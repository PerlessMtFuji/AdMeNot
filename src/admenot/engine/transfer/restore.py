"""Silnik wgrywania kopii na nowy telefon (spec Etapu 2 §4.3, §8a).

Port `_restore_files`/`_push_chunks`/`_push_chunk` ze skryptu adb-backup. Gwarancje:
* tylko dopisywanie: na telefon idą `mkdir -p`, `adb push`, odczyty (`stat`, `df`, `sha256sum`)
  i skan mediów — wołający podaje `guard.AppendOnlyAdb` i `RealPusher`;
* pliki idą wyłącznie pod cele z planu; nadpisać wolno tylko własny niedokończony plik (stan
  `pushing` albo nieudana próba w tym stanie); plik „już jest” nigdy nie jest wgrywany;
* plan może się zestarzeć: tuż przed każdą paczką jeden `stat` jej celów — cudzy plik, który
  pojawił się od planu, zostaje nietknięty (identyczny → `exists`, inny → nazwa zastępcza);
* stan w SQLite po każdej paczce, osobno dla każdego telefonu docelowego — przerwanie (kabel,
  zamknięcie okna, brak miejsca) traci najwyżej paczki w locie;
* małe pliki w `streams` równoległych `adb push`, duże potem w jednym strumieniu; stan zapisuje
  tylko wątek główny (wątki zwracają wynik `push`);
* rozłączenie nie jest błędem pliku: paczki z tej rundy wracają do kolejki bez liczenia próby,
  jedno `wait_device()` na rundę, do `MAX_DISCONNECTS` razy;
* odmowa zapisu przez Androida (`Permission denied`, `Read-only file system`) → `denied` bez
  ponawiania; inny błąd → ponowienie, po `MAX_ATTEMPTS` próbach `error`.
"""

from __future__ import annotations

import csv
import hashlib
import posixpath
import re
import time
from collections import Counter, deque
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.device.info import DeviceInfo

from .backup import (
    CHUNK_MAX_FILES,
    CMD_MAX_CHARS,
    MANIFEST,
    MAX_ATTEMPTS,
    MAX_DISCONNECTS,
    _cmd_batches,
)
from .guard import SCAN_VOLUME_CMD, q, safe_target
from .puller import PullResult
from .pusher import Pusher
from .restore_plan import (
    MTIME_TOLERANCE,
    Action,
    PlanFile,
    RestorePlan,
    _apk_selected,
    read_space,
    resolve_conflicts,
    same_file,
    stat_all,
)
from .restore_state import RestoreRow, RestoreState, is_own, read_restores, restore_state_path
from .store import CopyDir
from .telephony import _CONNECTION_KINDS
from .telplan import TelPlan

MiB = 1024 ** 2
SMALL_MAX = 16 * MiB  # mniejsze pliki idą równolegle
STREAMS = 4
SMALL_CHUNK_BYTES = 256 * MiB
BIG_CHUNK_BYTES = 1024 * MiB
SCAN_TIMEOUT = 3600  # s
HASH_TIMEOUT = 3600  # s na paczkę `sha256sum`
_DENIED = ("permission denied", "read-only file system")
_NO_TOOL = ("not found", "inaccessible")
_SDCARD_PATH = re.compile(r"/sdcard/[^'\"\n:]+")

Status = Literal["complete", "incomplete", "stopped"]
MediaScan = Literal["done", "failed", "restart", "skipped"]
ErrorKey = Literal["phone_full", "too_many_disconnects", "wrong_device", "copy_missing"]

@dataclass(frozen=True)
class UploadChoice:
    groups: frozenset[str]  # ⊆ UPLOAD_GROUPS ∪ {"other:…"}
    apks_on: frozenset[str]  # `remote` podejrzanych APK zaznaczonych przez serwisanta
    verify_hash: bool = False
    tel: frozenset[str] = frozenset()  # ⊆ TEL_KINDS; `sms` obejmuje MMS (silnik telefonii: `sms` + `mms`)

    def to_json(self) -> dict[str, Any]:
        return {"groups": sorted(self.groups), "apks_on": sorted(self.apks_on), "verify_hash": self.verify_hash,
                "tel": sorted(self.tel)}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> UploadChoice:
        """Stan sprzed Etapu 3 nie ma klucza `tel` (wgrywanie samych plików)."""
        return cls(frozenset(data["groups"]), frozenset(data["apks_on"]), bool(data.get("verify_hash", False)),
                   frozenset(data.get("tel") or ()))


