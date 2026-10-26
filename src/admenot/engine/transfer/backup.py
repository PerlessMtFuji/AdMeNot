"""Silnik kopii starego telefonu: telefonia → pliki paczkami → aplikacje → `manifest.csv`.

Port `BackupEngine` ze skryptu adb-backup. Gwarancje:
* stan po każdej paczce w SQLite — przerwanie (kabel, zamknięcie okna, brak miejsca) traci
  najwyżej jedną paczkę, a ponowne uruchomienie na tym samym `CopyDir` pomija pliki już
  skopiowane i niezmienione (`_reconcile`);
* plik jest „zrobiony” dopiero, gdy rozmiar na dysku zgadza się z telefonem (opcjonalnie też
  SHA-256 z `sha256sum` na telefonie);
* rozłączenie nie jest błędem pliku: czekamy na telefon (`wait_device`) i ponawiamy, do 20 razy;
* plik zmieniony na telefonie w trakcie kopii pobieramy ponownie; pomijamy tylko plik, którego
  na pewno już nie ma (`No such file`); po 3 nieudanych próbach — błąd.

Na telefon idą wyłącznie odczyty: wszystko przechodzi przez `guard.ReadOnlyAdb`, a kopia APK przez
`guard.ApkReadAdb` (dodatkowo tylko `pm path <pakiet>` i `pull` plików `.apk` tego pakietu).
Błędy w stanie i w `manifest.csv` to klucze, nie tekst.
"""

from __future__ import annotations

import csv
import errno
import hashlib
import os
import shutil
import sqlite3
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from admenot.engine.actions.backup import backup_apks, is_complete
from admenot.engine.actions.errors import ActionError
from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.apk.cache import NoSpace
from admenot.engine.device.info import DeviceInfo

from .guard import ApkReadAdb, ReadOnlyAdb, UnsafeCommand, q
from .inventory import Inventory
from .puller import Puller
from .state import FileRow, State
from .store import KEEP_DAYS, CopyDir
from .telephony import _CONNECTION_KINDS, CategoryResult, Stopped, export_telephony
from .winpath import PathPlanner

CHUNK_MAX_FILES = 200
CHUNK_MAX_BYTES = 1024 ** 3
CMD_MAX_CHARS = 24_000  # linia poleceń Windows ma limit 32 767 znaków
DEVICE_CMD_MAX = 48_000  # limit długości polecenia `adb shell`
MAX_ATTEMPTS = 3
MAX_DISCONNECTS = 20
SPACE_MARGIN = 64 * 1024 ** 2  # zapas na dysku ponad rozmiar paczki / eksportu / APK
MMS_FACTOR = 2.4  # załączniki jako pliki + te same dane w base64 w mms.xml
MANIFEST = "manifest.csv"
APK_TMP = ".apk-tmp"  # pobrane APK przed sprawdzeniem; usuwany po etapie aplikacji
TELEPHONY = ("contacts", "sms", "mms", "calls")
_GONE = ("no such file", "does not exist")  # `stat`/`sha256sum`: pliku na pewno nie ma
_NO_TOOL = ("not found", "inaccessible")  # `sha256sum` niedostępne na telefonie

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
    done_apps: int = 0  # obsłużone (skopiowane, nieudane, pominięte) — pliki kończą się przed aplikacjami
    total_apps: int = 0


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


