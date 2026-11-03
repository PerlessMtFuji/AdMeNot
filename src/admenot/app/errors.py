"""Błędy dla UI: klucz (tłumaczony w UI) + szczegóły. Nieoczekiwane wyjątki trafiają do logu."""

from __future__ import annotations

import functools
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from admenot.app import crash
from admenot.engine.actions.errors import ActionError
from admenot.engine.adb.transport import AdbError
from admenot.engine.journal.db import JournalTooNew
from admenot.engine.oplock import DeviceBusy
from admenot.engine.paths import logs_dir
from admenot.engine.settings import SettingsTooNew

_ADB_KEYS = {"adb_missing": "adb_missing", "unauthorized": "unauthorized", "offline": "offline",
             "no_device": "disconnected", "timeout": "timeout"}


class AppError(Exception):
    def __init__(self, key: str, message: str = "", **extra: Any) -> None:
        super().__init__(message or key)
        self.key = key
        self.message = message
        self.extra = extra


def error_payload(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, AppError):
        return {"key": exc.key, "message": exc.message, **exc.extra}
    if isinstance(exc, DeviceBusy):
        return {"key": "device_busy", "message": exc.serial}
    if isinstance(exc, (SettingsTooNew, JournalTooNew)):
        return {"key": "data_too_new", "message": str(exc)}
    if isinstance(exc, AdbError):
        return {"key": _ADB_KEYS.get(exc.kind, "adb_error"), "message": exc.message}
    if isinstance(exc, ActionError):
        return {"key": exc.key if exc.uncertain else "action_error",
                "message": exc.detail or exc.key}
    if isinstance(exc, ValueError):
        return {"key": "bad_request", "message": str(exc)}
    return {"key": "internal", "message": f"{type(exc).__name__}: {exc}"}


def log_exception(exc: BaseException, scrub: Callable[[str], str] | None = None) -> Path:
    """Traceback do `app-<dzień>.log`; `scrub` czyści tekst przed zapisem (np. ścieżki plików
    klienta przy błędach kopii danych)."""
    path = logs_dir() / f"app-{datetime.now():%Y-%m-%d}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(traceback.format_exception(exc))
    if scrub is not None:
        text = scrub(text)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{text}\n")
    return path


def report_error(exc: BaseException, context: dict[str, Any] | None = None,
                 scrub: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Payload błędu dla UI. Log i raport awarii to dodatki: pełny dysk albo brak uprawnień
    nie może zamienić pierwotnej przyczyny w drugi wyjątek (audyt 2026-10-11, EDGE-02).
    `scrub` czyści wpis w lokalnym logu (np. ścieżki plików klienta)."""
    payload = error_payload(exc)
    if payload["key"] == "internal":
        try:
            payload["log"] = str(log_exception(exc) if scrub is None else log_exception(exc, scrub=scrub))
        except OSError:
            payload["log_failed"] = True
        try:
            crash_id = crash.capture(exc, context=context)
        except Exception:  # noqa: BLE001 — zgłoszenie błędu nie może samo zawieść
            crash_id = None
        if crash_id:
            payload["crash"] = crash_id
    return payload


def bridge(method: Callable[..., dict[str, Any]], *,
           scrub: Callable[[str], str] | None = None) -> Callable[..., dict[str, Any]]:
    """Metoda mostu dla JS: wyjątek nigdy nie leci do okna — wynik to `{"error": payload}`.
    `scrub` czyści wpis nieoczekiwanego błędu w lokalnym logu (`report_error`)."""
    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — do JS nigdy nie leci wyjątek
            return {"error": report_error(exc, {"call": method.__name__}, scrub=scrub)}

    return wrapper
