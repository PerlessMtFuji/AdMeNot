"""Silnik kopii starego telefonu: telefonia → pliki paczkami → aplikacje → `manifest.csv`.

Port `BackupEngine` ze skryptu adb-backup. Gwarancje:
* stan po każdej paczce w SQLite — przerwanie (kabel, zamknięcie okna, brak miejsca) traci
  najwyżej jedną paczkę, a ponowne uruchomienie na tym samym `CopyDir` pomija pliki już
  skopiowane i niezmienione (`_reconcile`);
* plik jest „zrobiony” dopiero, gdy rozmiar na dysku zgadza się z telefonem (opcjonalnie też
  SHA-256 z `sha256sum` na telefonie);
* rozłączenie nie jest błędem pliku: czekamy na telefon (`wait_device`) i ponawiamy, do 20 razy;
* plik zmieniony na telefonie w trakcie kopii pobieramy ponownie, zniknięty pomijamy, a po
  3 nieudanych próbach oznaczamy jako błąd.

Na telefon idą wyłącznie odczyty: wszystko przechodzi przez `ReadOnlyAdb`, a kopia APK dostaje
tylko dodatkowo `pm path <pakiet>` i `pull` plików `.apk` tego pakietu (`_ApkReadAdb`). Dlatego
`adb` to surowy transport (nie `ReadOnlyAdb` — przez niego kopia APK by się nie udała).
"""

from __future__ import annotations

import csv
import hashlib
import os
import shutil
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from admenot.engine.actions.backup import backup_apks, is_complete
from admenot.engine.actions.errors import ActionError
from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.apk.cache import NoSpace
from admenot.engine.device.info import DeviceInfo

from .guard import ReadOnlyAdb, UnsafeCommand, q
from .inventory import Inventory, RemoteFile
from .puller import Puller
from .state import FileRow, State
from .store import CopyDir
from .telephony import _CONNECTION_KINDS, CategoryResult, Stopped, export_telephony
from .winpath import PathPlanner

CHUNK_MAX_FILES = 200
CHUNK_MAX_BYTES = 1024 ** 3
CMD_MAX_CHARS = 24_000  # linia poleceń Windows ma limit 32 767 znaków
DEVICE_CMD_MAX = 48_000  # limit długości polecenia `adb shell`
MAX_ATTEMPTS = 3
MAX_DISCONNECTS = 20
SPACE_MARGIN = 64 * 1024 ** 2  # zapas na dysku ponad rozmiar paczki
MANIFEST = "manifest.csv"
APK_TMP = ".apk-tmp"  # pobrane APK przed sprawdzeniem; usuwany po etapie aplikacji
TELEPHONY = ("contacts", "sms", "mms", "calls")

Stage = Literal["telephony", "files", "apps", "verify"]


@dataclass(frozen=True)
class Selection:
    contacts: bool
    sms: bool
    mms: bool
    calls: bool
    categories: frozenset[str]  # ⊆ {"media", "downloads", "whatsapp"}
    others: frozenset[str]  # nazwy folderów; "" = luźne pliki w głównym folderze
    apps: frozenset[str]  # pakiety
    verify_hash: bool = False

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("categories", "others", "apps"):
            data[key] = sorted(data[key])
        return data


@dataclass(frozen=True)
class Progress:
    stage: Stage
    done_files: int
    total_files: int
    done_bytes: int
    total_bytes: int
    current: str  # ścieżka względna — tylko do UI, nigdy do telemetrii


@dataclass(frozen=True)
class BackupResult:
    status: Literal["complete", "incomplete", "stopped"]
    copy_id: str
    telephony: dict[str, CategoryResult]
    files_done: int
    files_failed: int
    apps_done: int
    apps_failed: int
    bytes: int
    seconds: int


class BackupError(Exception):
    """Kopia zatrzymana; zostaje `in_progress`, więc ponowne uruchomienie ją wznowi."""

    def __init__(self, key: Literal["disk_full", "wrong_device", "too_many_disconnects"]) -> None:
        super().__init__(key)
        self.key = key


class _Stop(Exception):
    """Przerwanie na żądanie (wewnętrzne — `run_backup` zwraca wtedy `stopped`)."""