def _has(text: str, needles: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(n in low for n in needles)


Failed = list[tuple[FileRow, Path, str]]  # (wiersz, plik lokalny, klucz powodu)


def run_backup(adb: AdbTransport, puller: Puller, device: DeviceInfo, copy: CopyDir, inventory: Inventory,
               selection: Selection, *, on_progress: Callable[[Progress], None],
               should_stop: Callable[[], bool], wait_device: Callable[[], None],
               free_bytes: Callable[[Path], int] = _disk_free,
               now: datetime | None = None) -> BackupResult:
    """Kopiuje wybrane dane do `copy`, wznawiając jej stan.

    `adb` to surowy transport (nie `ReadOnlyAdb`): silnik sam opakowuje go w `ReadOnlyAdb`, a na
    kopię APK w `ApkReadAdb` — przez gotowy `ReadOnlyAdb` kopia aplikacji by się nie udała.
    `BackupError` i `stopped` zostawiają kopię `in_progress` (do wznowienia); koniec to `complete`
    albo `incomplete` (zapisane w `meta.json`). Wznowienie z terminem krótszym niż dzień od `now`
    dostaje `KEEP_DAYS` dni od wznowienia.
    """
    return _Backup(adb, puller, device, copy, inventory, selection, on_progress, should_stop,
                   wait_device, free_bytes, now or datetime.now()).run()


class _Backup:
    def __init__(self, adb: AdbTransport, puller: Puller, device: DeviceInfo, copy: CopyDir,
                 inventory: Inventory, selection: Selection, on_progress: Callable[[Progress], None],
                 should_stop: Callable[[], bool], wait_device: Callable[[], None],
                 free_bytes: Callable[[Path], int], now: datetime) -> None:
        self.raw = adb
        self.now = now
        self.adb = ReadOnlyAdb(adb)
        self.puller, self.device, self.copy, self.inventory = puller, device, copy, inventory
        self.sel = selection
        self.on_progress, self.should_stop, self.wait_device = on_progress, should_stop, wait_device
        self.free_bytes = free_bytes
        self.disconnects = 0
        self.hash_ok = True
        self.total_files = self.total_bytes = self.done_files = self.done_bytes = 0
        self.done_apps, self.total_apps = 0, len(selection.apps)

    # ---- przebieg -----------------------------------------------------------------------
    def run(self) -> BackupResult:
        """Pełny dysk — także przy zapisie `meta.json` przed startem i w SQLite (`database or disk
        is full`) — to `disk_full`, nie błąd programu."""
        try:
            return self._run()
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise BackupError("disk_full") from exc
            raise
        except sqlite3.OperationalError as exc:
            if _has(str(exc), ("disk is full",)):
                raise BackupError("disk_full") from exc
            raise

    def _run(self) -> BackupResult:
        meta = self.copy.read_meta()
        if meta.serial != self.device.serial:
            raise BackupError("wrong_device")
        meta.status = "in_progress"  # ponowne uruchomienie, które się urwie, zostaje do wznowienia
        meta.selection = self.sel.to_json()
        if meta.expires < self.now + timedelta(days=1):
            # wznowienie kopii tuż przed (albo po) terminie: po zakończeniu nie znika od razu
            meta.expires = max(meta.expires, self.now + timedelta(days=KEEP_DAYS))
        self.copy.write_meta(meta)
        self.copy.write_verdicts(self.inventory.apps + self.inventory.skipped_apps)
        t0 = time.monotonic()
        state = State(self.copy.state_path)
        try:
            tel: dict[str, CategoryResult] = {}
            try:
                tel = self._telephony(state)
                self._reconcile(state)
                self._transfer(state)
                apps = self._apps(state)
            except _Stop:
                result = self._result(state, "stopped", tel, self._saved_apps(state), t0)
                self._save_partial(state, t0, result)
                return result
            return self._finalize(state, tel, apps, t0)
        except (BackupError, OSError, sqlite3.Error):
            self._save_partial(state, t0)
            raise
        finally:
            state.close()

    def _progress(self, stage: Stage, current: str = "", inflight: int = 0) -> None:
        self.on_progress(Progress(stage, self.done_files, self.total_files, self.done_bytes + inflight,
                                  self.total_bytes, current, self.done_apps, self.total_apps))

    def _check_stop(self) -> None:
        if self.should_stop():
            raise _Stop()

    def _need(self, nbytes: int) -> None:
        if self.free_bytes(self.copy.path) < nbytes + SPACE_MARGIN:
            raise BackupError("disk_full")

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
            self._need(int(self.inventory.mms_bytes * MMS_FACTOR) if "mms" in todo else 0)
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
    def _wanted(self, category: str) -> bool:
        if category.startswith("other:"):
            return category[len("other:"):] in self.sel.others
        return category in self.sel.categories

    def _local(self, rel: str) -> Path:
        return self.copy.files_dir.joinpath(*rel.split("/"))

    def _reconcile(self, state: State) -> None:
        """Wybrane pliki z inwentarza do stanu. Zrobione i niezmienione (rozmiar, czas, plik na
        dysku) zostają; reszta wraca do kolejki. Niezrobione spoza inwentarza → `skipped`:
        `vanished`, gdy ich kategoria nadal jest wybrana, inaczej `not_selected`."""
        existing = state.all_files()
        planner = PathPlanner(taken={r.local_rel.casefold(): r.remote for r in existing.values()})
        base_len = len(str(self.copy.files_dir))
        seen: set[str] = set()
        for f in self.inventory.files:
            if not self._wanted(f.category) or f.remote in seen:
                continue
            seen.add(f.remote)
            row = existing.get(f.remote)
            if row is None:
                rel = planner.local_rel(f.remote, base_len)
                state.insert(FileRow(f.remote, f.category, f.size, f.mtime, rel, f.remote in planner.renamed,
                                     "pending", 0))
                continue
            if row.status == "done" and (row.size, row.mtime) == (f.size, f.mtime) and self._on_disk(row):
                state.update(f.remote, root=f.category)
            else:
                state.update(f.remote, root=f.category, size=f.size, mtime=f.mtime, status="pending",
                             attempts=0, error=None, sha256=None)
        for remote, row in existing.items():
            if remote not in seen and row.status != "done":
                state.update(remote, status="skipped",
                             error="vanished" if self._wanted(row.root) else "not_selected")
        state.commit()

    def _on_disk(self, row: FileRow) -> bool:
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
                self._need(sum(f.size for f in chunk))
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
        failed: Failed = []
        for f, loc in zip(chunk, locals_, strict=True):
            try:
                size = loc.stat().st_size
            except OSError:
                size = -1
            if size == f.size:
                ok.append((f, loc))
            else:
                failed.append((f, loc, "pull_failed"))
        sums: dict[str, str] = {}
        if self.sel.verify_hash and self.hash_ok and ok:
            self._progress("verify", current)
            ok, bad, sums = self._verify(ok)
            failed += bad
        for f, _ in ok:
            state.update(f.remote, status="done", error=None, sha256=sums.get(f.remote))
            self.done_files += 1
            self.done_bytes += f.size
        state.commit()  # przed czekaniem na telefon / `too_many_disconnects` — zrobione zostają
        if failed:
            self._handle_failures(state, failed)
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
                try:
                    loc.unlink(missing_ok=True)
                except OSError:  # zablokowany (np. antywirus): zostaje `pending`, następny pull go nadpisze
                    pass
        state.commit()

    def _handle_failures(self, state: State, failed: Failed) -> None:
        for f, loc, _ in failed:
            try:
                if loc.stat().st_size != f.size:
                    loc.unlink()
            except OSError:
                pass
        if not self._online():
            self._disconnected()
            return
        try:
            current, gone = restat(self.adb, [f.remote for f, _, _ in failed])
        except AdbError:  # błąd połączenia tuż po sprawdzeniu stanu
            self._disconnected()
            return
        for f, _, reason in failed:
            attempts = f.attempts + 1
            now = current.get(f.remote)
            if f.remote in gone:
                state.update(f.remote, status="skipped", error="vanished")
                self.total_files -= 1
                self.total_bytes -= f.size
            elif now is not None and now != (f.size, f.mtime):
                self.total_bytes += now[0] - f.size
                state.update(f.remote, size=now[0], mtime=now[1], attempts=attempts, error="changed",
                             status="error" if attempts >= MAX_ATTEMPTS else "pending")
            else:  # bez zmian albo `stat` się nie udał (np. przekroczenie czasu) — zwykła próba
                state.update(f.remote, attempts=attempts, error=reason,
                             status="error" if attempts >= MAX_ATTEMPTS else "pending")

    def _verify(self, ok: list[tuple[FileRow, Path]]
                ) -> tuple[list[tuple[FileRow, Path]], Failed, dict[str, str]]:
        """(zgodne, niezaliczone z powodem, sumy). Brak `sha256sum` na telefonie → dalej tylko
        rozmiar (liczba takich plików trafia do `meta.counts["size_only"]`). Inny błąd paczki → po
        jednym pliku; plik bez sumy zużywa próbę. Rozłączenie → nic z paczki nie jest zaliczone."""
        remote = self._remote_hashes([f.remote for f, _ in ok])
        if remote is None:
            return [], [(f, loc, "hash_unavailable") for f, loc in ok], {}
        if not self.hash_ok:
            return ok, [], {}
        good: list[tuple[FileRow, Path]] = []
        bad: Failed = []
        sums: dict[str, str] = {}
        for f, loc in ok:
            if f.remote not in remote:
                bad.append((f, loc, "hash_unavailable"))
                continue
            with loc.open("rb") as fh:
                digest = hashlib.file_digest(fh, "sha256").hexdigest()
            if remote[f.remote] == digest:
                good.append((f, loc))
                sums[f.remote] = digest
            else:
                bad.append((f, loc, "hash_mismatch"))
        return good, bad, sums

    def _remote_hashes(self, remotes: list[str]) -> dict[str, str] | None:
        """Sumy z telefonu; None = rozłączenie. Brak narzędzia ustawia `hash_ok = False`."""
        res: dict[str, str] = {}
        for batch in _cmd_batches(remotes):
            try:
                out = self.adb.shell("sha256sum " + " ".join(q(r) for r in batch), timeout=3600)
            except AdbError as exc:
                if exc.kind in _CONNECTION_KINDS:
                    return None
                if exc.kind == "command_failed" and _has(exc.message, _NO_TOOL):
                    self.hash_ok = False
                    return res
                if len(batch) > 1:
                    for one in batch:
                        sub = self._remote_hashes([one])
                        if sub is None:
                            return None
                        if not self.hash_ok:
                            return res
                        res.update(sub)
                continue
            for line in out.split("\n"):
                if len(line) > 66 and line[64:66] == "  ":
                    res[line[66:]] = line[:64].lower()
        return res

    # ---- aplikacje ------------------------------------------------------------------------
    def _apps(self, state: State) -> dict[str, dict[str, Any]]:
        """Wybrane aplikacje z inwentarza (złośliwych tam nie ma). Zrobione wcześniej i nadal
        kompletne na dysku pomijamy bez pytania telefonu. Wybrany pakiet spoza inwentarza →
        `skipped` (`not_in_inventory`), widoczny w `meta.counts`."""
        saved: dict[str, dict[str, Any]] = state.get_meta("apps", {})
        entries = {a.package: a for a in self.inventory.apps if a.package in self.sel.apps}
        tmp = self.copy.path / APK_TMP
        for package in sorted(self.sel.apps):
            entry = entries.get(package)
            if entry is None:
                saved[package] = {"status": "skipped", "error": "not_in_inventory"}
                state.set_meta("apps", saved)
                self.done_apps += 1
                continue
            self._check_stop()
            target = self.copy.apps_dir / package / (
                str(entry.version_code) if entry.version_code is not None else "unknown")
            prev = saved.get(package)
            if not (prev and prev.get("status") == "done" and is_complete(target, package)):
                self._progress("apps", package)
                self._need(0)
                saved[package] = self._app(package, entry.version_code, target, tmp)
                state.set_meta("apps", saved)
            self.done_apps += 1
        if self.sel.apps:
            self._progress("apps")
        shutil.rmtree(tmp, ignore_errors=True)
        return self._saved_apps(state)

    def _saved_apps(self, state: State) -> dict[str, dict[str, Any]]:
        saved = state.get_meta("apps", {})
        return {p: saved[p] for p in sorted(self.sel.apps) if p in saved}

    def _app(self, package: str, version_code: int | None, target: Path, tmp: Path) -> dict[str, Any]:
        while True:
            self._check_stop()  # przerwanie w czasie czekania na telefon: bez kolejnych prób
            try:
                paths = backup_apks(ApkReadAdb(self.raw, package), package, version_code, target, tmp)
                return {"status": "done", "bytes": sum(p.stat().st_size for p in paths)}
            except NoSpace:
                raise BackupError("disk_full") from None
            except AdbError as exc:
                # Kabel wyrwany w trakcie `pull` daje `command_failed`, więc pytamy o telefon.
                if exc.kind not in _CONNECTION_KINDS and self._online():
                    return {"status": "failed", "error": exc.kind}
                self._disconnected()
            except OSError as exc:
                if exc.errno == errno.ENOSPC:
                    raise BackupError("disk_full") from exc
                return {"status": "failed", "error": "OSError"}
            except (ActionError, UnsafeCommand, ValueError) as exc:
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
            apps_failed=sum(1 for a in apps.values() if a.get("status") == "failed"),
            bytes=files_bytes + app_bytes, seconds=round(time.monotonic() - t0))

    def _finalize(self, state: State, tel: dict[str, CategoryResult], apps: dict[str, dict[str, Any]],
                  t0: float) -> BackupResult:
        """`manifest.csv` (Excel: `;`, UTF-8 z BOM) i `meta.json`. Kompletna = nic w kolejce, żadnego
        błędu pliku, każda wybrana kategoria telefonii `ok` i żadna wybrana aplikacja nieudana.
        Plik, którego na pewno nie ma już na telefonie (`vanished`), kompletności nie psuje."""
        rows = sorted(state.all_files().values(), key=lambda r: r.remote)
        manifest = self.copy.path / MANIFEST
        tmp = manifest.with_name(MANIFEST + ".tmp")
        with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["status", "remote", "local_rel", "size", "mtime", "sha256", "reason"])
            for r in rows:
                w.writerow([r.status, r.remote, f"{self.copy.files_dir.name}/{r.local_rel}", r.size,
                            datetime.fromtimestamp(r.mtime).isoformat(sep=" ") if r.mtime > 0 else "",
                            r.sha256 or "", r.error if r.status != "done" and r.error else ""])
        os.replace(tmp, manifest)

        cnt = Counter(r.status for r in rows)
        complete = (cnt.get("pending", 0) == 0 and cnt.get("error", 0) == 0
                    and all(v.status == "ok" for v in tel.values())
                    and all(a.get("status") != "failed" for a in apps.values()))
        result = self._result(state, "complete" if complete else "incomplete", tel, apps, t0)
        meta = self.copy.read_meta()
        meta.status = result.status  # type: ignore[assignment]  # tu tylko complete/incomplete
        meta.counts = self._counts(rows, result, tel, apps)
        meta.bytes = result.bytes
        self.copy.write_meta(meta)
        return result

    def _counts(self, rows: list[FileRow], result: BackupResult, tel: dict[str, CategoryResult],
                apps: dict[str, dict[str, Any]]) -> dict[str, int]:
        """Liczniki do `meta.counts`. `unreadable` — pliki i foldery, których skan nie odczytał
        (nie trafiły do kopii, choć kopia może być „kompletna”)."""
        cnt = Counter(r.status for r in rows)
        counts = {"files": result.files_done, "files_failed": result.files_failed,
                  "files_skipped": cnt.get("skipped", 0), "apps": result.apps_done,
                  "apps_failed": result.apps_failed,
                  "apps_skipped": sum(1 for a in apps.values() if a.get("status") == "skipped"),
                  "unreadable": self.inventory.unreadable,
                  **{k: v.count for k, v in tel.items()}}
        if self.sel.verify_hash:
            counts["size_only"] = sum(1 for r in rows if r.status == "done" and not r.sha256)
        return counts

    def _saved_tel(self, state: State) -> dict[str, CategoryResult]:
        saved = state.get_meta("telephony", {})
        return {k: CategoryResult(**saved[k]) for k in TELEPHONY if getattr(self.sel, k) and k in saved}

    def _save_partial(self, state: State, t0: float, result: BackupResult | None = None) -> None:
        """Przerwana kopia (zatrzymanie, `BackupError`, błąd dysku) zostaje `in_progress`, ale
        bajty i liczniki tego, co już skopiowano, trafiają do `meta.json` — Historia nie pokazuje
        0 B. Najlepsza próba: pełny dysk przy zapisie nie zasłania pierwotnej przyczyny."""
        try:
            if result is None:
                result = self._result(state, "stopped", self._saved_tel(state),
                                      self._saved_apps(state), t0)
            meta = self.copy.read_meta()
            meta.counts = self._counts(list(state.all_files().values()), result, result.telephony,
                                       self._saved_apps(state))
            meta.bytes = result.bytes
            self.copy.write_meta(meta)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            pass


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


