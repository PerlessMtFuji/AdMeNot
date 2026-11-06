"""Most GUI <-> eksplorator plików telefonu (`ExplorerMixin`, dołączany do `Api`).

Sesja eksploratora trzyma blokadę telefonu (`oplock.device_lock`) przez cały czas otwarcia, więc skan,
naprawa i przenoszenie danych na tym telefonie nie ruszą, dopóki serwisant nie wróci na „Połącz”.
Wszystkie polecenia adb idą przez `ExplorerAdb` (strażnik eksploratora) nad `SessionLogAdb` tego
telefonu — log sesji na dysku zwija ścieżki plików klienta (`client_paths`). Pliki do podglądu
i miniatury idą z lokalnego `MediaServer`, nie przez most JSON. Obecność telefonu śledzi odczyt listy
telefonów (`_device_list`, obserwator z `watch_devices`): zniknął → `explorer:offline`; wrócił ten
sam → `explorer:online` (UI odświeża bieżący folder); zamiast niego pojawił się inny → eksplorator
się zamyka (`explorer:closed`).
"""

from __future__ import annotations

import contextlib
import functools
import math
import os
import queue
import re
import shutil
import tempfile
import threading
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

from admenot.app import telemetry, winclip
from admenot.app.errors import AppError, bridge, log_exception
from admenot.app.explorer_present import ROOT, crumbs, entry_view, file_type, place_view
from admenot.app.present import device_card
from admenot.app.telemetry_events import explorer_event
from admenot.engine.adb.devices import list_devices
from admenot.engine.adb.sessionlog import SessionLogAdb
from admenot.engine.adb.transport import AdbError
from admenot.engine.clientpaths import client_paths
from admenot.engine.device.info import DeviceInfo, read_device_info
from admenot.engine.explorer import hostfs
from admenot.engine.explorer.create import CreateError, make_folder, make_text
from admenot.engine.explorer.guard import (
    ExplorerAdb,
    UnsafeCommand,
    explorer_pusher,
    is_tmp_name,
    safe_read_path,
)
from admenot.engine.explorer.listing import ListError, list_dir, list_error
from admenot.engine.explorer.media import MediaServer
from admenot.engine.explorer.meta import image_meta, media_meta
from admenot.engine.explorer.places import Place, count_place, find_places, place_bytes
from admenot.engine.explorer.plan import Problem, TaskPlan, plan_to_pc, plan_to_phone
from admenot.engine.explorer.queue import TransferQueue, sweep_recorded
from admenot.engine.explorer.textview import TEXT_LIMIT, decode_chunk
from admenot.engine.explorer.thumbs import EXIF_HEAD
from admenot.engine.oplock import DeviceBusy, device_lock
from admenot.engine.paths import journal_path
from admenot.engine.phones.provider import PhoneMatch
from admenot.engine.settings import (
    EXPLORER_RECENT_MAX,
    EXPLORER_RECENT_PHONES,
    SettingsTooNew,
    save_internal,
)
from admenot.engine.tools import resolve_adb
from admenot.engine.transfer.guard import STAT_TAIL, q

__all__ = ["ExplorerMixin", "MediaFactory", "explorer_temp_dir"]

MediaFactory = Callable[[str, ExplorerAdb, Callable[[str], bool]], MediaServer]
_LOCAL_ORIGIN = re.compile(r"http://(?:127\.0\.0\.1|localhost)(?::\d{1,5})?")
_END = frozenset({"done", "cancelled", "failed"})  # końcowe stany zadania kolejki
_PREVIEW_KINDS = frozenset({"image", "video", "audio"})  # podgląd przez `explorer_meta` (tekst: `explorer_text`)
EXPLORER_QUIT_WAIT = 10.0  # s; wyjście z programu czeka na wątek kolejki (zabicie `adb`, sprzątanie)