def _disk_free(path: Path) -> int:
    return shutil.disk_usage(path).free


class _ApkReadAdb:
    """`ReadOnlyAdb` + dokładnie to, czego potrzebuje `backup_apks` dla jednego pakietu."""

    def __init__(self, raw: AdbTransport, package: str) -> None:
        self.raw = raw
        self.ro = ReadOnlyAdb(raw)
        self.package = package

    @property
    def serial(self) -> str | None:
        return self.raw.serial

    def with_serial(self, serial: str) -> _ApkReadAdb:
        return _ApkReadAdb(self.raw.with_serial(serial), self.package)

    def shell(self, command: str, timeout: float = 20.0) -> str:
        if command == f"pm path {self.package}":
            return self.raw.shell(command, timeout=timeout)
        return self.ro.shell(command, timeout=timeout)

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        if len(args) == 3 and args[0] == "pull":
            remote = PurePosixPath(args[1])
            if remote.is_absolute() and remote.suffix == ".apk" and ".." not in remote.parts:
                return self.raw.run(args, timeout=timeout)
            raise UnsafeCommand(f"Niedozwolone pobranie: {args[1][:120]}")
        return self.ro.run(args, timeout=timeout)

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        return self.ro.run_bytes(args, timeout=timeout)


def run_backup(adb: AdbTransport, puller: Puller, device: DeviceInfo, copy: CopyDir, inventory: Inventory,
               selection: Selection, *, on_progress: Callable[[Progress], None],
               should_stop: Callable[[], bool], wait_device: Callable[[], None],
               free_bytes: Callable[[Path], int] = _disk_free) -> BackupResult:
    """Kopiuje wybrane dane do `copy`, wznawiając jej stan. `BackupError` i `stopped` zostawiają
    kopię `in_progress`; koniec to `complete` albo `incomplete` (zapisane w `meta.json`)."""
    return _Backup(adb, puller, device, copy, inventory, selection, on_progress, should_stop,
                   wait_device, free_bytes).run()