def restat(adb: AdbTransport, remotes: list[str]) -> tuple[dict[str, tuple[int, int]], set[str]]:
    """(aktualny rozmiar i mtime, pliki, których na pewno nie ma). `stat` kończy się błędem,
    gdy brakuje choć jednego pliku — wtedy pytamy o każdy osobno. Plik bez odpowiedzi i bez
    `No such file` (przekroczenie czasu, brak dostępu) nie trafia do żadnego z wyników.
    Błąd połączenia idzie wyżej. Wspólne dla kopii i planu wgrywania (`restore_plan`)."""
    stats: dict[str, tuple[int, int]] = {}
    gone: set[str] = set()
    for batch in _cmd_batches(remotes):
        try:
            out = adb.shell("stat -c " + q("%s|%Y|%n") + " " + " ".join(q(r) for r in batch), timeout=120)
        except AdbError as exc:
            if exc.kind in _CONNECTION_KINDS:
                raise
            if len(batch) > 1:
                for remote in batch:
                    s, g = restat(adb, [remote])
                    stats.update(s)
                    gone |= g
            elif exc.kind == "command_failed" and _has(exc.message, _GONE):
                gone.add(batch[0])
            continue
        for line in out.split("\n"):
            bits = line.split("|", 2)
            if len(bits) == 3 and bits[0].isdigit() and bits[1].lstrip("-").isdigit():
                stats[bits[2]] = (int(bits[0]), int(bits[1]))
    return stats, gone


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