def _bridge(method: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Metoda mostu eksploratora: nieoczekiwany błąd w lokalnym logu bez nazw plików klienta, a klucz
    każdego błędu (nie komunikat) liczy się do statystyk otwartej sesji."""
    wrapped = bridge(method, scrub=client_paths)

    @functools.wraps(method)
    def counted(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        out = wrapped(self, *args, **kwargs)
        error = out.get("error") if isinstance(out, dict) else None
        sess = self._explorer
        if isinstance(error, dict) and sess is not None:
            sess.stats.note_error(str(error.get("key")))
        return out

    return counted


def explorer_temp_dir() -> Path:
    """`%TEMP%/AdMeNot/explorer` — pliki robocze eksploratora; czyszczony przy zamknięciu i starcie."""
    return Path(tempfile.gettempdir()) / "AdMeNot" / "explorer"


def _local_origin(origin: str) -> bool:
    """Okno programu (pywebview `http_server`) i serwer deweloperski UI: tylko pętla zwrotna."""
    return _LOCAL_ORIGIN.fullmatch(origin) is not None


class _Pump:
    """Zdarzenia kolejki zadań do okna z osobnego wątku: `emit` kolejki woła się pod jej blokadą
    zdarzeń, a wysłanie do okna (`run_js`) potrafi czekać na wątek GUI."""

    def __init__(self, emit: Callable[[str, Any], None]) -> None:
        self._emit = emit
        self._items: queue.SimpleQueue[tuple[str, Any] | None] = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._loop, name="explorer-events", daemon=True)
        self._thread.start()

    def __call__(self, name: str, detail: Any) -> None:
        self._items.put((name, detail))

    def close(self) -> None:
        self._items.put(None)

    def _loop(self) -> None:
        while (item := self._items.get()) is not None:
            try:
                self._emit(*item)
            except Exception as exc:  # noqa: BLE001 — zamknięte okno nie zatrzymuje kolejki
                log_exception(exc, scrub=client_paths)


@dataclass
class _Stats:
    """Liczby sesji do telemetrii (`explorer_event`): bez nazw plików i ścieżek. Zadania kolejki
    aktualizuje wątek kolejki, resztę wątki mostu — stąd blokada."""

    started: float = 0.0
    previews: Counter[str] = field(default_factory=Counter)
    created: Counter[str] = field(default_factory=Counter)
    errors: Counter[str] = field(default_factory=Counter)
    files: Counter[str] = field(default_factory=Counter)  # to_pc / to_phone → przesłane pliki
    bytes: Counter[str] = field(default_factory=Counter)  # to_pc / to_phone → przesłane bajty
    speeds: list[float] = field(default_factory=list)  # średnia prędkość zakończonych zadań, B/s
    runs: dict[str, tuple[float | None, float]] = field(default_factory=dict)  # zadanie → (od kiedy działa, czas pracy)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def note_error(self, key: str) -> None:
        with self.lock:
            self.errors[key] += 1

    def note(self, counter: str, key: str) -> None:
        with self.lock:
            getattr(self, counter)[key] += 1

    def task(self, view: dict[str, Any], now: float) -> None:
        """Zdarzenie kolejki: czas pracy zadania (bez pauz i czekania na telefon), a po końcu zadania
        pliki, bajty, prędkość i powody nieudanych plików (`file_<powód>`)."""
        tid, status = view["id"], view["status"]
        with self.lock:
            since, active = self.runs.get(tid, (None, 0.0))
            if status == "running" and since is None:
                since = now
            elif status != "running" and since is not None:
                since, active = None, active + max(0.0, now - since)
            if status not in _END:
                self.runs[tid] = (since, active)
                return
            if tid not in self.runs:
                return  # koniec już policzony
            del self.runs[tid]
            self.files[view["kind"]] += view["done_files"]
            self.bytes[view["kind"]] += view["done_bytes"]
            for _src, reason in view["failed"]:
                self.errors[f"file_{reason}"] += 1
            if active > 0 and view["done_bytes"] > 0:
                self.speeds.append(view["done_bytes"] / active)


@dataclass
class _Session:
    serial: str
    device: DeviceInfo
    match: PhoneMatch | None
    log: SessionLogAdb
    adb: ExplorerAdb
    media: MediaServer
    base: str  # adres serwera mediów
    stack: contextlib.ExitStack  # blokada telefonu i serwer mediów
    places: list[Place]
    offline: bool = False
    others: frozenset[str] = frozenset()  # inne telefony gotowe, gdy nasz zniknął
    queue: TransferQueue | None = None
    pump: _Pump | None = None
    text: tuple[str, int, str] | None = None  # podgląd tekstu: (ścieżka, następny bajt, kodek)
    stats: _Stats = field(default_factory=_Stats)  # liczby do telemetrii przy zamknięciu
    locked: set[str] = field(default_factory=set)  # foldery z kłódką wg sondy listowania (R5) — do planu wgrywania
    card: dict[str, Any] = field(init=False)  # karta telefonu (nazwa w okruszkach)

    def __post_init__(self) -> None:
        self.card = device_card(self.device, self.match)

    @property
    def name(self) -> str:
        return str(self.card["name"])


class ExplorerMixin:
    """Metody `explorer_*` dla `Api`. Korzysta z pól i metod `Api` (`_emit`, `_session`, `_host`,
    `_settings`, `_jobs`, `_sync`, `_names`, `_serial`, `_provider`, `_open_url`, fabryk `adb pull/push`
    i `_require_cleaned`)."""

    def _explorer_setup(self, media_factory: MediaFactory | None, temp_dir: Path | None,
                        clipboard: Callable[[], list[str]] | None = None) -> None:
        self._explorer: _Session | None = None
        self._explorer_lock = threading.RLock()
        self._explorer_media = media_factory or self._real_media
        self._explorer_temp = temp_dir or explorer_temp_dir()
        self._explorer_clipboard = clipboard or winclip.clipboard_files
        self._pick_files_fn: Callable[[], list[str]] | None = None
        self._explorer_seq = 0  # kolejne kolejki zadań (przedrostek identyfikatorów)
        self._explorer_clean_temp()

    # --- pomocnicze -----------------------------------------------------------------------

    def _real_media(self, serial: str, adb: ExplorerAdb, allow_origin: Callable[[str], bool]) -> MediaServer:
        path = resolve_adb(self._settings.adb_path).path
        if path is None:
            raise AdbError("adb_missing", "adb")
        return MediaServer(path, serial, allow_origin)

    def _explorer_clean_temp(self) -> None:
        shutil.rmtree(self._explorer_temp, ignore_errors=True)

    def _explorer_session(self) -> _Session:
        sess = self._explorer
        if sess is None:
            raise AppError("explorer_not_open")
        return sess

    def _ready_serials(self) -> set[str]:
        return {e.serial for e in list_devices(self._host) if e.state == "device"}

    def _explorer_apps(self, sess: _Session) -> dict[str, str]:
        """Nazwy aplikacji do folderów `Android/media|data/<pakiet>` — z ostatniego skanu tego telefonu."""
        return self._names() if self._serial == sess.serial else {}

    @staticmethod
    def _explorer_online(sess: _Session) -> bool:
        try:
            return sess.adb.run(["get-state"]).strip() == "device"
        except AdbError:
            return False

    def _explorer_error(self, sess: _Session | None, exc: Exception) -> AppError:
        """Błąd silnika → klucz `explorer_*` (bez ścieżek w komunikacie)."""
        if isinstance(exc, CreateError):
            return AppError(f"explorer_{exc.key}")
        if isinstance(exc, FileNotFoundError):
            return AppError("explorer_missing")
        if isinstance(exc, AdbError):
            exc = list_error(exc)
        if isinstance(exc, ListError):
            if exc.kind == "failed":  # nieznany błąd: odłączenie albo odmowa telefonu
                return AppError("explorer_offline" if sess is None or not self._explorer_online(sess)
                                else "explorer_denied")
            return AppError(f"explorer_{exc.kind}")
        return AppError("bad_request", "path") if isinstance(exc, UnsafeCommand) else AppError("internal")

    @contextlib.contextmanager
    def _explorer_errors(self, sess: _Session | None) -> Iterator[None]:
        try:
            yield
        except (ListError, CreateError, AdbError, UnsafeCommand, FileNotFoundError) as exc:
            raise self._explorer_error(sess, exc) from None

    @staticmethod
    def _explorer_path(path: Any, file: bool = False) -> str:
        """Ścieżka z UI: `/sdcard` (tylko folder) albo pod `/sdcard/`, bez `..` i nowej linii."""
        if not isinstance(path, str):
            raise AppError("bad_request", "path")
        clean = path.rstrip("/") or path
        if clean == ROOT and not file:
            return ROOT
        try:
            return safe_read_path(clean)
        except UnsafeCommand:
            raise AppError("bad_request", "path") from None

    def _explorer_stat(self, sess: _Session, path: str) -> tuple[bool, int, int]:
        """(czy folder, rozmiar, mtime); brak → `explorer_missing`, odmowa → `explorer_denied`."""
        with self._explorer_errors(sess):
            out = sess.adb.shell("stat -c '%f|%s|%Y|%n' " + q(path) + STAT_TAIL)
        for line in out.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4 and parts[3] == path and parts[1].isdigit():
                try:
                    is_dir = int(parts[0], 16) & 0o170000 == 0o040000
                    return is_dir, int(parts[1]), int(parts[2])
                except ValueError:
                    break
            if "permission denied" in line.lower():
                raise AppError("explorer_denied")
        raise AppError("explorer_missing")

    def _explorer_sweep(self, sess_adb: ExplorerAdb, serial: str, skip: set[str]) -> int:
        """Nasze pliki tymczasowe z poprzednich otwarć (zabity program); błąd nie blokuje otwarcia."""
        try:
            return sweep_recorded(sess_adb, serial, skip=skip)
        except (AdbError, UnsafeCommand, OSError) as exc:
            log_exception(exc, scrub=client_paths)
            return 0

    def _explorer_view(self, sess: _Session, leftovers: int) -> dict[str, Any]:
        return {"device": sess.card, "places": [place_view(p) for p in sess.places],
                "media": sess.base, "sdk": sess.device.sdk, "leftovers": leftovers,
                "recent": list(self._settings.explorer_recents.get(sess.serial, []))}

    def _explorer_count(self, sess: _Session) -> None:
        """Liczby plików Miejsc w tle; po każdym miejscu `explorer:places` (nieudane — bez liczby)."""
        def run() -> None:
            for i, place in enumerate(list(sess.places)):
                if self._explorer is not sess:
                    return
                try:
                    count: int | None = count_place(sess.adb, place)
                except (ListError, AdbError):
                    count = None
                except Exception as exc:  # noqa: BLE001 — jedno miejsce bez liczby, reszta liczy się dalej
                    log_exception(exc, scrub=client_paths)
                    count = None
                with self._explorer_lock:
                    if self._explorer is not sess:
                        return
                    sess.places[i] = replace(place, count=count)
                    views = [place_view(p) for p in sess.places]
                self._emit("explorer:places", {"places": views})

        if self._sync:
            run()
        else:
            threading.Thread(target=run, name="explorer-places", daemon=True).start()

    def _explorer_remember(self, serial: str, path: str) -> None:
        """„Ostatnio” — ostatnie odwiedzone foldery (bez korzenia pamięci), osobno dla każdego telefonu:
        foldery poprzedniego klienta nie pokazują się przy następnym telefonie. Pamiętamy
        `EXPLORER_RECENT_PHONES` telefonów; najdawniej używany wypada."""
        if path == ROOT:
            return
        recents = self._settings.explorer_recents
        old = recents.get(serial, [])
        recent = [path, *(p for p in old if p != path)][:EXPLORER_RECENT_MAX]
        if recent == old and next(reversed(recents), None) == serial:
            return
        updated = {k: v for k, v in recents.items() if k != serial}
        updated[serial] = recent  # na koniec: ostatnio używany
        while len(updated) > EXPLORER_RECENT_PHONES:
            del updated[next(iter(updated))]
        try:
            self._settings = save_internal({"explorer_recents": updated})
        except (OSError, ValueError, TimeoutError, SettingsTooNew) as exc:
            log_exception(exc, scrub=client_paths)

    def _explorer_end(self, only: _Session | None = None, wait: bool | None = None) -> _Session | None:
        """Zamknięcie sesji: kolejka (anulowana), serwer mediów, `%TEMP%`, blokada telefonu; zwraca
        zamkniętą sesję. `only` — tylko gdy otwarta jest wciąż ta sesja (zamknięcie z obserwatora telefonów).

        Bez czekania (`wait` None = tylko w testach `sync_jobs` czekamy): woła to wątek GUI (`_shutdown`),
        obserwator telefonów i `explorer_open` pod blokadą sesji, a wątek kolejki może być w kroku, który
        nie patrzy na anulowanie (`sha256sum` dużego pliku). Kolejka dostaje anulowanie od razu, a blokadę
        telefonu zwalnia wątek `explorer-close` dopiero po końcu wątku kolejki — ten jeszcze sprząta swoje
        pliki tymczasowe na telefonie, więc do tego czasu nikt inny (skan, kopia, nowy eksplorator) nie
        dostaje tego telefonu."""
        with self._explorer_lock:
            sess = self._explorer
            if sess is None or (only is not None and sess is not only):
                return None
            self._explorer = None
        queue_ = sess.queue
        seconds = self._clock() - sess.stats.started
        try:
            sess.media.stop()  # od razu; `stack.close()` woła `stop` jeszcze raz — bez skutku
            if queue_ is not None:
                queue_.shutdown(wait=False)
        finally:
            self._explorer_clean_temp()

        def finish() -> None:
            try:
                if queue_ is not None:
                    queue_.join()
            finally:
                try:
                    # po końcu wątku kolejki (anulowane przy zamknięciu zadania też są już policzone),
                    # a przed zwolnieniem telefonu — błąd zamknięcia nie gubi zdarzenia
                    self._explorer_telemetry(sess, seconds)
                finally:
                    if sess.pump is not None:
                        sess.pump.close()
                    sess.stack.close()

        if queue_ is None or (self._sync if wait is None else wait):
            finish()
        else:
            threading.Thread(target=finish, name="explorer-close", daemon=True).start()
        return sess

    def _explorer_active(self) -> int:
        """Trwające zadania kolejki otwartego eksploratora (zamknięcie sesji je anuluje)."""
        sess = self._explorer
        queue_ = sess.queue if sess is not None else None
        return queue_.active() if queue_ is not None else 0

    def _explorer_quit(self, timeout: float = EXPLORER_QUIT_WAIT) -> None:
        """Wyjście z programu (nie z wątku GUI): sesja się kończy, kolejka anuluje zadania, a my czekamy do
        `timeout` s na jej wątek — ten zabija `adb pull/push` (`_kill_tree`) i usuwa swoje `.admenot-part`,
        zanim proces programu zniknie (inaczej osierocony `adb` pisałby dalej na dysk). Wątek, który nie
        zdążył (np. długie `sha256sum`), zostaje, a pliki w toku na komputerze usuwamy sami."""
        try:
            sess = self._explorer_end(wait=False)
        except Exception as exc:  # noqa: BLE001 — zamknięcie programu nie może utknąć na eksploratorze
            log_exception(exc, scrub=client_paths)
            return
        queue_ = sess.queue if sess is not None else None
        if queue_ is not None and not queue_.join(timeout):
            queue_.drop_partials()

    @staticmethod
    def _explorer_telemetry(sess: _Session, seconds: float) -> None:
        """Zdarzenie `explorer` (same liczby; zgodę sprawdza `telemetry.record`)."""
        st = sess.stats
        with st.lock:
            args = (sess.device, seconds, st.files["to_pc"], st.bytes["to_pc"], st.files["to_phone"],
                    st.bytes["to_phone"], dict(st.previews), dict(st.created), dict(st.errors), list(st.speeds))
        telemetry.record("explorer", lambda _packages: explorer_event(*args))

    def _explorer_task_event(self, sess: _Session, detail: dict[str, Any]) -> None:
        """`explorer:task` z kolejki (wątek kolejki): statystyki sesji, potem widok do okna."""
        try:
            sess.stats.task(detail, self._clock())
        except Exception as exc:  # noqa: BLE001 — statystyki nie zatrzymują zdarzeń kolejki
            log_exception(exc, scrub=client_paths)
        (sess.pump or self._emit)("explorer:task", {"task": _task_view(detail)})
        if detail.get("kind") == "to_phone" and detail.get("status") in _END:
            self._explorer_storage_push(sess)

    def _explorer_storage_push(self, sess: _Session) -> None:
        """`explorer:storage` po zadaniu do telefonu (w tle — liczenie rozmiarów Miejsc trwa)."""
        def run() -> None:
            try:
                if self._explorer is sess:
                    self._emit("explorer:storage", self._explorer_usage(sess))
            except (ListError, AdbError, UnsafeCommand, AppError):
                pass
            except Exception as exc:  # noqa: BLE001 — zdarzenie pamięci nie psuje kolejki
                log_exception(exc, scrub=client_paths)

        if self._sync:
            run()
        else:
            threading.Thread(target=run, name="explorer-storage", daemon=True).start()

    def _explorer_usage(self, sess: _Session) -> dict[str, Any]:
        """Pamięć telefonu: `df -k /sdcard` + rozmiary Miejsc podzielone na zdjęcia, filmy i WhatsApp;
        reszta zajętego miejsca to „inne”."""
        with self._explorer_errors(sess):
            out = sess.adb.shell("df -k /sdcard")
        total = used = 0
        for line in reversed(out.splitlines()):
            cols = line.split()
            if len(cols) >= 4 and cols[1].isdigit() and cols[2].isdigit():
                total, used = int(cols[1]) * 1024, int(cols[2]) * 1024
                break
        else:
            raise AppError("explorer_offline")
        sizes = {"photos": 0, "videos": 0, "whatsapp": 0}
        group = {"camera": "photos", "screenshots": "photos", "movies": "videos", "whatsapp": "whatsapp"}
        for place in list(sess.places):
            key = group.get(place.key)
            if key is None:
                continue
            try:
                sizes[key] += place_bytes(sess.adb, place)
            except (ListError, AdbError):
                continue  # miejsce bez rozmiaru — wchodzi do „inne”
        sizes["other"] = max(0, used - sum(sizes.values()))
        return {"total": total, "used": used, "groups": sizes}

    def _explorer_start(self, sess: _Session, plan: TaskPlan, verify_hash: bool) -> dict[str, Any]:
        """Problemy planu → nic nie startuje, UI je pokazuje; inaczej zadanie trafia do kolejki."""
        if plan.problems:
            for problem in plan.problems:
                sess.stats.note_error(f"problem_{problem.key}")
            return {"problems": [_problem_view(p) for p in plan.problems]}
        try:
            # pod blokadą sesji: plan liczony dla `sess` trafia tylko do kolejki tej sesji — nie do kolejki
            # telefonu otwartego w międzyczasie
            with self._explorer_lock:
                return {"task": self._explorer_queue(sess).add(plan, verify_hash)}
        except RuntimeError:  # kolejka zamknięta w międzyczasie (eksplorator zamknięty)
            raise AppError("explorer_not_open") from None

    def _explorer_save_dest(self, path: str) -> None:
        if path == self._settings.explorer_dest:
            return
        try:
            self._settings = save_internal({"explorer_dest": path})
        except (OSError, ValueError, TimeoutError, SettingsTooNew) as exc:
            log_exception(exc, scrub=client_paths)

    def _explorer_drop(self, paths: list[Any]) -> None:
        """Pliki/foldery upuszczone z Eksploratora Windows (handler `drop` okna, `main.py`): zdarzenie
        `explorer:drop` z liczbą plików i sumą bajtów — tylko przy otwartym eksploratorze."""
        if self._explorer is None:
            return
        paths = [p for p in paths if isinstance(p, str) and p]
        if not paths:
            return
        count, size = _local_totals(paths)
        if self._explorer is not None:
            self._emit("explorer:drop", {"paths": paths, "count": count, "bytes": size})

    def _require_explorer_free(self, serial: str) -> None:
        """Wejście skanu/przenoszenia: telefon z otwartym eksploratorem jest zajęty."""
        sess = self._explorer
        if sess is not None and isinstance(serial, str) and sess.serial == serial.strip():
            raise AppError("busy", "explorer")

    def _explorer_presence(self, ready: set[str]) -> None:
        """Z odczytu listy telefonów: odłączenie, powrót tego samego, pojawienie się innego."""
        with self._explorer_lock:
            sess = self._explorer
            if sess is None:
                return
            if sess.serial in ready:
                if not sess.offline:
                    return
                sess.offline = False
                event: tuple[str, dict[str, Any]] = ("explorer:online", {"serial": sess.serial})
            elif not sess.offline:
                sess.offline, sess.others = True, frozenset(ready)
                event = ("explorer:offline", {"serial": sess.serial})
            elif ready - sess.others:
                event = ("explorer:closed", {"serial": sess.serial, "reason": "other_phone"})
            else:
                sess.others &= ready  # odłączony i podłączony znowu inny telefon też zamknie eksplorator
                return
        if event[0] == "explorer:closed":
            try:
                self._explorer_end(only=sess)
            except Exception as exc:  # noqa: BLE001 — lista telefonów działa dalej
                log_exception(exc, scrub=client_paths)
        self._emit(*event)

    def _explorer_queue(self, expected: _Session | None = None) -> TransferQueue:
        """Kolejka zadań otwartego eksploratora (kopiowanie i wgrywanie, Task 9), tworzona przy pierwszym
        zadaniu: adb, `adb pull/push` i sprawdzanie podłączenia — tylko telefon tej sesji. `expected` —
        sesja, dla której wołający coś przygotował; inna (albo żadna) otwarta → `explorer_not_open`.
        Identyfikatory zadań mają przedrostek sesji (`s<n>t<m>`), więc stary identyfikator nie trafi
        w zadanie nowej sesji."""
        with self._explorer_lock:
            sess = self._explorer_session()
            if expected is not None and sess is not expected:
                raise AppError("explorer_not_open")
            if sess.queue is None:
                self._explorer_seq += 1
                serial = sess.serial
                adb_path = self._settings.adb_path
                sess.pump = None if self._sync else _Pump(self._emit)
                sess.queue = TransferQueue(
                    lambda: sess.adb, self._puller_factory(adb_path, serial, sess.log),
                    explorer_pusher(self._pusher_factory(adb_path, serial, sess.log)),
                    lambda _name, detail: self._explorer_task_event(sess, detail),
                    lambda: serial in self._ready_serials(), sdk=lambda: sess.device.sdk,
                    id_prefix=f"s{self._explorer_seq}t")
            return sess.queue

    # --- metody dla UI ----------------------------------------------------------------------

    @_bridge
    def explorer_open(self, serial: str) -> dict[str, Any]:
        if not isinstance(serial, str) or not serial.strip():
            raise AppError("bad_request", "serial")
        serial = serial.strip()
        old: _Session | None = None
        try:
            with self._explorer_lock:
                sess = self._explorer
                if sess is not None and sess.serial == serial:
                    # ponowne otwarcie (np. odświeżone okno): ta sama sesja; foldery z plikami tymczasowymi
                    # pilnowanymi przez żywą kolejkę zostają
                    skip = sess.queue.tracked_folders() if sess.queue is not None else set()
                    return self._explorer_view(sess, self._explorer_sweep(sess.adb, serial, skip))
                job = self._jobs.current()
                if job is not None:
                    raise AppError("explorer_busy", job.kind)
                try:
                    self._require_cleaned(serial)
                except AppError as exc:
                    if exc.key == "busy":
                        raise AppError("explorer_busy", exc.message) from None
                    raise
                # inny telefon: poprzednia sesja (i jej zadania) się kończy — UI dostaje `explorer:closed`
                # (po zwolnieniu `_explorer_lock`: `run_js` czeka na wątek GUI, a ten może czekać na blokadę)
                old = self._explorer_end()
                stack = contextlib.ExitStack()
                try:
                    try:
                        stack.enter_context(device_lock(journal_path(), serial))
                    except DeviceBusy:
                        raise AppError("explorer_busy", "device") from None
                    log = self._session(serial)
                    with self._explorer_errors(None):
                        device = read_device_info(log)
                    match = self._provider.match(device)
                    adb = ExplorerAdb(log)
                    leftovers = self._explorer_sweep(adb, serial, set())
                    with self._explorer_errors(None):
                        places = find_places(adb)
                    media = self._explorer_media(serial, adb, _local_origin)
                    stack.callback(media.stop)
                    base = media.start()
                    sess = _Session(serial, device, match, log, adb, media, base, stack, places)
                    sess.stats.started = self._clock()
                except BaseException:
                    stack.close()
                    raise
                self._explorer = sess
        finally:
            if old is not None:  # także gdy nowy telefon się nie otworzył — stara sesja i tak zamknięta
                self._emit("explorer:closed", {"serial": old.serial, "reason": "switched"})
        view = self._explorer_view(sess, leftovers)  # liczby miejsc dochodzą zdarzeniem
        self._explorer_count(sess)
        return view

    @_bridge
    def explorer_storage(self) -> dict[str, Any]:
        """Zajęta i całkowita pamięć telefonu z podziałem na grupy (sylwetka z „cieczą” w Miejscach)."""
        return self._explorer_usage(self._explorer_session())

    @_bridge
    def explorer_close(self) -> dict[str, Any]:
        self._explorer_end()
        return {}

    @_bridge
    def explorer_list(self, path: str) -> dict[str, Any]:
        sess = self._explorer_session()
        path = self._explorer_path(path)
        apps = self._explorer_apps(sess)
        locked = False
        try:
            result = list_dir(sess.adb, path, sdk=sess.device.sdk, apps=apps)
            entries, skipped = result.entries, result.skipped
        except ListError as exc:
            if exc.kind != "denied":
                raise self._explorer_error(sess, exc) from None
            entries, skipped, locked = [], 0, True  # folder z kłódką zamiast błędu (spec §5.3)
        except (AdbError, UnsafeCommand) as exc:
            raise self._explorer_error(sess, exc) from None
        with self._explorer_lock:  # wynik sondy kłódki dla planu wgrywania (`plan_to_phone(locked=…)`)
            if locked:
                sess.locked.add(path)
            sess.locked.update(e.path for e in entries if e.locked)
        sess.media.forget_sizes(path)  # świeże rozmiary plików folderu (miniatury, podgląd)
        for entry in entries:
            if entry.kind == "file":
                sess.media.remember_size(entry.path, entry.size)
        if not locked:
            self._explorer_remember(sess.serial, path)
        return {"path": path, "crumbs": crumbs(path, sess.name, apps),
                "entries": [entry_view(e, sess.media) for e in entries], "skipped": skipped, "locked": locked}

    @_bridge
    def explorer_meta(self, path: str) -> dict[str, Any]:
        sess = self._explorer_session()
        path = self._explorer_path(path, file=True)
        is_dir, size, mtime = self._explorer_stat(sess, path)
        meta: dict[str, Any] = {}
        if not is_dir:
            kind, _ext = file_type(PurePosixPath(path).name)
            with self._explorer_errors(sess):
                if kind == "image":
                    meta = image_meta(sess.media.read_range(path, 0, min(size, EXIF_HEAD)))
                elif kind in ("video", "audio"):
                    meta = media_meta(sess.adb, path)
            if kind in _PREVIEW_KINDS:
                sess.stats.note("previews", kind)
        return {"meta": {**meta, "size": size, "mtime": mtime, "path": path}}

    @_bridge
    def explorer_text(self, path: str, more: bool = False) -> dict[str, Any]:
        """Podgląd tekstu po `TEXT_LIMIT` bajtów; `more` — następny kawałek tego samego pliku."""
        sess = self._explorer_session()
        path = self._explorer_path(path, file=True)
        if not isinstance(more, bool):
            raise AppError("bad_request", "more")
        is_dir, size, _mtime = self._explorer_stat(sess, path)
        if is_dir:
            raise AppError("bad_request", "path")
        offset, codec = 0, None
        if more and sess.text is not None and sess.text[0] == path:
            _, offset, codec = sess.text
        want = max(0, min(TEXT_LIMIT, size - offset))
        with self._explorer_errors(sess):
            data = sess.media.read_range(path, offset, want) if want else b""
            if want and not data:  # strumień urwany od razu
                raise AdbError("command_failed", "empty read")
        text, codec, used = decode_chunk(data, codec, final=offset + len(data) >= size)
        if offset == 0:  # następne kawałki tego samego pliku to ten sam podgląd
            sess.stats.note("previews", "text")
        offset += used
        sess.text = (path, offset, codec)
        return {"text": text, "encoding": "utf-16" if codec.startswith("utf-16") else codec,
                "truncated": offset < size}

    @_bridge
    def explorer_mkdir(self, parent: str, name: str) -> dict[str, Any]:
        sess = self._explorer_session()
        if not isinstance(parent, str) or not isinstance(name, str):
            raise AppError("bad_request", "name")
        try:
            with self._explorer_errors(sess):
                made = make_folder(sess.adb, parent, name)
        except AppError as exc:
            raise _bad_name(exc) from None
        sess.stats.note("created", "folder")
        return {"path": made}

    @_bridge
    def explorer_new_text(self, parent: str, name: str, text: str) -> dict[str, Any]:
        sess = self._explorer_session()
        if not all(isinstance(v, str) for v in (parent, name, text)):
            raise AppError("bad_request", "name")
        self._explorer_temp.mkdir(parents=True, exist_ok=True)
        try:
            with self._explorer_errors(sess):
                pusher = explorer_pusher(self._pusher_factory(self._settings.adb_path, sess.serial, sess.log))
                made = make_text(sess.adb, pusher, parent, name, text, temp_dir=self._explorer_temp)
        except AppError as exc:
            raise _bad_name(exc) from None
        sess.stats.note("created", "text")
        return {"path": made}

    @_bridge
    def explorer_open_map(self, lat: float, lon: float) -> dict[str, Any]:
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in (lat, lon)) or abs(lat) > 90 or abs(lon) > 180:
            raise AppError("bad_request", "coordinates")
        la, lo = f"{lat:.6f}", f"{lon:.6f}"
        self._open_url(f"https://www.openstreetmap.org/?mlat={la}&mlon={lo}#map=17/{la}/{lo}")
        return {}

    # --- kopiowanie i wgrywanie -------------------------------------------------------------

    @_bridge
    def explorer_copy(self, paths: list[str], dest: str | None = None,
                      verify_hash: bool = False) -> dict[str, Any]:
        """Kopia zaznaczenia z telefonu do folderu na komputerze (`dest` None → ostatni wybrany).
        Problemy planu (miejsce, FAT32, zapis, odmowa) wracają przed startem zamiast zadania."""
        sess = self._explorer_session()
        if not isinstance(paths, list) or not paths:
            raise AppError("bad_request", "paths")
        if not isinstance(verify_hash, bool):
            raise AppError("bad_request", "verify_hash")
        remote = [self._explorer_path(p, file=True) for p in paths]
        if dest is None:
            dest = self._settings.explorer_dest
        elif not isinstance(dest, str):
            raise AppError("bad_request", "dest")
        if not dest or not os.path.isabs(dest) or not os.path.isdir(dest):  # np. odłączony pendrive
            raise AppError("explorer_no_dest")
        with self._explorer_errors(sess):
            plan = plan_to_pc(sess.adb, remote, Path(dest))
        self._explorer_save_dest(dest)
        return self._explorer_start(sess, plan, verify_hash)

    @_bridge
    def explorer_upload(self, locals_: list[str], remote_dir: str) -> dict[str, Any]:
        """Wgranie plików/folderów z komputera (okno wyboru, upuszczenie, Ctrl+V) do folderu telefonu."""
        sess = self._explorer_session()
        if not isinstance(locals_, list) or not locals_ or not all(
                isinstance(p, str) and os.path.isabs(p) for p in locals_):
            raise AppError("bad_request", "paths")
        remote_dir = self._explorer_path(remote_dir)
        with self._explorer_lock:
            locked = frozenset(sess.locked)
        with self._explorer_errors(sess):  # `df` przy odłączonym telefonie → explorer_offline
            plan = plan_to_phone(sess.adb, [Path(p) for p in locals_], remote_dir, locked=locked)
        return self._explorer_start(sess, plan, False)

    @_bridge
    def explorer_pick_dest(self) -> dict[str, Any]:
        """Okno wyboru folderu docelowego kopii; wybrany zostaje zapamiętany (`explorer_dest`)."""
        path = self._pick_folder_fn() if self._pick_folder_fn else None
        if path:
            self._explorer_save_dest(path)
        return {"path": path}

    @_bridge
    def explorer_pick_upload(self, kind: str) -> dict[str, Any]:
        """Okno wyboru plików (wiele) albo jednego folderu do wgrania; anulowane → pusta lista."""
        if kind == "files":
            return {"paths": list(self._pick_files_fn() or []) if self._pick_files_fn else []}
        if kind == "folder":
            path = self._pick_folder_fn() if self._pick_folder_fn else None
            return {"paths": [path] if path else []}
        raise AppError("bad_request", "kind")

    @_bridge
    def explorer_clipboard(self) -> dict[str, Any]:
        """Pliki i foldery skopiowane (Ctrl+C) w Eksploratorze Windows — do wgrania po Ctrl+V."""
        return {"paths": list(self._explorer_clipboard())}

    @_bridge
    def explorer_tasks(self) -> dict[str, Any]:
        sess = self._explorer_session()
        tasks = sess.queue.tasks() if sess.queue is not None else []
        return {"tasks": [_task_view(asdict(t)) for t in tasks]}

    def _explorer_task_queue(self, task_id: Any) -> TransferQueue | None:
        sess = self._explorer_session()
        if not isinstance(task_id, str):
            raise AppError("bad_request", "id")
        return sess.queue

    @_bridge
    def explorer_pause(self, task_id: str) -> dict[str, Any]:
        queue_ = self._explorer_task_queue(task_id)
        if queue_ is not None:
            queue_.pause(task_id)
        return {}

    @_bridge
    def explorer_resume(self, task_id: str) -> dict[str, Any]:
        queue_ = self._explorer_task_queue(task_id)
        if queue_ is not None:
            queue_.resume(task_id)
        return {}

    @_bridge
    def explorer_cancel(self, task_id: str) -> dict[str, Any]:
        """Anulowanie od razu; wstrzymane zadanie z plikiem tymczasowym na telefonie sprząta go
        (`stat`/`rm`, do minuty) — w osobnym wątku, żeby UI nie czekało (w testach `sync_jobs` od razu)."""
        queue_ = self._explorer_task_queue(task_id)
        if queue_ is None:
            return {}

        def cancel() -> None:
            try:
                queue_.cancel(task_id)
            except Exception as exc:  # noqa: BLE001 — sprzątanie dokończy `sweep_tmp` przy następnym otwarciu
                log_exception(exc, scrub=client_paths)

        if self._sync:
            cancel()
        else:
            threading.Thread(target=cancel, name="explorer-cancel", daemon=True).start()
        return {}

    @_bridge
    def explorer_open_folder(self, path: str) -> dict[str, Any]:
        """„Otwórz folder” po kopii: tylko istniejący folder na komputerze — nigdy plik (bez uruchamiania)."""
        if not isinstance(path, str) or not path:
            raise AppError("bad_request", "path")
        folder = Path(path)
        if not folder.is_absolute() or not folder.is_dir():
            raise AppError("explorer_not_folder")
        self._open_file(folder)
        return {}


def _task_view(state: dict[str, Any]) -> dict[str, Any]:
    """`TaskState` (słownik z kolejki) dla UI; nieudane pliki jako `{path, reason}`."""
    return {**state, "speed": round(state["speed"]),
            "failed": [{"path": src, "reason": reason} for src, reason in state["failed"]]}


def _problem_view(problem: Problem) -> dict[str, Any]:
    return {"key": problem.key, "detail": problem.detail}


def _local_totals(paths: list[str]) -> tuple[int, int]:
    """(liczba plików, suma bajtów) upuszczonych plików i folderów na komputerze — foldery rekurencyjnie,
    jak plan wgrywania (bez dowiązań i naszych plików tymczasowych); nieczytelne pozycje są pomijane."""
    count = size = 0

    def walk(folder: str) -> None:
        nonlocal count, size
        try:
            with os.scandir(hostfs.long_path(folder)) as it:
                entries = list(it)
        except OSError:
            return
        for e in entries:
            try:
                if e.is_symlink() or is_tmp_name(e.name):
                    continue
                if e.is_dir(follow_symlinks=False):
                    walk(e.path)
                elif e.is_file(follow_symlinks=False):
                    size += e.stat(follow_symlinks=False).st_size
                    count += 1
            except OSError:
                continue

    for p in paths:
        try:
            if os.path.isdir(p):
                walk(p)
            elif os.path.isfile(p):
                size += os.path.getsize(p)
                count += 1
        except OSError:
            continue
    return count, size


def _bad_name(exc: AppError) -> AppError:
    """Tworzenie: ścieżka spoza `/sdcard/` albo z `..` (strażnik, `UnsafeCommand`) to zła nazwa —
    UI pokazuje ten błąd przy polu nazwy."""
    return AppError("explorer_bad_name") if exc.key == "bad_request" else exc