TEL_KINDS = frozenset({"contacts", "sms", "calls"})  # wybór telefonii na ekranie wgrywania


@dataclass(frozen=True)
class RestoreProgress:
    stage: Literal["plan", "files", "scan"]
    done_files: int
    total_files: int
    done_bytes: int
    total_bytes: int
    current: str  # ścieżka — tylko do UI, nigdy do telemetrii


@dataclass(frozen=True)
class RestoreResult:
    status: Status
    target_serial: str
    files_done: int
    files_exists: int
    files_renamed: int  # wgrane obok jako „(z kopii)”
    files_denied: int
    files_failed: int
    files_unselected: int
    apk_skipped: int  # ocenione jako szkodliwe — nigdy nie wgrywane
    apk_suspicious_skipped: int
    bytes: int
    seconds: int
    hashed: bool  # sprawdzono sumy SHA-256 (a nie tylko rozmiar)
    # skończone: Android 10+ `done`/`failed`, starszy `restart`; przerwane: `skipped` (skanuje wznowienie)
    media_scan: MediaScan
    files_missing: int = 0  # pliki wybranych grup, których nie ma na PC (`plan.missing_in`)


class RestoreError(Exception):
    """Wgrywanie zatrzymane; stan zostaje do wznowienia."""

    def __init__(self, key: ErrorKey) -> None:
        super().__init__(key)
        self.key = key


class _Stop(Exception):
    """Przerwanie na żądanie (wewnętrzne — `run_restore` zwraca wtedy `stopped`)."""


@dataclass
class _Chunk:
    rows: list[RestoreRow]
    locals_: list[Path]
    remote: str  # katalog z `/` na końcu albo pełna ścieżka jednego pliku
    checked: bool = False  # cele sprawdzone tuż przed `push` (`_recheck`)

    @property
    def bytes(self) -> int:
        return sum(r.size for r in self.rows)


def run_restore(adb: AdbTransport, pusher: Pusher, device: DeviceInfo, copy: CopyDir, plan: RestorePlan,
                choice: UploadChoice, *, on_progress: Callable[[RestoreProgress], None],
                should_stop: Callable[[], bool], wait_device: Callable[[], None],
                streams: int = STREAMS) -> RestoreResult:
    """Wgrywa wybrane pliki planu na telefon `device`, wznawiając stan tej kopii dla tego telefonu.

    `adb` — `guard.AppendOnlyAdb`; `plan` zbudowany ze `taken_alts` z `RestoreState.taken_alts()`.
    `RestoreError` i `stopped` zostawiają stan do wznowienia; koniec to `complete` albo `incomplete`.
    """
    return _Restore(adb, pusher, device, copy, plan, choice, on_progress, should_stop, wait_device,
                    max(1, streams)).run()


