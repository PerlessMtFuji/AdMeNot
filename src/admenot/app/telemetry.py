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
from admenot.engine.settings import Settings, effective_lang, load_settings, save_internal
from admenot.net import client

ENDPOINT = "/api/v1/telemetry"
FORMAT = 1
BATCH = 100
MAX_BYTES = 1024 * 1024
KEEP = timedelta(days=30)
FIRST = 30.0  # s po starcie
PERIOD = 6 * 3600.0
MIN_GAP = 600.0  # po `record` najwyżej raz na 10 min

Post = Callable[[str, dict[str, Any]], dict[str, Any]]
Delete = Callable[[str], dict[str, Any]]
Now = Callable[[], datetime]

_lock = threading.Lock()  # plik kolejki i lista do usunięcia
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), "utf-8")
    tmp.replace(path)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"installs": ids}), "utf-8")
    tmp.replace(path)


def delete_pending() -> bool:
    with _lock:
        return bool(_read_deletes())


# --- zgoda ----------------------------------------------------------------------------------

def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_consent(telemetry: bool, packages: bool, now: datetime) -> Settings:
    """Spec §4.2: włączenie tworzy ID (raz), wyłączenie kasuje kolejkę i planuje usunięcie z serwera."""
    current = load_settings()
    packages = packages and telemetry
    changes: dict[str, Any] = {"telemetry": telemetry, "telemetry_packages": packages,
                               "telemetry_at": _stamp(now)}
    if telemetry:
        changes["telemetry_id"] = current.telemetry_id or str(uuid.uuid4())
    else:
        changes["telemetry_id"] = None
    with _lock:
        settings = save_internal(changes)  # najpierw ustawienia: SettingsTooNew nic nie rusza
        if not telemetry:
            _write_events([])
            if current.telemetry_id:
                _write_deletes([*_read_deletes(), current.telemetry_id])
        elif not packages and current.telemetry_packages:
            _write_events([{**e, "packages": None} if "packages" in e else e
                           for e in _read_events()])
    _wake.set()
    return settings


# --- zapis ----------------------------------------------------------------------------------

def record(type_: str, build: Callable[[bool], dict[str, Any]], now: Now | None = None) -> None:
    try:
        settings = load_settings()
        if not settings.telemetry or not settings.telemetry_id:
            return
        when = (now or _utc_now)()
        event = {**common(settings.telemetry_id, type_, when, effective_lang(settings)),
                 **build(settings.telemetry_packages)}
        with _lock:
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


def _send_deletes(delete: Delete) -> None:
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
            _write_deletes([i for i in _read_deletes() if i not in done])


def _remove(sent: list[dict[str, Any]]) -> None:
    with _lock:
        rest = _read_events()
        for event in sent:  # nowe wpisy mogły dojść w trakcie wysyłki — usuwamy tylko wysłane
            with contextlib.suppress(ValueError):
                rest.remove(event)
        _write_events(rest)


def send_pending(post: Post | None = None, delete: Delete | None = None,
                 stop: threading.Event | None = None, now: Now | None = None) -> None:
    post = post or client.post_json
    try:
        _send_deletes(delete or client.delete)
        while stop is None or not stop.is_set():
            settings = load_settings()
            with _lock:
                events = _read_events()
                if not settings.telemetry or not settings.telemetry_id:
                    return
                mine = [e for e in events if e["install"] == settings.telemetry_id]
                if len(mine) != len(events):  # pozostałość po cofniętej zgodzie — nie wychodzi
                    _write_events(_trim(mine, (now or _utc_now)()))
            batch = mine[:BATCH]
            if not batch:
                return
            try:
                post(ENDPOINT, {"format": FORMAT, "events": batch})
            except client.BackendError as exc:
                if _waiting(exc):
                    return
                _log(exc)  # 400: zła paczka nie może blokować kolejki na zawsze
            _remove(batch)
    except Exception as exc:  # noqa: BLE001
        _log(exc)


def _loop(wake: threading.Event, stop: threading.Event,
          clock: Callable[[], float] = time.monotonic) -> None:
    delay = FIRST
    last: float | None = None
    while True:
        wake.wait(delay)
        wake.clear()
        if stop.is_set():
            return
        if last is not None and clock() - last < MIN_GAP:
            delay = MIN_GAP - (clock() - last)
            continue
        last = clock()
        send_pending(stop=stop)
        delay = PERIOD


def start() -> None:
    """Wątek wysyłki (z `run_gui`); CLI nigdy niczego nie wysyła."""
    global _thread
    if _thread is not None:
        return
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