class _Backup:
    def __init__(self, adb: AdbTransport, puller: Puller, device: DeviceInfo, copy: CopyDir,
                 inventory: Inventory, selection: Selection, on_progress: Callable[[Progress], None],
                 should_stop: Callable[[], bool], wait_device: Callable[[], None],
                 free_bytes: Callable[[Path], int]) -> None:
        self.raw = adb
        self.adb = ReadOnlyAdb(adb)
        self.puller, self.device, self.copy, self.inventory = puller, device, copy, inventory
        self.sel = selection
        self.on_progress, self.should_stop, self.wait_device = on_progress, should_stop, wait_device
        self.free_bytes = free_bytes
        self.disconnects = 0
        self.hash_ok = True
        self.total_files = self.total_bytes = self.done_files = self.done_bytes = 0

    # ---- przebieg -----------------------------------------------------------------------
    def run(self) -> BackupResult:
        meta = self.copy.read_meta()
        if meta.serial != self.device.serial:
            raise BackupError("wrong_device")
        if not meta.selection:
            meta.selection = self.sel.to_json()
            self.copy.write_meta(meta)
        t0 = time.monotonic()
        state = State(self.copy.state_path)
        try:
            tel: dict[str, CategoryResult] = {}
            apps: dict[str, dict[str, Any]] = {}
            try:
                tel = self._telephony(state)
                self._reconcile(state)
                self._transfer(state)
                apps = self._apps(state)
            except _Stop:
                saved = state.get_meta("apps", {})
                apps = {p: saved[p] for p in sorted(self.sel.apps) if p in saved}
                return self._result(state, "stopped", tel, apps, t0)
            return self._finalize(state, tel, apps, t0)
        finally:
            state.close()

    def _progress(self, stage: Stage, current: str = "", inflight: int = 0) -> None:
        self.on_progress(Progress(stage, self.done_files, self.total_files, self.done_bytes + inflight,
                                  self.total_bytes, current))

    def _check_stop(self) -> None:
        if self.should_stop():
            raise _Stop()

    def _online(self) -> bool:
        try:
            return self.adb.run(["get-state"]).strip() == "device"
        except AdbError:
            return False

    def _disconnected(self) -> None:
        """Rozłączenie nie zużywa prób pliku — czekamy na telefon; limit chroni przed złym kablem."""
        self.disconnects += 1
        if self.disconnects > MAX_DISCONNECTS:
            raise BackupError("too_many_disconnects")
        self.wait_device()

    # ---- telefonia ----------------------------------------------------------------------
    def _telephony(self, state: State) -> dict[str, CategoryResult]:
        """Kategorie zakończone `ok` w poprzednim przebiegu nie są eksportowane ponownie."""
        wanted = [k for k in TELEPHONY if getattr(self.sel, k)]
        saved = {k: CategoryResult(**v) for k, v in state.get_meta("telephony", {}).items()}
        todo = [k for k in wanted if k not in saved or saved[k].status != "ok"]
        if todo:
            self._progress("telephony")
            while True:
                self._check_stop()
                try:
                    res = export_telephony(
                        self.adb, self.copy.phone_dir, contacts="contacts" in todo, sms="sms" in todo,
                        calls="calls" in todo, mms="mms" in todo, shell_v2=self.device.sdk >= 24,
                        should_stop=self.should_stop)
                    break
                except Stopped:
                    raise _Stop() from None
                except AdbError as exc:
                    if exc.kind not in _CONNECTION_KINDS:
                        raise
                    self._disconnected()
            saved.update(res)
            state.set_meta("telephony", {k: asdict(v) for k, v in saved.items()})
        return {k: saved[k] for k in wanted if k in saved}

    # ---- uzgadnianie stanu ----------------------------------------------------------------
    def _selected(self, f: RemoteFile) -> bool:
        if f.category.startswith("other:"):
            return f.category[len("other:"):] in self.sel.others
        return f.category in self.sel.categories

    def _local(self, rel: str) -> Path:
        return self.copy.files_dir.joinpath(*rel.split("/"))

    def _reconcile(self, state: State) -> None:
        """Wybrane pliki z inwentarza do stanu. Zrobione i niezmienione (rozmiar, czas, plik na
        dysku) zostają; reszta wraca do kolejki. Niewybrane i niezrobione → `skipped`."""
        existing = state.all_files()
        planner = PathPlanner(taken={r.local_rel.casefold(): r.remote for r in existing.values()})
        base_len = len(str(self.copy.files_dir))
        seen: set[str] = set()
        for f in self.inventory.files:
            if not self._selected(f) or f.remote in seen:
                continue
            seen.add(f.remote)
            row = existing.get(f.remote)
            if row is None:
                rel = planner.local_rel(f.remote, base_len)
                state.insert(FileRow(f.remote, f.category, f.size, f.mtime, rel, f.remote in planner.renamed,
                                     "pending", 0))
                continue
            if row.status == "done" and (row.size, row.mtime) == (f.size, f.mtime) and self._has(row):
                state.update(f.remote, root=f.category)
            else:
                state.update(f.remote, root=f.category, size=f.size, mtime=f.mtime, status="pending",
                             attempts=0, error=None, sha256=None)
        for remote, row in existing.items():
            if remote not in seen and row.status != "done":
                state.update(remote, status="skipped", error="not_selected")
        state.commit()

    def _has(self, row: FileRow) -> bool:
        try:
            return self._local(row.local_rel).stat().st_size == row.size
        except OSError:
            return False

    # ---- pliki ----------------------------------------------------------------------------
    def _transfer(self, state: State) -> None:
        totals = state.totals()
        self.total_files = sum(n for s, (n, _) in totals.items() if s in ("done", "pending"))
        self.total_bytes = sum(b for s, (_, b) in totals.items() if s in ("done", "pending"))
        self.done_files, self.done_bytes = totals.get("done", (0, 0))
        self._progress("files")
        while pend := state.pending():
            for chunk in _chunks(pend):
                self._check_stop()
                need = sum(f.size for f in chunk) + SPACE_MARGIN
                if self.free_bytes(self.copy.path) < need:
                    raise BackupError("disk_full")
                self._pull_chunk(state, chunk)

    def _pull_chunk(self, state: State, chunk: list[FileRow]) -> None:
        locals_ = [self._local(f.local_rel) for f in chunk]
        if len(chunk) == 1:  # pojedynczy plik → jawna ścieżka docelowa (obsługuje zmienione nazwy)
            target = locals_[0]
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            target = locals_[0].parent
            target.mkdir(parents=True, exist_ok=True)
        current = chunk[0].local_rel
        res = self.puller.pull([f.remote for f in chunk], target, self.should_stop,
                               lambda: self._progress("files", current, _inflight(chunk, locals_)))
        if res.stopped:
            self._salvage(state, chunk, locals_)
            raise _Stop()

        ok: list[tuple[FileRow, Path]] = []
        failed: list[tuple[FileRow, Path]] = []
        for f, loc in zip(chunk, locals_, strict=True):
            try:
                size = loc.stat().st_size
            except OSError:
                size = -1
            (ok if size == f.size else failed).append((f, loc))
        sums: dict[str, str] = {}
        if self.sel.verify_hash and self.hash_ok and ok:
            self._progress("verify", current)
            ok, bad, sums = self._verify(ok)
            failed += bad
        for f, _ in ok:
            state.update(f.remote, status="done", error=None, sha256=sums.get(f.remote))
            self.done_files += 1
            self.done_bytes += f.size
        if failed:
            msg = next((ln for ln in res.lines if "error" in ln.lower()), res.lines[-1] if res.lines else "")
            self._handle_failures(state, failed, msg or f"adb pull rc {res.rc}")
        state.commit()
        self._progress("files", current)

    def _salvage(self, state: State, chunk: list[FileRow], locals_: list[Path]) -> None:
        """Po przerwaniu: pliki kompletne (rozmiar + czas, który `pull -a` ustawia dopiero na
        końcu pliku) są gotowe; nasze niedokończone usuwamy. Z SHA-256 nic nie zaliczamy bez sumy."""
        for f, loc in zip(chunk, locals_, strict=True):
            try:
                st = loc.stat()
            except OSError:
                continue
            if st.st_size == f.size and int(st.st_mtime) == f.mtime and not self.sel.verify_hash:
                state.update(f.remote, status="done", error=None, sha256=None)
                self.done_files += 1
                self.done_bytes += f.size
            else:
                loc.unlink(missing_ok=True)
        state.commit()

    def _handle_failures(self, state: State, failed: list[tuple[FileRow, Path]], msg: str) -> None:
        for f, loc in failed:
            try:
                if loc.stat().st_size != f.size:
                    loc.unlink()
            except OSError:
                pass
        if not self._online():
            self._disconnected()
            return
        try:
            current = self._restat([f.remote for f, _ in failed])
        except AdbError:  # błąd połączenia tuż po sprawdzeniu stanu
            self._disconnected()
            return
        for f, _ in failed:
            attempts = f.attempts + 1
            now = current.get(f.remote)
            if now is None:
                state.update(f.remote, status="skipped", error="vanished")
            elif now != (f.size, f.mtime):
                self.total_bytes += now[0] - f.size
                state.update(f.remote, size=now[0], mtime=now[1], attempts=attempts, error="changed",
                             status="error" if attempts >= MAX_ATTEMPTS else "pending")
            else:
                state.update(f.remote, attempts=attempts, error=msg[:300],
                             status="error" if attempts >= MAX_ATTEMPTS else "pending")

    def _restat(self, remotes: list[str]) -> dict[str, tuple[int, int]]:
        """Aktualny (rozmiar, mtime) z telefonu; brak wpisu = pliku nie ma. `stat` kończy się błędem,
        gdy brakuje choć jednego pliku — wtedy pytamy o każdy osobno. Błąd połączenia idzie wyżej."""
        res: dict[str, tuple[int, int]] = {}
        for batch in _cmd_batches(remotes):
            try:
                out = self.adb.shell("stat -c " + q("%s|%Y|%n") + " " + " ".join(q(r) for r in batch),
                                     timeout=120)
            except AdbError as exc:
                if exc.kind in _CONNECTION_KINDS:
                    raise
                if len(batch) > 1:
                    for remote in batch:
                        res.update(self._restat([remote]))
                continue
            for line in out.split("\n"):
                bits = line.split("|", 2)
                if len(bits) == 3 and bits[0].isdigit() and bits[1].lstrip("-").isdigit():
                    res[bits[2]] = (int(bits[0]), int(bits[1]))
        return res

    def _verify(self, ok: list[tuple[FileRow, Path]]
                ) -> tuple[list[tuple[FileRow, Path]], list[tuple[FileRow, Path]], dict[str, str]]:
        """(zgodne, niezgodne, sumy). Brak `sha256sum` na telefonie → dalej tylko rozmiar.
        Rozłączenie albo przekroczenie czasu → żaden plik paczki nie jest zaliczony (ponowimy)."""
        remote: dict[str, str] = {}
        for batch in _cmd_batches([f.remote for f, _ in ok]):
            try:
                out = self.adb.shell("sha256sum " + " ".join(q(r) for r in batch), timeout=3600)
            except AdbError as exc:
                if exc.kind in _CONNECTION_KINDS or exc.kind == "timeout":
                    return [], ok, {}
                self.hash_ok = False
                return ok, [], {}
            for line in out.split("\n"):
                if len(line) > 66 and line[64:66] == "  ":
                    remote[line[66:]] = line[:64].lower()
        good, bad, sums = [], [], {}
        for f, loc in ok:
            with loc.open("rb") as fh:
                digest = hashlib.file_digest(fh, "sha256").hexdigest()
            if remote.get(f.remote) == digest:
                good.append((f, loc))
                sums[f.remote] = digest
            else:
                bad.append((f, loc))
        return good, bad, sums

    # ---- aplikacje ------------------------------------------------------------------------
    def _apps(self, state: State) -> dict[str, dict[str, Any]]:
        """Wybrane aplikacje z inwentarza (złośliwych tam nie ma). Zrobione wcześniej i nadal
        kompletne na dysku pomijamy bez pytania telefonu."""
        saved: dict[str, dict[str, Any]] = state.get_meta("apps", {})
        entries = [a for a in self.inventory.apps if a.package in self.sel.apps]
        tmp = self.copy.path / APK_TMP
        for entry in entries:
            self._check_stop()
            target = self.copy.apps_dir / entry.package / (
                str(entry.version_code) if entry.version_code is not None else "unknown")
            prev = saved.get(entry.package)
            if prev and prev.get("status") == "done" and is_complete(target, entry.package):
                continue
            self._progress("apps", entry.package)
            saved[entry.package] = self._app(entry.package, entry.version_code, target, tmp)
            state.set_meta("apps", saved)
        shutil.rmtree(tmp, ignore_errors=True)
        return {a.package: saved[a.package] for a in entries}

    def _app(self, package: str, version_code: int | None, target: Path, tmp: Path) -> dict[str, Any]:
        while True:
            try:
                paths = backup_apks(_ApkReadAdb(self.raw, package), package, version_code, target, tmp)
                return {"status": "done", "bytes": sum(p.stat().st_size for p in paths)}
            except NoSpace:
                raise BackupError("disk_full") from None
            except AdbError as exc:
                if exc.kind not in _CONNECTION_KINDS:
                    return {"status": "failed", "error": exc.kind}
                self._disconnected()
            except (ActionError, UnsafeCommand, ValueError, OSError) as exc:
                return {"status": "failed", "error": type(exc).__name__}

    # ---- wynik ----------------------------------------------------------------------------
    def _result(self, state: State, status: Literal["complete", "incomplete", "stopped"],
                tel: dict[str, CategoryResult], apps: dict[str, dict[str, Any]], t0: float) -> BackupResult:
        cnt = Counter(r.status for r in state.all_files().values())
        files_bytes = state.totals().get("done", (0, 0))[1]
        app_bytes = sum(int(a.get("bytes", 0)) for a in apps.values() if a.get("status") == "done")
        return BackupResult(
            status=status, copy_id=f"{self.copy.path.parent.name}/{self.copy.path.name}", telephony=tel,
            files_done=cnt.get("done", 0), files_failed=cnt.get("error", 0),
            apps_done=sum(1 for a in apps.values() if a.get("status") == "done"),
            apps_failed=sum(1 for a in apps.values() if a.get("status") != "done"),
            bytes=files_bytes + app_bytes, seconds=round(time.monotonic() - t0))

    def _finalize(self, state: State, tel: dict[str, CategoryResult], apps: dict[str, dict[str, Any]],
                  t0: float) -> BackupResult:
        """`manifest.csv` (Excel: `;`, UTF-8 z BOM) i `meta.json`. Kompletna = nic w kolejce, żadnego
        błędu pliku, każda wybrana kategoria telefonii `ok` i każda wybrana aplikacja skopiowana.
        Plik, który zniknął z telefonu (`skipped`), kompletności nie psuje — nie ma czego kopiować."""
        rows = sorted(state.all_files().values(), key=lambda r: r.remote)
        manifest = self.copy.path / MANIFEST
        tmp = manifest.with_name(MANIFEST + ".tmp")
        with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["status", "remote", "local_rel", "size", "mtime", "sha256"])
            for r in rows:
                w.writerow([r.status, r.remote, f"{self.copy.files_dir.name}/{r.local_rel}", r.size,
                            datetime.fromtimestamp(r.mtime).isoformat(sep=" ") if r.mtime > 0 else "",
                            r.sha256 or ""])
        os.replace(tmp, manifest)

        cnt = Counter(r.status for r in rows)
        complete = (cnt.get("pending", 0) == 0 and cnt.get("error", 0) == 0
                    and all(v.status == "ok" for v in tel.values())
                    and all(a.get("status") == "done" for a in apps.values()))
        result = self._result(state, "complete" if complete else "incomplete", tel, apps, t0)
        meta = self.copy.read_meta()
        meta.status = result.status  # type: ignore[assignment]  # tu tylko complete/incomplete
        meta.counts = {"files": result.files_done, "files_failed": result.files_failed,
                       "files_skipped": cnt.get("skipped", 0), "apps": result.apps_done,
                       "apps_failed": result.apps_failed,
                       **{k: v.count for k, v in tel.items()}}
        meta.bytes = result.bytes
        self.copy.write_meta(meta)
        return result


