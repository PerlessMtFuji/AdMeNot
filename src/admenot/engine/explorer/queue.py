"""Kolejka zadań eksploratora: kopiowanie telefon → komputer i wgrywanie komputer → telefon (spec §5.5).

Zadania idą po kolei; w zadaniu małe pliki do `STREAMS` równoległych strumieni, duże (≥ `BIG_FILE`) pojedynczo.
Nic nie jest nadpisywane: na komputerze plik powstaje jako `<cel>.admenot-part` i dostaje docelową nazwę
dopiero po sprawdzeniu rozmiaru; na telefonie — `<folder>/.admenot-<12 hex>.part`, potem `mv -n` i `stat`,
że cel jest i pliku tymczasowego już nie ma (`mv -n` na istniejący plik kończy się kodem 0 i zostawia
oba — wtedy nazwa obok). Foldery z naszymi plikami tymczasowymi na telefonie są zapisywane na dysku
(`explorer_tmp/<telefon>.json`) przed każdym `push`, żeby po zabitym programie sprzątnąć je przy
następnym otwarciu (`sweep_recorded`). Odłączenie → `waiting` i ponowienie co `RETRY_INTERVAL` s od
pierwszego niedokończonego pliku, tylko dla tego samego telefonu. Zdarzenia `explorer:task` nie
częściej niż co `EVENT_INTERVAL` s (zmiana statusu — zawsze). Bez nazw plików w logach.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import ntpath
import os
import posixpath
import secrets
import threading
import time
from collections.abc import Callable, Collection, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Literal

from admenot.engine import paths
from admenot.engine.adb.transport import AdbError
from admenot.engine.explorer.guard import (
    TMP_PREFIX,
    TMP_SUFFIX,
    ExplorerAdb,
    explorer_pusher,
    is_tmp_name,
)
from admenot.engine.explorer.listing import ListError, list_dir
from admenot.engine.explorer.plan import Item, TaskPlan, side_name
from admenot.engine.transfer.backup import _cmd_batches
from admenot.engine.transfer.guard import SCAN_VOLUME_CMD, STAT_TAIL, q
from admenot.engine.transfer.puller import Puller, PullResult
from admenot.engine.transfer.pusher import Pusher
from admenot.engine.transfer.restore import _refused_paths

__all__ = [
    "BIG_FILE",
    "EVENT_INTERVAL",
    "HASH_BASE_TIMEOUT",
    "HASH_MIN_SPEED",
    "RETRY_INTERVAL",
    "STREAMS",
    "TaskState",
    "TransferQueue",
    "forget_tmp_folder",
    "hash_timeout",
    "read_tmp_folders",
    "record_tmp_folder",
    "sweep_recorded",
    "sweep_tmp",
]

_LOG = logging.getLogger(__name__)

STREAMS = 4  # równoległe strumienie małych plików
BIG_FILE = 64 * 1024 * 1024  # od tylu bajtów plik idzie sam
EVENT_INTERVAL = 0.5  # s; najczęstsze zdarzenie postępu
RETRY_INTERVAL = 2.0  # s; sprawdzanie, czy telefon wrócił
HASH_BASE_TIMEOUT = 60.0  # s; `sha256sum` na telefonie: stała część limitu czasu
HASH_MIN_SPEED = 20 * 1024 * 1024  # B/s; ostrożna prędkość `sha256sum` (wolna karta, pamięć eMMC)
SCAN_FILE_MAX = 32  # powyżej tylu wgranych mediów jeden `scan_volume` zamiast `scan_file` na plik
PC_PART = ".admenot-part"  # przyrostek pliku w trakcie pobierania na komputer
_COMMIT_TRIES = 50  # kolejne nazwy obok, gdy cel ciągle się pojawia
_CONNECTION_KINDS = frozenset({"offline", "no_device", "unauthorized", "adb_missing"})
_DENIED = ("permission denied", "read-only file system")
_STORAGE = "/storage/emulated/0"

Status = Literal["queued", "running", "paused", "waiting", "done", "cancelled", "failed"]
_Stop = Literal["cancel", "pause", "disconnect"]
_PRIORITY = {"disconnect": 1, "pause": 2, "cancel": 3}
_ACTIVE = frozenset({"queued", "running", "paused", "waiting"})


@dataclass
class TaskState:
    id: str
    kind: Literal["to_pc", "to_phone"]
    status: Status
    done_files: int
    total_files: int
    done_bytes: int
    total_bytes: int
    speed: float  # B/s od ostatniego startu (wznowienia)
    eta_s: int | None
    skipped: int  # identyczne pliki pominięte (+ elementy pominięte przez plan)
    renamed: int  # zapisane obok pod inną nazwą
    failed: list[tuple[str, str]]  # (plik źródłowy, powód: denied | size | mismatch | missing | error)
    verified: Literal["size", "hash", "mismatch"] | None
    dest: str  # folder docelowy (na PC albo na telefonie)


# ---------------------------------------------------------------------------------------------
# lista folderów z plikami tymczasowymi (na dysku komputera)

_LIST_LOCK = threading.Lock()


def _tmp_list_path(serial: str, directory: Path | None) -> Path:
    base = directory if directory is not None else paths.data_dir() / "explorer_tmp"
    return base / f"{paths.device_dir_name(serial)}.json"


def read_tmp_folders(serial: str, *, directory: Path | None = None) -> list[str]:
    """Foldery telefonu, w których mógł zostać nasz plik tymczasowy (posortowane)."""
    with _LIST_LOCK:
        return sorted(_read(_tmp_list_path(serial, directory)))


def record_tmp_folder(serial: str, folder: str, *, directory: Path | None = None) -> None:
    with _LIST_LOCK:
        path = _tmp_list_path(serial, directory)
        folders = _read(path)
        if folder not in folders:
            _write(path, folders | {folder})


def forget_tmp_folder(serial: str, folder: str, *, directory: Path | None = None) -> None:
    with _LIST_LOCK:
        path = _tmp_list_path(serial, directory)
        folders = _read(path)
        if folder in folders:
            _write(path, folders - {folder})


def _read(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    folders = data.get("folders") if isinstance(data, dict) else None
    return {f for f in folders if isinstance(f, str)} if isinstance(folders, list) else set()


def _write(path: Path, folders: set[str]) -> None:
    try:
        if not folders:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"folders": sorted(folders)}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        _LOG.warning("explorer tmp list not saved")


def sweep_tmp(adb: ExplorerAdb, folders: Iterable[str]) -> int:
    """Usuwa (`rm -f`, po jednym) nasze pliki tymczasowe `.admenot-<12 hex>.part` z podanych folderów.
    Folder, którego nie ma albo którego nie da się przeczytać, jest pomijany; odłączenie — `AdbError`."""
    removed = 0
    for folder in folders:
        try:
            entries = list_dir(adb, folder, include_hidden=True).entries
        except ListError as exc:
            if exc.kind == "offline":
                raise AdbError("offline", "device offline") from exc
            continue
        for e in entries:
            if e.kind != "file" or not is_tmp_name(e.name):
                continue
            try:
                adb.shell(f"rm -f {q(e.path)}")
            except AdbError as exc:
                if exc.kind in _CONNECTION_KINDS:
                    raise
                continue
            removed += 1
    return removed


def sweep_recorded(adb: ExplorerAdb, serial: str, *, directory: Path | None = None,
                   skip: Collection[str] = ()) -> int:
    """Sprząta foldery z listy na dysku (przy otwarciu eksploratora) i usuwa je z listy.
    `skip` — foldery, których pliki tymczasowe pilnuje jeszcze żywa kolejka tego telefonu."""
    removed = 0
    for folder in read_tmp_folders(serial, directory=directory):
        if folder in skip:
            continue
        removed += sweep_tmp(adb, [folder])
        forget_tmp_folder(serial, folder, directory=directory)
    return removed


# ---------------------------------------------------------------------------------------------
# kolejka


class _Disconnect(Exception):
    """Telefon zniknął — plik wraca do kolejki, zadanie czeka."""


class _Failed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class _Task:
    plan: TaskPlan
    verify_hash: bool
    state: TaskState
    status: list[str]  # stan pliku: pending | done | skipped | failed
    names: dict[str, set[str]]  # folder docelowy -> nazwy zajęte w planie i nadane w trakcie
    stop: _Stop | None = None
    prepared: bool = False
    inflight: dict[int, str] = field(default_factory=dict)  # (do PC) plik -> lokalny `.admenot-part`
    committing: dict[int, tuple[str, str, int]] = field(default_factory=dict)  # tmp, cel, rozmiar
    tmps: set[str] = field(default_factory=set)  # nasze pliki tymczasowe na telefonie do sprzątnięcia
    media: list[str] = field(default_factory=list)  # wgrane media do skanu
    failed_bytes: int = 0
    mismatch: bool = False
    last_emit: float | None = None
    run_t0: float = 0.0
    run_b0: int = 0


def hash_timeout(size: int) -> float:
    """Limit czasu `sha256sum` pliku o rozmiarze `size` (wielogigabajtowy film liczy się minutami)."""
    return HASH_BASE_TIMEOUT + max(size, 0) / HASH_MIN_SPEED


def _hash_local(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _is_media(name: str) -> bool:
    mime = mimetypes.guess_type(name)[0] or ""
    return mime.split("/", 1)[0] in ("image", "video", "audio")


def _dest(plan: TaskPlan) -> str:
    """Folder docelowy zadania: wspólny przodek folderów nadrzędnych celów i nowych folderów."""
    mod = posixpath if plan.kind == "to_phone" else ntpath if os.name == "nt" else posixpath
    parents = [mod.dirname(p) for p in [*(i.dst for i in plan.items), *plan.dirs]]
    if not parents:
        return ""
    try:
        return mod.commonpath(parents)
    except ValueError:
        return parents[0]


class TransferQueue:
    def __init__(self, adb_factory: Callable[[], ExplorerAdb], puller: Puller, pusher: Pusher,
                 emit: Callable[[str, dict], None], is_connected: Callable[[], bool], *,
                 connected_serials: Callable[[], Collection[str]] | None = None,
                 sdk: Callable[[], int] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 retry_interval: float = RETRY_INTERVAL,
                 tmp_dir: Path | None = None,
                 token: Callable[[], str] = lambda: secrets.token_hex(6),
                 streams: int = STREAMS, big_file: int = BIG_FILE, id_prefix: str = "t") -> None:
        self._adb_factory = adb_factory
        self._puller = puller
        self._pusher = explorer_pusher(pusher)  # tylko do naszego pliku tymczasowego pod /sdcard/
        self._emit_fn = emit
        self._is_connected = is_connected
        self._connected_serials = connected_serials
        self._sdk_fn = sdk
        self._sdk: int | None = None
        self._clock = clock
        self._retry = retry_interval
        self.tmp_dir = tmp_dir
        self._token = token
        self._streams = max(1, streams)
        self._big = big_file
        self._id_prefix = id_prefix  # różne kolejki (sesje) — różne identyfikatory zadań
        self.serial: str = adb_factory().serial or "unknown"
        self._tasks: dict[str, _Task] = {}
        self._lock = threading.RLock()
        # zawsze przed `_lock`: kolejność zdarzeń = kolejność zmian; `emit` woła się bez `_lock` (`_locked`)
        self._emit_lock = threading.RLock()
        self._outbox: list[dict] = []  # zdarzenia zebrane pod `_lock`, wysyłane po jego zwolnieniu
        self._cond = threading.Condition(self._lock)
        self._wake = threading.Event()
        self._closing = False
        self._seq = 0
        self._folders: dict[str, int] = {}  # folder telefonu -> liczba naszych plików tymczasowych
        self._worker: threading.Thread | None = None

    # ---- API -----------------------------------------------------------------------------
    def add(self, plan: TaskPlan, verify_hash: bool = False) -> str:
        status = ["skipped" if i.action == "skip_same" else "pending" for i in plan.items]
        live = [i for i, s in zip(plan.items, status, strict=True) if s == "pending"]
        names: dict[str, set[str]] = {}
        split = posixpath.split if plan.kind == "to_phone" else os.path.split
        for i in plan.items:
            folder, name = split(i.dst)
            names.setdefault(folder, set()).add(name)
        with self._locked():
            if self._closing:
                raise RuntimeError("queue closed")
            self._seq += 1
            tid = f"{self._id_prefix}{self._seq}"
            state = TaskState(tid, plan.kind, "queued", 0, len(live), 0, sum(i.size for i in live), 0.0, None,
                              plan.skipped + len(plan.items) - len(live), 0, [], None, _dest(plan))
            task = self._tasks[tid] = _Task(plan, verify_hash, state, status, names)
            self._emit(task, force=True)
            if self._worker is None:
                self._worker = threading.Thread(target=self._loop, name="explorer-queue", daemon=True)
                self._worker.start()
            self._cond.notify_all()
        return tid

    def pause(self, task_id: str) -> None:
        with self._locked():
            task = self._tasks.get(task_id)
            if task is None:
                return
            if task.state.status == "queued":
                self._set(task, "paused")
            elif task.state.status in ("running", "waiting"):
                self._request(task, "pause")
        self._wake.set()

    def resume(self, task_id: str) -> None:
        with self._locked():
            task = self._tasks.get(task_id)
            if task is not None and task.state.status == "paused":
                task.stop = None
                self._set(task, "queued")
                self._cond.notify_all()

    def cancel(self, task_id: str) -> None:
        with self._locked():
            task = self._tasks.get(task_id)
            if task is None:
                return
            if task.state.status in ("queued", "paused"):
                self._set(task, "cancelled")
                leftovers = bool(task.tmps)
            elif task.state.status in ("running", "waiting"):
                self._request(task, "cancel")
                leftovers = False
            else:
                return
        self._wake.set()
        if leftovers:  # wstrzymane po odłączeniu: plik tymczasowy na telefonie zostaje do `sweep_tmp`
            self._clean_tmps(task)

    def active(self) -> int:
        """Zadania, które zamknięcie kolejki anuluje (w kolejce, w toku, wstrzymane, czekające na telefon)."""
        with self._lock:
            return sum(t.state.status in _ACTIVE for t in self._tasks.values())

    def drop_partials(self) -> None:
        """Usuwa lokalne `<cel>.admenot-part` plików w toku — gdy wątek kolejki nie skończył się na czas
        przy wyjściu z programu (zwykle sprząta je sam po anulowaniu)."""
        with self._lock:
            parts = [part for t in self._tasks.values() for part in t.inflight.values()]
        for part in parts:
            _unlink(part)

    def tracked_folders(self) -> set[str]:
        """Foldery telefonu z naszymi plikami tymczasowymi pilnowanymi teraz przez kolejkę."""
        with self._lock:
            return set(self._folders)

    def tasks(self) -> list[TaskState]:
        with self._lock:
            return [self._snapshot(t) for t in self._tasks.values()]

    def wait_for(self, task_id: str, *statuses: str, timeout: float = 10.0) -> TaskState:
        """Czeka, aż zadanie będzie w jednym z `statuses` (dla testów i mostka)."""
        with self._cond:
            ok = self._cond.wait_for(lambda: self._tasks[task_id].state.status in statuses, timeout)
            if not ok:
                raise TimeoutError(f"{task_id}: {self._tasks[task_id].state.status}")
            return self._snapshot(self._tasks[task_id])

    def shutdown(self, wait: bool = True) -> None:
        """Anuluje wszystko (niedokończone zadania przepadają); `wait` — czeka na wątek kolejki
        (bez czekania: wątek kończy bieżący krok, np. `sha256sum`, i sprząta sam; `join` czeka później)."""
        with self._locked():
            self._closing = True
            for task in self._tasks.values():
                if task.state.status in ("queued", "paused"):
                    self._set(task, "cancelled")
                elif task.state.status in ("running", "waiting"):
                    self._request(task, "cancel")
            self._cond.notify_all()
            worker = self._worker
        self._wake.set()
        if wait and worker is not None:
            worker.join()

    def join(self, timeout: float | None = None) -> bool:
        """Czeka na koniec wątku kolejki (po `shutdown`); True, gdy wątku już nie ma."""
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.join(timeout)
            return not worker.is_alive()
        return True

    # ---- stan i zdarzenia ----------------------------------------------------------------
    def _request(self, task: _Task, reason: _Stop) -> None:
        if task.stop is None or _PRIORITY[reason] > _PRIORITY[task.stop]:
            task.stop = reason

    def _snapshot(self, task: _Task) -> TaskState:
        st = replace(task.state, failed=list(task.state.failed))
        if task.inflight:  # postęp dużego pliku pobieranego na komputer
            extra = 0
            for idx, part in list(task.inflight.items()):
                try:
                    extra += min(os.path.getsize(part), task.plan.items[idx].size)
                except OSError:
                    pass
            st.done_bytes += extra
        if st.status == "running":
            now = self._clock()
            elapsed = now - task.run_t0
            st.speed = (st.done_bytes - task.run_b0) / elapsed if elapsed > 0 else 0.0
            left = st.total_bytes - st.done_bytes - task.failed_bytes
            st.eta_s = int(left / st.speed) if st.speed > 0 else None
        else:
            st.speed, st.eta_s = 0.0, None
        return st

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """`_emit_lock` + `_lock`; zebrane zdarzenia idą do `emit` już bez `_lock` (callback może wołać
        `tasks()`), ale jeszcze pod `_emit_lock` — w kolejności zmian."""
        with self._emit_lock:
            with self._lock:
                yield
            while self._outbox:
                self._emit_fn("explorer:task", self._outbox.pop(0))

    def _emit(self, task: _Task, force: bool = False) -> None:
        """Wołać pod `_locked()`."""
        now = self._clock()
        if not force and task.last_emit is not None and now - task.last_emit < EVENT_INTERVAL:
            return
        task.last_emit = now
        self._outbox.append(asdict(self._snapshot(task)))

    def _set(self, task: _Task, status: Status) -> None:
        """Zmiana statusu (wołać pod `_locked()`)."""
        if task.state.status == status:
            return
        task.state.status = status
        if status == "running":
            task.run_t0, task.run_b0 = self._clock(), task.state.done_bytes
        self._emit(task, force=True)
        self._cond.notify_all()

    def _status(self, task: _Task, status: Status) -> None:
        with self._locked():
            self._set(task, status)

    def _progress(self, task: _Task) -> None:
        with self._locked():
            self._emit(task)

    # ---- wątek kolejki -------------------------------------------------------------------
    def _next(self) -> _Task | None:
        return next((t for t in self._tasks.values() if t.state.status == "queued"), None)

    def _loop(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._closing or self._next() is not None)
            with self._locked():
                if self._closing:
                    return
                task = self._next()
                if task is None:
                    continue
                task.stop = None
                self._set(task, "running")
            self._run(task)

    def _run(self, task: _Task) -> None:
        try:
            while True:
                outcome = self._pass(task)
                if outcome == "disconnect" and self._wait_online(task):
                    continue
                break
            stop = task.stop if outcome != "done" else None
            if stop == "pause":
                self._status(task, "paused")
            elif stop is not None:  # anulowanie (też przy zamykaniu) albo odłączenie zakończone anulowaniem
                self._clean_tmps(task)
                self._status(task, "cancelled")
            else:
                self._finish(task)
        except Exception as exc:  # noqa: BLE001 — błąd zadania nie może zabić kolejki
            _LOG.error("explorer task failed: %s", type(exc).__name__)
            for part in list(task.inflight.values()):
                _unlink(part)
            self._clean_tmps(task)
            self._status(task, "failed")

    def _finish(self, task: _Task) -> None:
        if task.plan.kind == "to_phone" and task.media:
            self._scan(task.media)
        with self._locked():
            task.state.verified = ("mismatch" if task.mismatch else "hash") if task.verify_hash else "size"
            self._set(task, "done")

    def _pass(self, task: _Task) -> str:
        """Jedno przejście po niedokończonych plikach; wynik: done | pause | cancel | disconnect."""
        try:
            self._clean_tmps(task, strict=True)
            if not task.prepared:
                self._prepare(task)
                task.prepared = True
        except _Disconnect:
            return "disconnect"
        pending = [i for i, s in enumerate(task.status) if s == "pending"]
        inflight: set[Future[None]] = set()
        with ThreadPoolExecutor(self._streams, thread_name_prefix="explorer-stream") as pool:
            for idx in pending:
                big = task.plan.items[idx].size >= self._big
                while inflight and (big or len(inflight) >= self._streams):
                    _, inflight = wait(inflight, return_when=FIRST_COMPLETED)
                if task.stop is not None:
                    break
                inflight.add(pool.submit(self._one, task, idx))
                if big:
                    wait(inflight)
                    inflight.clear()
            wait(inflight)
        return task.stop or "done"

    def _wait_online(self, task: _Task) -> bool:
        """Czeka na ten sam telefon; False, gdy zadanie wstrzymano albo anulowano w trakcie."""
        self._status(task, "waiting")
        while True:
            with self._lock:
                if task.stop in ("pause", "cancel"):
                    return False
            if self._online():
                with self._locked():
                    if task.stop in ("pause", "cancel"):
                        return False
                    task.stop = None
                    self._set(task, "running")
                return True
            self._wake.wait(self._retry)
            self._wake.clear()

    def _online(self) -> bool:
        try:
            if not self._is_connected():
                return False
            if self._connected_serials is not None and self.serial not in self._connected_serials():
                return False
            return self._adb_factory().run(["get-state"]).strip() == "device"
        except AdbError:
            return False

    def _check(self, exc: AdbError) -> None:
        """Błąd adb: odłączenie → `_Disconnect`; inaczej `_Failed` z powodem."""
        if exc.kind in _CONNECTION_KINDS or not self._online():
            raise _Disconnect from exc
        low = exc.message.lower()
        if any(d in low for d in _DENIED):
            raise _Failed("denied") from exc
        if "no such file" in low:
            raise _Failed("missing") from exc
        raise _Failed("error") from exc

    def _shell(self, command: str, timeout: float = 60.0) -> str:
        try:
            return self._adb_factory().shell(command, timeout=timeout)
        except AdbError as exc:
            self._check(exc)
            raise  # nieosiągalne

    def _should_stop(self, task: _Task) -> Callable[[], bool]:
        return lambda: task.stop is not None

    # ---- jeden plik ----------------------------------------------------------------------
    def _one(self, task: _Task, idx: int) -> None:
        item = task.plan.items[idx]
        try:
            if task.stop is not None:
                return
            if task.plan.kind == "to_pc":
                result = self._to_pc(task, idx, item)
            else:
                result = self._to_phone(task, idx, item)
        except _Disconnect:
            with self._lock:
                self._request(task, "disconnect")
            return
        except _Failed as f:
            result = ("failed", f.reason)
        except Exception as exc:  # noqa: BLE001 — np. błąd dysku; w puli wyjątek by przepadł
            _LOG.warning("explorer file failed: %s", type(exc).__name__)
            result = ("failed", "error")
        self._settle(task, idx, item, result)

    def _settle(self, task: _Task, idx: int, item: Item, result: tuple[str, ...]) -> None:
        kind = result[0]
        with self._locked():
            st = task.state
            if kind == "stopped":
                return
            if kind == "skipped":
                task.status[idx] = "skipped"
                st.skipped += 1
                st.total_files -= 1
                st.total_bytes -= item.size
            elif kind == "failed":
                task.status[idx] = "failed"
                st.failed.append((item.src, result[1]))
                task.failed_bytes += item.size
                if result[1] == "mismatch":
                    task.mismatch = True
            else:  # ("done", renamed)
                task.status[idx] = "done"
                st.done_files += 1
                st.done_bytes += item.size
                if result[1] == "1":
                    st.renamed += 1
            self._emit(task)

    def _taken(self, task: _Task, folder: str, existing: Iterable[str]) -> set[str]:
        with self._lock:
            return set(existing) | task.names.get(folder, set())

    def _claim(self, task: _Task, folder: str, name: str) -> None:
        with self._lock:
            task.names.setdefault(folder, set()).add(name)

    # ---- telefon -> komputer --------------------------------------------------------------
    def _phone_hash(self, path: str, size: int) -> str:
        out = self._shell(f"sha256sum {q(path)}", timeout=hash_timeout(size))
        digest = out.split(maxsplit=1)[0].lower() if out.strip() else ""
        if len(digest) != 64:
            raise _Failed("error")
        return digest

    def _to_pc(self, task: _Task, idx: int, item: Item) -> tuple[str, ...]:
        folder, name = os.path.split(item.dst)
        dst = item.dst
        renamed = item.action == "renamed"
        if item.action == "check_hash":
            if os.path.isfile(dst) and os.path.getsize(dst) == item.size \
                    and _hash_local(dst) == self._phone_hash(item.src, item.size):
                return ("skipped",)
            if os.path.lexists(dst):
                dst = self._pc_side(task, folder, name)
                renamed = True
        part = dst + PC_PART
        with self._lock:
            task.inflight[idx] = part
        try:
            res = self._pull(task, item.src, part)
            if res.stopped:
                return ("stopped",)
            if res.rc != 0:
                if not self._online():
                    raise _Disconnect
                text = "\n".join(res.lines).lower()
                reason = "denied" if any(d in text for d in _DENIED) else \
                    "missing" if "no such file" in text else "error"
                raise _Failed(reason)
            if not os.path.isfile(part) or os.path.getsize(part) != item.size:
                raise _Failed("size")
            if task.verify_hash and _hash_local(part) != self._phone_hash(item.src, item.size):
                raise _Failed("mismatch")
            os.utime(part, (item.mtime, item.mtime))
            for _ in range(_COMMIT_TRIES):
                try:
                    _commit_no_overwrite(part, dst)
                    break
                except FileExistsError:  # cel pojawił się w trakcie — nigdy nie nadpisujemy
                    dst = self._pc_side(task, folder, name)
                    renamed = True
            else:
                raise _Failed("error")
            part = ""
        finally:
            with self._lock:
                task.inflight.pop(idx, None)
            if part:
                _unlink(part)
        return ("done", "1" if renamed else "0")

    def _pc_side(self, task: _Task, folder: str, name: str) -> str:
        try:
            existing = os.listdir(folder)
        except OSError:
            existing = []
        new = side_name(name, self._taken(task, folder, existing), "z telefonu")
        self._claim(task, folder, new)
        return os.path.join(folder, new)

    def _pull(self, task: _Task, src: str, part: str) -> PullResult:
        try:
            return self._puller.pull([src], Path(part), self._should_stop(task), lambda: self._progress(task))
        except AdbError as exc:  # np. adb zniknął razem z telefonem — rozstrzyga `_online`
            return PullResult(1, [f"adb: error: {exc.kind}"], False)

    # ---- komputer -> telefon --------------------------------------------------------------
    def _prepare(self, task: _Task) -> None:
        if task.plan.kind == "to_pc":
            for d in task.plan.dirs:
                try:
                    os.makedirs(d, exist_ok=True)
                except OSError:
                    pass  # pobranie do takiego folderu się nie uda i plik trafi do nieudanych
            return
        refused: set[str] = set()
        for batch in _cmd_batches(task.plan.dirs):
            try:
                self._adb_factory().shell("mkdir -p " + " ".join(q(d) for d in batch), timeout=120)
            except AdbError as exc:
                if exc.kind in _CONNECTION_KINDS or not self._online():
                    raise _Disconnect from exc
                refused |= _refused_paths(exc.message)
        if not refused:
            return
        for idx, item in enumerate(task.plan.items):
            folder = posixpath.dirname(item.dst)
            if task.status[idx] == "pending" and any(folder == r or folder.startswith(r + "/") for r in refused):
                self._settle(task, idx, item, ("failed", "denied"))

    def _to_phone(self, task: _Task, idx: int, item: Item) -> tuple[str, ...]:
        folder, name = posixpath.split(item.dst)
        target = item.dst
        renamed = item.action == "renamed"
        size = os.path.getsize(item.src)
        if item.action == "check_hash":
            existing = self._phone_size(target)
            if existing == size and self._phone_hash(target, size) == _hash_local(item.src):
                return ("skipped",)
            if existing is not None:
                target = self._phone_side(task, folder, name)
                renamed = True
        tmp = f"{folder}/{TMP_PREFIX}{self._token()}{TMP_SUFFIX}"
        if not is_tmp_name(posixpath.basename(tmp)):
            raise _Failed("error")
        self._add_tmp(task, tmp)
        res = self._push(task, item.src, tmp)
        if res.stopped:
            self._rm_tmp(task, tmp)
            return ("stopped",)
        if res.rc != 0:
            if not self._online():
                raise _Disconnect
            self._rm_tmp(task, tmp)
            text = "\n".join(res.lines).lower()
            raise _Failed("denied" if any(d in text for d in _DENIED) else "error")
        try:
            if self._phone_size(tmp) != size:
                raise _Failed("size")
            if task.verify_hash and self._phone_hash(tmp, size) != _hash_local(item.src):
                raise _Failed("mismatch")
        except _Failed:
            self._rm_tmp(task, tmp)
            raise
        try:
            for _ in range(_COMMIT_TRIES):
                with self._lock:
                    task.committing[idx] = (tmp, target, size)
                self._shell(f"mv -n {q(tmp)} {q(target)}")
                sizes = self._phone_sizes([tmp, target])
                if tmp not in sizes:
                    with self._lock:
                        task.committing.pop(idx, None)
                    self._drop_tmp(task, tmp)
                    if sizes.get(target) != size:
                        raise _Failed("error")
                    if _is_media(target):
                        with self._lock:
                            task.media.append(target)
                    return ("done", "1" if renamed else "0")
                # cel pojawił się w trakcie: `mv -n` zostawił oba pliki — nazwa obok
                target = self._phone_side(task, folder, name)
                renamed = True
            raise _Failed("error")
        except _Failed:
            with self._lock:
                task.committing.pop(idx, None)
            if tmp in task.tmps:
                self._rm_tmp(task, tmp)
            raise

    def _push(self, task: _Task, src: str, tmp: str) -> PullResult:
        try:
            return self._pusher.push([Path(src)], tmp, self._should_stop(task), lambda: self._progress(task))
        except AdbError as exc:
            return PullResult(1, [f"adb: error: {exc.kind}"], False)

    def _phone_sizes(self, remotes: list[str]) -> dict[str, int]:
        """Rozmiary istniejących zwykłych plików (`stat` z `STAT_TAIL`: brak pliku = linia błędu)."""
        out = self._shell("stat -c '%f|%s|%Y|%n' " + " ".join(q(r) for r in remotes) + STAT_TAIL)
        sizes: dict[str, int] = {}
        for line in out.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4 and parts[1].isdigit() and parts[3] in remotes:
                try:
                    is_dir = int(parts[0], 16) & 0o170000 == 0o040000
                except ValueError:
                    continue
                if not is_dir:
                    sizes[parts[3]] = int(parts[1])
        return sizes

    def _phone_size(self, remote: str) -> int | None:
        return self._phone_sizes([remote]).get(remote)

    def _phone_side(self, task: _Task, folder: str, name: str) -> str:
        try:
            existing = [e.name for e in list_dir(self._adb_factory(), folder, include_hidden=True).entries]
        except ListError as exc:
            if exc.kind == "offline" or not self._online():
                raise _Disconnect from exc
            existing = []
        new = side_name(name, self._taken(task, folder, existing), "z komputera")
        self._claim(task, folder, new)
        return f"{folder}/{new}"

    # ---- pliki tymczasowe na telefonie ---------------------------------------------------
    def _add_tmp(self, task: _Task, tmp: str) -> None:
        folder = posixpath.dirname(tmp)
        with self._lock:
            task.tmps.add(tmp)
            first = self._folders.get(folder, 0) == 0
            self._folders[folder] = self._folders.get(folder, 0) + 1
        if first:  # na dysku przed `push` — po zabitym programie sprząta `sweep_recorded`
            record_tmp_folder(self.serial, folder, directory=self.tmp_dir)

    def _drop_tmp(self, task: _Task, tmp: str) -> None:
        """Pliku tymczasowego już nie ma (przeniesiony albo usunięty)."""
        folder = posixpath.dirname(tmp)
        with self._lock:
            if tmp not in task.tmps:
                return
            task.tmps.discard(tmp)
            left = self._folders.get(folder, 1) - 1
            if left > 0:
                self._folders[folder] = left
            else:
                self._folders.pop(folder, None)
        if left <= 0:
            forget_tmp_folder(self.serial, folder, directory=self.tmp_dir)

    def _rm_tmp(self, task: _Task, tmp: str) -> bool:
        """`rm -f` naszego pliku tymczasowego; przy odłączonym telefonie zostaje na liście."""
        try:
            self._adb_factory().shell(f"rm -f {q(tmp)}")
        except AdbError:
            return False
        self._drop_tmp(task, tmp)
        return True

    def _clean_tmps(self, task: _Task, strict: bool = False) -> None:
        """Pliki tymczasowe z przerwanych prób: przeniesiony przed odłączeniem (`mv -n` doszedł) → plik
        gotowy; inny → `rm -f`. `strict`: niedostępny telefon → `_Disconnect` (inaczej zostają na liście)."""
        with self._lock:
            tmps = sorted(task.tmps)
            committing = {v[0]: (k, v) for k, v in task.committing.items()}
        for tmp in tmps:
            if tmp in committing:
                idx, (_, target, size) = committing[tmp]
                try:
                    sizes = self._phone_sizes([tmp, target])
                except (_Disconnect, _Failed):
                    if strict and not self._online():
                        raise _Disconnect from None
                    if strict:  # telefon jest, ale nie odpowiada na `stat`: plik zostaje dla `sweep_tmp`
                        with self._lock:
                            task.committing.pop(idx, None)
                        self._abandon_tmp(task, tmp)
                    continue
                with self._lock:
                    task.committing.pop(idx, None)
                if tmp not in sizes and sizes.get(target) == size:
                    self._drop_tmp(task, tmp)
                    if _is_media(target):
                        with self._lock:
                            task.media.append(target)
                    item = task.plan.items[idx]
                    self._settle(task, idx, item, ("done", "1" if target != item.dst else "0"))
                    continue
            if not self._rm_tmp(task, tmp) and strict:
                if not self._online():
                    raise _Disconnect
                self._abandon_tmp(task, tmp)  # `rm -f` odmówił przy działającym telefonie

    def _abandon_tmp(self, task: _Task, tmp: str) -> None:
        """Pliku tymczasowego nie da się usunąć teraz: zadanie przestaje go pilnować, a folder zostaje na
        liście na dysku (licznik folderu nie maleje), więc posprząta go `sweep_tmp` przy następnym otwarciu."""
        with self._lock:
            task.tmps.discard(tmp)

    # ---- skan mediów ---------------------------------------------------------------------
    def _scan(self, media: list[str]) -> None:
        try:
            if self._sdk is None:
                self._sdk = self._sdk_fn() if self._sdk_fn is not None else self._read_sdk()
            if self._sdk < 29:
                return  # Android < 10: galeria odświeży się sama po restarcie
            adb = self._adb_factory()
            if len(media) > SCAN_FILE_MAX:
                adb.shell(SCAN_VOLUME_CMD, timeout=120)
                return
            for remote in media:
                arg = _STORAGE + remote[len("/sdcard"):]
                adb.shell(f"content call --uri content://media --method scan_file --arg {q(arg)}")
        except AdbError:
            pass  # bez skanu pliki i tak są; galeria dojdzie do nich sama

    def _read_sdk(self) -> int:
        out = self._adb_factory().shell("getprop ro.build.version.sdk").strip()
        return int(out) if out.isdigit() else 0


def _commit_no_overwrite(src: str, dst: str) -> None:
    """Zmiana nazwy, która nigdy nie nadpisuje: `FileExistsError`, gdy `dst` istnieje (też w chwili zapisu).
    Windows: `os.rename` sam odmawia; gdzie indziej `os.link` (atomowo) i usunięcie `src`."""
    if os.name == "nt":
        os.rename(src, dst)
        return
    try:
        os.link(src, dst)
    except FileExistsError:
        raise
    except OSError:  # system plików bez dowiązań: sprawdzenie tuż przed zmianą nazwy
        if os.path.lexists(dst):
            raise FileExistsError(dst) from None
        os.rename(src, dst)
        return
    os.unlink(src)


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