class _Restore:
    def __init__(self, adb: AdbTransport, pusher: Pusher, device: DeviceInfo, copy: CopyDir, plan: RestorePlan,
                 choice: UploadChoice, on_progress: Callable[[RestoreProgress], None],
                 should_stop: Callable[[], bool], wait_device: Callable[[], None], streams: int) -> None:
        self.adb, self.pusher, self.device, self.copy, self.plan, self.choice = adb, pusher, device, copy, plan, choice
        self.on_progress, self.should_stop, self.wait_device = on_progress, should_stop, wait_device
        self.streams = streams
        self.files = {f.remote: f for f in plan.files}
        self.disconnects = 0
        self.hash_ok = True
        self.expected: dict[str, str] | None = None
        self.total_files = self.total_bytes = self.done_files = self.done_bytes = 0

    # ---- przebieg -----------------------------------------------------------------------
    def run(self) -> RestoreResult:
        if not self.copy.files_dir.is_dir():
            raise RestoreError("copy_missing")
        t0 = time.monotonic()
        state = RestoreState(restore_state_path(self.copy, self.device.serial))
        try:
            if state.get_meta("serial", self.device.serial) != self.device.serial:
                raise RestoreError("wrong_device")
            state.set_meta("serial", self.device.serial)
            state.set_meta("choice", self.choice.to_json())
            _mark(state, "running")
            try:
                self._reconcile(state)
                self._mkdirs(state)
                self._transfer(state)
            except _Stop:
                result = self._result(state, "stopped", "skipped", t0)  # bez skanu: stop ma być szybki
                _mark(state, "stopped")
                return result
            except RestoreError as exc:
                _mark(state, exc.key)
                raise
            except BaseException:
                _mark(state, "incomplete")
                raise
            cnt = Counter(r.status for r in state.all_files().values())
            bad = cnt["pending"] + cnt["pushing"] + cnt["error"] + cnt["denied"]
            result = self._result(state, "incomplete" if bad else "complete", self._scan(cnt["done"] > 0), t0)
            _mark(state, result.status)
            return result
        finally:
            state.close()

    def _progress(self, stage: Literal["files", "scan"], current: str = "") -> None:
        self.on_progress(RestoreProgress(stage, self.done_files, self.total_files, self.done_bytes,
                                         self.total_bytes, current))

    def _online(self) -> bool:
        try:
            return self.adb.run(["get-state"]).strip() == "device"
        except AdbError:
            return False

    def _disconnected(self) -> None:
        """Rozłączenie nie zużywa prób pliku — czekamy na telefon; limit chroni przed złym kablem."""
        self.disconnects += 1
        if self.disconnects > MAX_DISCONNECTS:
            raise RestoreError("too_many_disconnects")
        self.wait_device()

    # ---- stan z planu ----------------------------------------------------------------------
    def _initial(self, f: PlanFile) -> tuple[str, str | None]:
        if f.group not in self.choice.groups:
            return "skipped", "unselected"
        if f.apk is not None and f.apk.outcome == "malicious":
            return "skipped", "apk_malicious"
        if f.apk is not None and not f.apk.default_on and f.remote not in self.choice.apks_on:
            return "skipped", "apk_suspicious"
        if f.action == "exists":
            return "exists", None
        return "pending", None

    def _reconcile(self, state: RestoreState) -> None:
        """Plan + wybór do stanu. `done`/`exists` zostają; reszta od nowa z planu (bez prób), a ślad
        własnego niedokończonego pliku (`interrupted`, a przy `skipped` — `own`) zostaje, gdy cel się
        nie zmienił. Nasz plik,
        który plan widzi jako „już jest” (wgrany przed przerwaniem), liczy się jako wgrany (`done`).
        Wiersze spoza planu (plik zniknął z PC) → `skipped`/`missing`."""
        existing = state.all_files()
        for f in self.plan.files:
            row = existing.get(f.remote)
            if row is not None and row.status in ("done", "exists"):
                continue
            status, error = self._initial(f)
            own = row is not None and row.target == f.target and is_own(row)
            if own and status == "pending":
                error = "interrupted"
            elif own and status == "exists":
                status = "done"
            state.insert(RestoreRow(f.remote, f.target, f.group, f.size, f.mtime, status, 0, error,
                                    own=own and status == "skipped"))
        for remote, row in existing.items():
            if remote not in self.files and row.status not in ("done", "exists", "skipped"):
                state.update(remote, status="skipped", error="missing", own=int(is_own(row)))
        state.commit()
        rows = [r for r in state.all_files().values() if r.status in ("pending", "done")]
        self.total_files, self.total_bytes = len(rows), sum(r.size for r in rows)
        done = [r for r in rows if r.status == "done"]
        self.done_files, self.done_bytes = len(done), sum(r.size for r in done)

    def _mkdirs(self, state: RestoreState) -> None:
        """Katalogi docelowe paczkami. Katalog, którego Android nie pozwala utworzyć (`Permission
        denied`, `Read-only file system` przy nim lub przy folderze nad nim) → jego pliki od razu
        `denied`, bez prób `push`. Inny błąd nie jest tu rozstrzygany — zdecyduje wynik `push`."""
        pending = state.by_status("pending")
        # `/sdcard` (luźne pliki w głównym folderze) zawsze jest — i nie jest celem pod `/sdcard/`
        dirs = sorted({posixpath.dirname(safe_target(r.target)) for r in pending} - {"/sdcard"})
        refused: set[str] = set()
        for batch in _cmd_batches(dirs):
            while True:
                if self.should_stop():
                    raise _Stop()
                try:
                    self.adb.shell("mkdir -p " + " ".join(q(d) for d in batch), timeout=120)
                    break
                except AdbError as exc:
                    if exc.kind not in _CONNECTION_KINDS and self._online():
                        refused |= _refused_paths(exc.message)
                        break
                    self._disconnected()
        if not refused:
            return
        for r in pending:
            d = posixpath.dirname(r.target)
            if any(d == p or d.startswith(p + "/") for p in refused):
                state.update(r.remote, status="denied", error="denied")
        state.commit()

    # ---- pliki ----------------------------------------------------------------------------
    def _transfer(self, state: RestoreState) -> None:
        self._progress("files")
        while pend := state.by_status("pending"):
            small, big = _chunks(pend, self.files)
            self._round(state, small, self.streams)
            self._round(state, big, 1)

    def _round(self, state: RestoreState, chunks: list[_Chunk], streams: int) -> None:
        """Paczki w `streams` równoległych `push`. Zatrzymanie, brak miejsca albo rozłączenie
        wstrzymuje kolejne paczki; trwające się kończą i dopiero wtedy reagujemy."""
        queue = deque(chunks)
        inflight: dict[Future[PullResult], _Chunk] = {}
        halt: set[str] = set()
        pool = ThreadPoolExecutor(streams) if streams > 1 else None
        try:
            while queue or inflight:
                while not halt and queue and len(inflight) < streams:
                    reason = self._blocked(queue[0], sum(c.bytes for c in inflight.values()))
                    if reason:
                        halt.add(reason)
                        break
                    chunk = queue.popleft()
                    if not chunk.checked:
                        pieces = self._recheck(state, chunk)
                        if pieces is None:
                            queue.appendleft(chunk)
                            halt.add("disconnect")
                            break
                        # reszta paczki (≤ sprawdzonych bajtów) idzie od razu; pliki przeniesione
                        # pod nazwę zastępczą — osobno, na początek kolejki
                        queue.extendleft(reversed(pieces[1:]))
                        chunk = pieces[0]
                        if not chunk.rows:
                            continue
                    for r in chunk.rows:
                        state.update(r.remote, status="pushing")
                    state.commit()
                    inflight[self._start(pool, chunk)] = chunk
                if not inflight:
                    break
                done, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for fut in done:
                    outcome = self._settle(state, inflight.pop(fut), fut.result())
                    if outcome:
                        halt.add(outcome)
        finally:
            if pool is not None:
                pool.shutdown(wait=True)
        if "stop" in halt:
            raise _Stop()
        if "full" in halt:
            raise RestoreError("phone_full")
        if "disconnect" in halt:
            self._disconnected()

    def _blocked(self, chunk: _Chunk, inflight_bytes: int) -> str | None:
        """Czy wstrzymać paczkę: zatrzymanie, rozłączenie albo za mało miejsca (wolne minus paczki
        w locie i ta paczka nie może zejść poniżej zapasu)."""
        if self.should_stop():
            return "stop"
        try:
            space = read_space(self.adb)
        except AdbError as exc:
            if exc.kind in _CONNECTION_KINDS or not self._online():
                return "disconnect"
            raise
        if space.free - inflight_bytes - chunk.bytes < self.plan.reserve:
            return "full"
        return None

    def _recheck(self, state: RestoreState, chunk: _Chunk) -> list[_Chunk] | None:
        """Plan mógł się zestarzeć (np. WhatsApp odtwarza kopię pod tę samą ścieżkę): jeden `stat`
        celów paczki tuż przed `push` (poza własnymi plikami — te wolno nadpisać). Cudzy plik
        identyczny → `exists`, bez wgrywania; inny → następna wolna nazwa zastępcza (jak w planie),
        zapisana w stanie, plik idzie sam. `denied` bez zmian — rozstrzygnie `push`.
        Zwraca [reszta paczki, *pliki pod nową nazwą] albo None przy rozłączeniu (wątek główny)."""
        foreign = [r for r in chunk.rows if not is_own(r)]
        if not foreign:
            return [replace(chunk, checked=True)]
        try:
            answers = stat_all(self.adb, [r.target for r in foreign], lambda: False)
        except AdbError as exc:
            if exc.kind in _CONNECTION_KINDS or not self._online():
                return None
            raise
        exists = [r for r in foreign if same_file(answers[r.target], r)]
        conflicts = [r for r in foreign if r not in exists and isinstance(answers[r.target], tuple)]
        decided: dict[str, tuple[Action, str]] = {}
        if conflicts:
            used = {r.target.casefold() for r in state.all_files().values()}
            try:
                decided = resolve_conflicts(self.adb, conflicts, used, lambda: False)
            except AdbError as exc:
                if exc.kind in _CONNECTION_KINDS or not self._online():
                    return None
                raise
        decided.update({r.remote: ("exists", r.target) for r in exists})
        if not decided:
            return [replace(chunk, checked=True)]
        local = dict(zip((r.remote for r in chunk.rows), chunk.locals_, strict=True))
        moved: list[_Chunk] = []
        for r in chunk.rows:
            if r.remote not in decided:
                continue
            action, target = decided[r.remote]
            if action == "exists":
                state.update(r.remote, status="exists", error=None, target=target)
                self.total_files -= 1
                self.total_bytes -= r.size
            else:
                state.update(r.remote, target=target)
                moved.append(_Chunk([replace(r, target=target)], [local[r.remote]], target, True))
        state.commit()
        keep = [r for r in chunk.rows if r.remote not in decided]
        rest = _Chunk(keep, [local[r.remote] for r in keep], chunk.remote, True)
        return [rest, *moved]

    def _start(self, pool: ThreadPoolExecutor | None, chunk: _Chunk) -> Future[PullResult]:
        """Jeden strumień — w wątku głównym (z postępem w trakcie); kilka — w puli, bez postępu
        z wątków (raportuje go wątek główny po każdej paczce)."""
        if pool is not None:
            return pool.submit(self._push, chunk, lambda: None)
        fut: Future[PullResult] = Future()
        current = chunk.rows[0].target
        try:
            fut.set_result(self._push(chunk, lambda: self._progress("files", current)))
        except Exception as exc:  # noqa: BLE001 — jak w puli: błąd wraca przez `fut.result()`
            fut.set_exception(exc)
        return fut

    def _push(self, chunk: _Chunk, tick: Callable[[], None]) -> PullResult:
        try:
            return self.pusher.push(chunk.locals_, chunk.remote, self.should_stop, tick)
        except AdbError as exc:  # np. adb zniknął razem z telefonem — rozstrzyga `get-state`
            return PullResult(1, [f"adb: error: {exc.kind}"], False)

    def _settle(self, state: RestoreState, chunk: _Chunk, res: PullResult) -> str | None:
        """Wynik paczki do stanu (wątek główny). Zwraca `stop`/`disconnect` albo None."""
        targets = [r.target for r in chunk.rows]
        if res.stopped:
            self._salvage(state, chunk)
            return "stop"
        answers = None
        if res.rc == 0 or self._online():
            try:
                answers = stat_all(self.adb, targets, lambda: False)
            except AdbError:
                answers = None
        if answers is None and not self._online():
            for r in chunk.rows:  # bez liczenia próby; pod celem może być nasz niedokończony plik
                state.update(r.remote, status="pending", error="disconnect")
            state.commit()
            return "disconnect"
        answers = answers or {}
        ok = [r for r in chunk.rows if isinstance(a := answers.get(r.target), tuple) and a[0] == r.size]
        bad = [(r, "push_failed") for r in chunk.rows if r not in ok]
        if ok and self.choice.verify_hash and self.hash_ok:
            checked = self._verify(chunk, ok)
            if checked is None:
                for r in chunk.rows:
                    state.update(r.remote, status="pending", error="disconnect")
                state.commit()
                return "disconnect"
            ok, mismatched = checked
            bad += [(r, "hash_mismatch") for r in mismatched]
        for r in ok:
            state.update(r.remote, status="done", error=None)
            self.done_files += 1
            self.done_bytes += r.size
        # paczka = jeden katalog docelowy, więc odmowa w wyniku `push` dotyczy wszystkich jej plików
        refused = any(_has(line, _DENIED) for line in res.lines)
        for r, reason in bad:
            if refused or answers.get(r.target) == "denied":
                state.update(r.remote, status="denied", error="denied")
                continue
            attempts = r.attempts + 1
            state.update(r.remote, attempts=attempts, error=reason,
                         status="error" if attempts >= MAX_ATTEMPTS else "pending")
        state.commit()
        self._progress("files", chunk.rows[-1].target)
        return None

    def _salvage(self, state: RestoreState, chunk: _Chunk) -> None:
        """Po przerwaniu: plik kompletny (rozmiar i data, którą `push` ustawia na końcu) jest gotowy;
        reszta zostaje `pushing` — wznowienie nadpisze własny plik. Z SHA-256 nic nie zaliczamy bez sumy."""
        if self.choice.verify_hash:
            return
        try:
            answers = stat_all(self.adb, [r.target for r in chunk.rows], lambda: False)
        except AdbError:
            return
        for r in chunk.rows:
            a = answers.get(r.target)
            if isinstance(a, tuple) and a[0] == r.size and abs(a[1] - r.mtime) <= MTIME_TOLERANCE:
                state.update(r.remote, status="done", error=None)
                self.done_files += 1
                self.done_bytes += r.size
        state.commit()

    def _verify(self, chunk: _Chunk, ok: list[RestoreRow]) -> tuple[list[RestoreRow], list[RestoreRow]] | None:
        """(zgodne, niezgodne) wg `sha256sum` na telefonie i sumy z `manifest.csv` (albo z pliku na PC).
        Brak narzędzia → dalej tylko rozmiar (`hash_ok = False`); rozłączenie → None."""
        remote: dict[str, str] = {}
        for batch in _cmd_batches([r.target for r in ok]):
            try:
                out = self.adb.shell("sha256sum " + " ".join(q(t) for t in batch), timeout=HASH_TIMEOUT)
            except AdbError as exc:
                if exc.kind in _CONNECTION_KINDS or not self._online():
                    return None
                if exc.kind == "command_failed" and _has(exc.message, _NO_TOOL):
                    self.hash_ok = False
                    return ok, []
                continue  # pliki tej paczki bez sumy → niezgodne, ponowienie
            for line in out.split("\n"):
                line = line.removesuffix("\r")
                if len(line) > 66 and line[64:66] == "  ":
                    remote[line[66:]] = line[:64].lower()
        local = dict(zip((r.remote for r in chunk.rows), chunk.locals_, strict=True))
        good = [r for r in ok if remote.get(r.target) == self._expected_sha(r.remote, local[r.remote])]
        return good, [r for r in ok if r not in good]

    def _expected_sha(self, remote: str, local: Path) -> str:
        if self.expected is None:
            self.expected = _manifest_sums(self.copy.path / MANIFEST)
        if remote not in self.expected:
            with local.open("rb") as fh:
                self.expected[remote] = hashlib.file_digest(fh, "sha256").hexdigest()
        return self.expected[remote]

    # ---- koniec ---------------------------------------------------------------------------
    def _scan(self, pushed: bool) -> MediaScan:
        """Skan galerii tylko, gdy w stanie jest plik wgrany (`done`) — kopia samej telefonii go nie robi."""
        if not pushed:
            return "skipped"
        if self.device.sdk < 29:
            return "restart"
        self._progress("scan")
        try:
            self.adb.shell(SCAN_VOLUME_CMD, timeout=SCAN_TIMEOUT)
        except AdbError:
            return "failed"
        return "done"

    def _result(self, state: RestoreState, status: Status, media_scan: MediaScan,
                t0: float) -> RestoreResult:
        rows = list(state.all_files().values())
        cnt = Counter(r.status for r in rows)
        skipped = Counter(r.error for r in rows if r.status == "skipped")
        done = [r for r in rows if r.status == "done"]
        return RestoreResult(
            status=status, target_serial=self.device.serial, files_done=len(done),
            files_exists=cnt["exists"], files_renamed=sum(1 for r in done if r.target != r.remote),
            files_denied=cnt["denied"], files_failed=cnt["error"], files_unselected=skipped["unselected"],
            apk_skipped=skipped["apk_malicious"], apk_suspicious_skipped=skipped["apk_suspicious"],
            bytes=sum(r.size for r in done), seconds=round(time.monotonic() - t0),
            hashed=self.choice.verify_hash and self.hash_ok, media_scan=media_scan,
            files_missing=self.plan.missing_in(self.choice.groups))


