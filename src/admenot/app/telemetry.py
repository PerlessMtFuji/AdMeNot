"""Statystyki użycia (spec kroku H §6): zgoda, kolejka w telemetry.jsonl, wysyłka w tle.

Bez zgody nic nie powstaje. Zapis i wysyłka nigdy nie rzucają — statystyki nie mogą zepsuć
skanu ani naprawy. Cofnięcie zgody kasuje kolejkę i zostawia ID do usunięcia z serwera
(`telemetry_delete.json`), ponawiane do skutku także bez zgody (prawo do usunięcia danych).
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from admenot.app.telemetry_events import common, hour, start_body
from admenot.engine.paths import telemetry_delete_path, telemetry_path
from admenot.engine.settings import (
    Settings,
    check_writable,
    effective_lang,
    load_settings,
    save_internal,
    settings_transaction,
    write_atomic,
)
from admenot.net import client

ENDPOINT = "/api/v1/telemetry"
FORMAT = 1
BATCH = 100
MAX_BYTES = 1024 * 1024
# Worker przyjmuje do 256 KB treści (server/src/telemetry.ts); paczkę liczymy w bajtach UTF-8
# tak, jak wysyła ją `client.post_json`, z zapasem (audyt 2026-10-11, BUG-11).
MAX_REQUEST = 192 * 1024
KEEP = timedelta(days=30)
FIRST = 30.0  # s po starcie
PERIOD = 6 * 3600.0
MIN_GAP = 600.0  # po `record` najwyżej raz na 10 min
RETRY = 600.0  # zaległa kolejka albo usunięcie z serwera: kolejna próba po 10 min, nie po 6 h

Post = Callable[[str, dict[str, Any]], dict[str, Any]]
Delete = Callable[[str], dict[str, Any]]
Now = Callable[[], datetime]

_lock = threading.Lock()  # plik kolejki i lista do usunięcia
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_on_deleted: Callable[[], None] | None = None  # UI chowa baner „usuwanie czeka”


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _log(exc: BaseException) -> None:
    with contextlib.suppress(Exception):
        from admenot.app.errors import log_exception  # errors importuje crash; bez cyklu na starcie

        log_exception(exc)


# --- plik kolejki ----------------------------------------------------------------------------

def _read_events() -> list[dict[str, Any]]:
    path = telemetry_path()
    try:
        raw = path.read_text("utf-8")
    except OSError:
        return []
    events = []
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue  # ucięty zapis albo ręczna edycja — wypada przy najbliższym przepisaniu
        if isinstance(value, dict) and isinstance(value.get("install"), str) \
                and isinstance(value.get("t"), str):
            events.append(value)
    return events


def _write_events(events: list[dict[str, Any]]) -> None:
    path = telemetry_path()
    if not events:
        path.unlink(missing_ok=True)
        return
    write_atomic(path, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))


def _trim(events: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    oldest = hour(now - KEEP)  # porównanie tekstowe: ten sam format „…T HH:00:00Z”
    kept = [e for e in events if e["t"] >= oldest]  # przyszłość (zły zegar) zostaje
    size = sum(len(json.dumps(e, ensure_ascii=False).encode()) + 1 for e in kept)
    while kept and size > MAX_BYTES:
        size -= len(json.dumps(kept[0], ensure_ascii=False).encode()) + 1
        kept.pop(0)
    return kept


# --- lista ID do usunięcia -------------------------------------------------------------------

def _read_deletes() -> list[str]:
    try:
        data = json.loads(telemetry_delete_path().read_text("utf-8"))
    except (OSError, ValueError):
        return []
    ids = data.get("installs") if isinstance(data, dict) else None
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []


def _write_deletes(ids: list[str]) -> None:
    path = telemetry_delete_path()
    if not ids:
        path.unlink(missing_ok=True)
        return
    write_atomic(path, json.dumps({"installs": ids}))


def delete_pending() -> bool:
    with _lock:
        return bool(_read_deletes())


# --- zgoda ----------------------------------------------------------------------------------

def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_consent(telemetry: bool, packages: bool, now: datetime) -> Settings:
    """Spec §4.2: włączenie tworzy ID (raz), wyłączenie kasuje kolejkę i planuje usunięcie z serwera."""
    packages = packages and telemetry
    # Odczyt i zapis pod jedną blokadą: równoległe wywołania z mostu nie tworzą dwóch ID,
    # a `record` nie dopisze zdarzenia starego ID po skasowaniu kolejki. Transakcja ustawień
    # wyklucza też zapis innego klucza ze starą zgodą z innego wątku lub procesu (PRIV-01).
    with _lock, settings_transaction():
        check_writable()  # SettingsTooNew przed czymkolwiek: nic nie ruszamy
        current = load_settings()
        changes: dict[str, Any] = {"telemetry": telemetry, "telemetry_packages": packages,
                                   "telemetry_at": _stamp(now),
                                   "telemetry_id": (current.telemetry_id or str(uuid.uuid4()))
                                   if telemetry else None}
        if not telemetry and current.telemetry_id:
            # Najpierw trwały zapis żądania usunięcia, dopiero potem zapomnienie ID: błąd zapisu
            # nie może zgubić identyfikatora danych na serwerze (PRIV-03).
            pending = _read_deletes()
            if current.telemetry_id not in pending:
                _write_deletes([*pending, current.telemetry_id])
        settings = save_internal(changes)
        if not telemetry:
            _write_events([])
        elif not packages and current.telemetry_packages:
            _write_events([{**e, "packages": None} if "packages" in e else e
                           for e in _read_events()])
    _wake.set()
    return settings


# --- zapis ----------------------------------------------------------------------------------

def record(type_: str, build: Callable[[bool], dict[str, Any]], now: Now | None = None) -> None:
    try:
        # Zgoda sprawdzona i zdarzenie zapisane bez cofnięcia zgody pomiędzy (także z innego procesu).
        with _lock, settings_transaction():
            settings = load_settings()
            if not settings.telemetry or not settings.telemetry_id:
                return
            when = (now or _utc_now)()
            event = {**common(settings.telemetry_id, type_, when, effective_lang(settings)),
                     **build(settings.telemetry_packages)}
            _write_events(_trim([*_read_events(), event], when))
        _wake.set()
    except Exception as exc:  # noqa: BLE001 — statystyki nigdy nie psują pracy
        _log(exc)


def note_start(mode: str, now: datetime) -> None:
    """Zdarzenie „start” najwyżej raz na dobę UTC (spec §6.5)."""
    try:
        settings = load_settings()
        day = now.astimezone(UTC).strftime("%Y-%m-%d")
        if not settings.telemetry or settings.telemetry_start_day == day:
            return
        record("start", lambda _packages: start_body(mode), now=lambda: now)
        save_internal({"telemetry_start_day": day})
    except Exception as exc:  # noqa: BLE001
        _log(exc)


# --- wysyłka --------------------------------------------------------------------------------

def _waiting(exc: client.BackendError) -> bool:
    """Serwer nieosiągalny, przeciążony albo limit dzienny — próbujemy później."""
    return exc.kind != "http" or exc.status in (429,) or (exc.status or 0) >= 500


def _send_deletes(delete: Delete, on_deleted: Callable[[], None] | None = None) -> bool:
    """True, jeśli poszło choć jedno zapytanie."""
    with _lock:
        ids = _read_deletes()
    done = []
    for install in ids:
        try:
            delete(f"{ENDPOINT}/{install}")
        except client.BackendError as exc:
            if _waiting(exc):
                break
            _log(exc)  # 400/404: nie ma czego usuwać albo zły ID — nie ponawiamy w nieskończoność
        done.append(install)
    if done:
        with _lock:
            rest = [i for i in _read_deletes() if i not in done]
            _write_deletes(rest)
        if not rest and on_deleted is not None:
            on_deleted()
    return bool(ids)


def _request_bytes(events: list[dict[str, Any]]) -> int:
    return len(json.dumps({"format": FORMAT, "events": events}).encode("utf-8"))


def _batch(events: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Najdłuższy początek kolejki (≤ `limit` zdarzeń), który mieści się w MAX_REQUEST."""
    batch: list[dict[str, Any]] = []
    size = _request_bytes([])
    for event in events[:limit]:
        grown = size + len(json.dumps(event).encode("utf-8")) + 2  # przecinek i spacja
        if batch and grown > MAX_REQUEST:
            break
        batch.append(event)
        size = grown
    return batch