def _inflight(chunk: list[FileRow], locals_: list[Path]) -> int:
    total = 0
    for f, loc in zip(chunk, locals_, strict=True):
        try:
            total += min(loc.stat().st_size, f.size)
        except OSError:
            pass
    return total


def _chunks(pend: list[FileRow]) -> list[list[FileRow]]:
    """Paczki ≤ 200 plików / ≤ 1 GB z jednego katalogu (na telefonie i na dysku). Plik
    o zmienionej nazwie albo ponawiany idzie sam — z jawną ścieżką docelową."""
    chunks: list[list[FileRow]] = []
    cur: list[FileRow] = []
    cur_key: tuple[str, str] | None = None
    cur_bytes = cur_chars = 0
    for f in pend:
        if f.renamed or f.attempts > 0:
            if cur:
                chunks.append(cur)
            chunks.append([f])
            cur, cur_key, cur_bytes, cur_chars = [], None, 0, 0
            continue
        key = (f.remote.rsplit("/", 1)[0], f.local_rel.rsplit("/", 1)[0] if "/" in f.local_rel else "")
        chars = len(f.remote) + 3
        if cur and (key != cur_key or len(cur) >= CHUNK_MAX_FILES or cur_bytes + f.size > CHUNK_MAX_BYTES
                    or cur_chars + chars > CMD_MAX_CHARS):
            chunks.append(cur)
            cur, cur_bytes, cur_chars = [], 0, 0
        cur.append(f)
        cur_key = key
        cur_bytes += f.size
        cur_chars += chars
    if cur:
        chunks.append(cur)
    return chunks


def _cmd_batches(remotes: list[str]) -> list[list[str]]:
    batches: list[list[str]] = []
    cur: list[str] = []
    n = 0
    for r in remotes:
        ln = len(q(r)) + 1
        if cur and n + ln > DEVICE_CMD_MAX:
            batches.append(cur)
            cur, n = [], 0
        cur.append(r)
        n += ln
    if cur:
        batches.append(cur)
    return batches
