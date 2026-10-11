"""Usuwanie zleceń i starych danych (przegląd 2026-10-11; RODO: ograniczenie przechowywania).

Serwis przechowuje nazwiska klientów, IMEI, zrzuty ekranów ich telefonów i kopie APK. Zlecenie
usuwamy razem z jego plikami: ręcznie z Historii albo po okresie z ustawień (`retention_days`).
Kopię APK usuwamy tylko wtedy, gdy nie korzysta z niej inne zlecenie i ma kształt katalogu kopii —
ścieżka pochodzi z dziennika, więc nie kasujemy dowolnego katalogu, który się w nim znalazł.
"""

from __future__ import annotations

import contextlib
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from admenot.engine.actions.backup import COMPLETE
from admenot.engine.journal.db import Journal, Order
from admenot.engine.oplock import DeviceBusy, device_lock
from admenot.engine.paths import reports_dir
from admenot.engine.report.files import report_stem
from admenot.engine.screenshot import delete_shots

LOG_KEEP_DAYS = 90
_LOG_DAY = re.compile(r"^(?:app-)?(\d{4}-\d{2}-\d{2})\.log$")
_REPORT_SUFFIXES = (".html", ".pdf", ".tmp.pdf")


def _owned_backups(journal: Journal, order: Order) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for action in journal.actions(order.id):
        params = action.step.get("params") or {}
        found.update((params[key], action.package) for key in ("dir", "backup_dir") if params.get(key))
    return found


def _remove_backup(path: Path, package: str) -> None:
    if path.is_dir() and path.parent.name == package and (path / COMPLETE).is_file():
        shutil.rmtree(path, ignore_errors=True)


def delete_order(journal: Journal, order: Order) -> None:
    """Zlecenie z dziennika razem ze zrzutami, protokołem i nieużywanymi gdzie indziej kopiami APK.
    Wołać pod blokadą telefonu (`device_lock`)."""
    owned = _owned_backups(journal, order)
    shared = journal.backup_dirs(exclude=order.id)
    delete_shots(journal, [shot.id for shot in journal.screenshots(order.id)])
    journal.delete_order(order.id)
    stem = report_stem(order.number)
    for suffix in _REPORT_SUFFIXES:
        with contextlib.suppress(OSError):  # PDF otwarty w czytniku: zostaje, zlecenia już nie ma
            (reports_dir() / f"{stem}{suffix}").unlink(missing_ok=True)
    for path, package in owned:
        if path not in shared:
            _remove_backup(Path(path), package)


def purge(journal: Journal, now: datetime, days: int) -> list[str]:
    """Zlecenia starsze niż `days` dni bez kroków do dokończenia. Telefon zajęty przez inny
    proces (CLI) — zlecenie zostaje do następnego razu."""
    deleted: list[str] = []
    for order in journal.orders_before(now - timedelta(days=days)):
        if any(a.status == "pending" for a in journal.actions(order.id)):
            continue
        try:
            with device_lock(journal.path, order.device_serial):
                delete_order(journal, order)
        except DeviceBusy:
            continue
        deleted.append(order.number)
    return deleted


def prune_logs(directory: Path, now: datetime, days: int = LOG_KEEP_DAYS) -> int:
    """Dzienne logi sesji ADB (`RRRR-MM-DD.log`) i błędów okna (`app-RRRR-MM-DD.log`) starsze
    niż `days` dni. Innych plików nie ruszamy."""
    cutoff = (now - timedelta(days=days)).date()
    removed = 0
    try:
        paths = list(directory.iterdir())
    except OSError:
        return 0
    for path in paths:
        match = _LOG_DAY.match(path.name)
        if match is None:
            continue
        try:
            day = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if day >= cutoff:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
    return removed