def _remove(sent: list[dict[str, Any]]) -> None:
    with _lock:
        rest = _read_events()
        for event in sent:  # nowe wpisy mogły dojść w trakcie wysyłki — usuwamy tylko wysłane
            with contextlib.suppress(ValueError):
                rest.remove(event)
        _write_events(rest)


def send_pending(post: Post | None = None, delete: Delete | None = None,
                 stop: threading.Event | None = None, now: Now | None = None,
                 on_deleted: Callable[[], None] | None = None) -> bool:
    """Wysyła usunięcia i kolejkę; True, jeśli poszło choć jedno zapytanie (dla limitu w `_loop`)."""
    post = post or client.post_json
    went = False
    limit = BATCH
    try:
        went = _send_deletes(delete or client.delete, on_deleted)
        while stop is None or not stop.is_set():
            settings = load_settings()
            with _lock:
                events = _read_events()
                if not settings.telemetry or not settings.telemetry_id:
                    return went
                mine = [e for e in events if e["install"] == settings.telemetry_id]
                if len(mine) != len(events):  # pozostałość po cofniętej zgodzie — nie wychodzi
                    _write_events(_trim(mine, (now or _utc_now)()))
            batch = _batch(mine, limit)
            if not batch:
                return went
            went = True
            try:
                post(ENDPOINT, {"format": FORMAT, "events": batch})
            except client.BackendError as exc:
                if _waiting(exc):
                    return went
                if exc.status == 413 and len(batch) > 1:
                    limit = max(1, len(batch) // 2)  # za duża paczka: dzielimy, nic nie kasujemy
                    continue
                _log(exc)  # 400 albo pojedyncze zbyt duże zdarzenie nie blokuje kolejki na zawsze
            _remove(batch)
            limit = BATCH
    except Exception as exc:  # noqa: BLE001
        _log(exc)
    return went


def _loop(wake: threading.Event, stop: threading.Event,
          clock: Callable[[], float] = time.monotonic) -> None:
    delay = FIRST
    last: float | None = None
    while True:
        wake.wait(delay)
        wake.clear()
        if stop.is_set():
            return
        # Przerwa dotyczy statystyk; usunięcie danych po cofnięciu zgody idzie od razu.
        if last is not None and clock() - last < MIN_GAP and not delete_pending():
            delay = MIN_GAP - (clock() - last)
            continue
        # Limit 10 min liczy się od próby, która coś wysłała: pusta (np. tuż po zgodzie, zanim
        # powstało pierwsze zdarzenie) nie wstrzymuje wysyłki skanu.
        if send_pending(stop=stop, on_deleted=_on_deleted):
            last = clock()
        delay = _next_delay()


def _next_delay() -> float:
    """Coś czeka na sieć (zdarzenia albo usunięcie po cofnięciu zgody) → RETRY, inaczej PERIOD."""
    try:
        waiting = delete_pending() or telemetry_path().exists()
    except OSError:
        waiting = False
    return RETRY if waiting else PERIOD


def start(on_deleted: Callable[[], None] | None = None) -> None:
    """Wątek wysyłki (z `run_gui`); CLI nigdy niczego nie wysyła."""
    global _thread, _on_deleted
    if _thread is not None:
        return
    _on_deleted = on_deleted
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(_wake, _stop), daemon=True,
                               name="admenot-telemetry")
    _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    _wake.set()
    if _thread is not None:
        _thread.join(timeout=2)
        _thread = None