def _mark(state: RestoreState, status: str) -> None:
    """Meta `status` i `updated` (ISO-8601 UTC) — dla widoku kopii i Bannera wznowienia."""
    state.set_meta("status", status)
    state.set_meta("updated", datetime.now(UTC).isoformat(timespec="seconds"))


def _tel_to_write(tel_plan: TelPlan, kinds: frozenset[str]) -> int:
    wanted = kinds | ({"mms"} if "sms" in kinds else set())
    count = {"contacts": len(tel_plan.contacts.write) if tel_plan.contacts is not None else 0,
             "sms": len(tel_plan.sms), "mms": len(tel_plan.mms), "calls": len(tel_plan.calls)}
    return sum(n for k, n in count.items() if k in wanted)


def settle_finished(copy: CopyDir, serial: str, plan: RestorePlan, tel_plan: TelPlan) -> bool:
    """Wznowienie, w którym według świeżego planu nie ma już nic do zrobienia (program zamknięty w trakcie
    zapisu, a telefon ma wszystko), zamyka stan jako zakończony — inaczej Banner wznowienia zostaje na zawsze,
    bo start jest wyłączony. Wiersze plików w toku kończą jako `done` (są na telefonie); rekordy telefonii,
    które telefon ma, nie mają wpisu w kolejce, więc wystarczy wyzerować `tel_left`. Zwraca, czy stan zamknięto."""
    mine = next((r for r in read_restores(copy) if r.serial == serial), None)
    if mine is None or not mine.resumable:
        return False
    state = RestoreState(restore_state_path(copy, serial))
    try:
        saved = state.get_meta("choice")
        try:
            choice = UploadChoice.from_json(saved) if isinstance(saved, dict) else None
        except (KeyError, TypeError):
            choice = None
        groups = {f.group for f in plan.files} if choice is None else choice.groups
        apks_on = set() if choice is None else set(choice.apks_on)
        kinds = TEL_KINDS if choice is None else choice.tel
        if _tel_to_write(tel_plan, kinds) or any(
                f.group in groups and f.action != "exists" and _apk_selected(f.apk, apks_on) for f in plan.files):
            return False
        planned = {f.remote for f in plan.files}
        present = {f.remote for f in plan.files if f.action == "exists"}
        for row in [*state.by_status("pending"), *state.by_status("pushing")]:
            if row.remote in present:
                state.update(row.remote, status="done", error=None)
            else:
                state.update(row.remote, status="skipped", error="unselected" if row.remote in planned else "missing")
        state.commit()
        state.set_meta("tel_left", 0)
        rows = state.all_files().values()
        _mark(state, "incomplete" if any(r.status in ("denied", "error") for r in rows) else "complete")
        return True
    finally:
        state.close()


