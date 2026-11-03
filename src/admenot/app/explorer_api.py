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
import queue
import re
import shutil
import tempfile
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

from admenot.app.errors import AppError, bridge, log_exception
from admenot.app.explorer_present import ROOT, crumbs, entry_view, file_type, place_view
from admenot.app.present import device_card
from admenot.engine.adb.devices import list_devices
from admenot.engine.adb.sessionlog import SessionLogAdb
from admenot.engine.adb.transport import AdbError
from admenot.engine.clientpaths import client_paths
from admenot.engine.device.info import DeviceInfo, read_device_info
from admenot.engine.explorer.create import CreateError, make_folder, make_text
from admenot.engine.explorer.guard import ExplorerAdb, UnsafeCommand, safe_read_path
from admenot.engine.explorer.listing import ListError, list_dir, list_error
from admenot.engine.explorer.media import MediaServer
from admenot.engine.explorer.meta import image_meta, media_meta
from admenot.engine.explorer.places import Place, count_place, find_places
from admenot.engine.explorer.queue import TransferQueue, sweep_recorded
from admenot.engine.explorer.textview import TEXT_LIMIT, decode_chunk
from admenot.engine.explorer.thumbs import EXIF_HEAD
from admenot.engine.oplock import DeviceBusy, device_lock
from admenot.engine.paths import journal_path
from admenot.engine.phones.provider import PhoneMatch
from admenot.engine.settings import EXPLORER_RECENT_MAX, SettingsTooNew, save_internal
from admenot.engine.tools import resolve_adb
from admenot.engine.transfer.guard import STAT_TAIL, q

__all__ = ["ExplorerMixin", "MediaFactory", "explorer_temp_dir"]

MediaFactory = Callable[[str, ExplorerAdb, Callable[[str], bool]], MediaServer]
# Nieoczekiwany błąd metody eksploratora: wpis w lokalnym logu bez nazw plików klienta.
_bridge = functools.partial(bridge, scrub=client_paths)
_LOCAL_ORIGIN = re.compile(r"http://(?:127\.0\.0\.1|localhost)(?::\d{1,5})?")


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

    def _explorer_setup(self, media_factory: MediaFactory | None, temp_dir: Path | None) -> None:
        self._explorer: _Session | None = None
        self._explorer_lock = threading.RLock()
        self._explorer_media = media_factory or self._real_media
        self._explorer_temp = temp_dir or explorer_temp_dir()
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
                "media": sess.base, "sdk": sess.device.sdk, "leftovers": leftovers}

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

    def _explorer_remember(self, path: str) -> None:
        """„Ostatnio” — ostatnie odwiedzone foldery (bez korzenia pamięci)."""
        if path == ROOT:
            return
        recent = [path, *(p for p in self._settings.explorer_recent if p != path)][:EXPLORER_RECENT_MAX]
        if recent == self._settings.explorer_recent:
            return
        try:
            self._settings = save_internal({"explorer_recent": recent})
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
                if sess.pump is not None:
                    sess.pump.close()
                sess.stack.close()

        if queue_ is None or (self._sync if wait is None else wait):
            finish()
        else:
            threading.Thread(target=finish, name="explorer-close", daemon=True).start()
        return sess

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

    def _explorer_queue(self) -> TransferQueue:
        """Kolejka zadań otwartego eksploratora (kopiowanie i wgrywanie, Task 9), tworzona przy pierwszym
        zadaniu: adb, `adb pull/push` i sprawdzanie podłączenia — tylko telefon tej sesji."""
        with self._explorer_lock:
            sess = self._explorer_session()
            if sess.queue is None:
                serial = sess.serial
                adb_path = self._settings.adb_path
                sess.pump = None if self._sync else _Pump(self._emit)
                sess.queue = TransferQueue(
                    lambda: sess.adb, self._puller_factory(adb_path, serial, sess.log),
                    self._pusher_factory(adb_path, serial, sess.log), sess.pump or self._emit,
                    lambda: serial in self._ready_serials(), sdk=lambda: sess.device.sdk)
            return sess.queue

    # --- metody dla UI ----------------------------------------------------------------------

    @_bridge
    def explorer_open(self, serial: str) -> dict[str, Any]:
        if not isinstance(serial, str) or not serial.strip():
            raise AppError("bad_request", "serial")
        serial = serial.strip()
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
            old = self._explorer_end()
            if old is not None:
                self._emit("explorer:closed", {"serial": old.serial, "reason": "switched"})
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
            except BaseException:
                stack.close()
                raise
            self._explorer = sess
        view = self._explorer_view(sess, leftovers)  # liczby miejsc dochodzą zdarzeniem
        self._explorer_count(sess)
        return view

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
        if not locked:
            self._explorer_remember(path)
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
                return {"path": make_folder(sess.adb, parent, name)}
        except AppError as exc:
            raise _bad_name(exc) from None

    @_bridge
    def explorer_new_text(self, parent: str, name: str, text: str) -> dict[str, Any]:
        sess = self._explorer_session()
        if not all(isinstance(v, str) for v in (parent, name, text)):
            raise AppError("bad_request", "name")
        self._explorer_temp.mkdir(parents=True, exist_ok=True)
        try:
            with self._explorer_errors(sess):
                pusher = self._pusher_factory(self._settings.adb_path, sess.serial, sess.log)
                return {"path": make_text(sess.adb, pusher, parent, name, text, temp_dir=self._explorer_temp)}
        except AppError as exc:
            raise _bad_name(exc) from None

    @_bridge
    def explorer_open_map(self, lat: float, lon: float) -> dict[str, Any]:
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in (lat, lon)) or abs(lat) > 90 or abs(lon) > 180:
            raise AppError("bad_request", "coordinates")
        la, lo = f"{lat:.6f}", f"{lon:.6f}"
        self._open_url(f"https://www.openstreetmap.org/?mlat={la}&mlon={lo}#map=17/{la}/{lo}")
        return {}


def _bad_name(exc: AppError) -> AppError:
    """Tworzenie: ścieżka spoza `/sdcard/` albo z `..` (strażnik, `UnsafeCommand`) to zła nazwa —
    UI pokazuje ten błąd przy polu nazwy."""
    return AppError("explorer_bad_name") if exc.key == "bad_request" else exc
