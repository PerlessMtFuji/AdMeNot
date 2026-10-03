"""Błędy dla UI: klucz (tłumaczony w UI) + szczegóły. Nieoczekiwane wyjątki trafiają do logu."""

from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from admenot.engine.actions.errors import ActionError
from admenot.engine.adb.transport import AdbError
from admenot.engine.paths import logs_dir

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
    if isinstance(exc, AdbError):
        return {"key": _ADB_KEYS.get(exc.kind, "adb_error"), "message": exc.message}
    if isinstance(exc, ActionError):
        return {"key": exc.key if exc.uncertain else "action_error",
                "message": exc.detail or exc.key}
    if isinstance(exc, ValueError):
        return {"key": "bad_request", "message": str(exc)}
    return {"key": "internal", "message": f"{type(exc).__name__}: {exc}"}


def log_exception(exc: BaseException) -> Path:
    path = logs_dir() / f"app-{datetime.now():%Y-%m-%d}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(traceback.format_exception(exc))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{text}\n")
    return path


def report_error(exc: BaseException) -> dict[str, Any]:
    payload = error_payload(exc)
    if payload["key"] == "internal":
        payload["log"] = str(log_exception(exc))
    return payload