def _has(text: str, needles: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(n in low for n in needles)


def _refused_paths(message: str) -> set[str]:
    """Ścieżki z linii błędu `mkdir`, w których Android odmówił zapisu (`mkdir: '/sdcard/…': Permission denied`)."""
    return {m.rstrip("/") for line in message.splitlines() if _has(line, _DENIED)
            for m in _SDCARD_PATH.findall(line)}


def _manifest_sums(path: Path) -> dict[str, str]:
    """`remote` → SHA-256 z `manifest.csv` kopii (puste, gdy kopia bez sum albo plik nieczytelny)."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return {row["remote"]: row["sha256"].lower() for row in csv.DictReader(fh, delimiter=";")
                    if row.get("sha256")}
    except (OSError, KeyError, csv.Error):
        return {}


def _chunks(pend: list[RestoreRow], files: dict[str, PlanFile]) -> tuple[list[_Chunk], list[_Chunk]]:
    """(małe, duże): paczki z jednego katalogu docelowego — małe ≤ 200 plików / ≤ 256 MiB, duże
    ≤ 1 GiB. Plik zapisywany pod inną nazwą (obok jako „(z kopii)” albo inna nazwa na PC) albo
    ponawiany idzie sam, z pełną ścieżką docelową."""
    out: dict[bool, list[_Chunk]] = {True: [], False: []}
    cur: dict[bool, list[tuple[RestoreRow, Path]]] = {True: [], False: []}
    sizes = {True: 0, False: 0}
    chars = {True: 0, False: 0}

    def flush(small: bool) -> None:
        if cur[small]:
            rows = [r for r, _ in cur[small]]
            out[small].append(_Chunk(rows, [p for _, p in cur[small]], posixpath.dirname(rows[0].target) + "/"))
        cur[small], sizes[small], chars[small] = [], 0, 0

    for r in pend:
        local = files[r.remote].local
        small = r.size < SMALL_MAX
        if r.attempts > 0 or local.name != posixpath.basename(r.target):
            out[small].append(_Chunk([r], [local], r.target))
            continue
        limit = SMALL_CHUNK_BYTES if small else BIG_CHUNK_BYTES
        c = len(str(local)) + 3
        prev = cur[small]
        if prev and (posixpath.dirname(prev[0][0].target) != posixpath.dirname(r.target)
                     or len(prev) >= CHUNK_MAX_FILES or sizes[small] + r.size > limit
                     or chars[small] + c > CMD_MAX_CHARS):
            flush(small)
        cur[small].append((r, local))
        sizes[small] += r.size
        chars[small] += c
    flush(True)
    flush(False)
    return out[True], out[False]
