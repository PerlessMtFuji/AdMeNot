"""Listowanie folderu na telefonie dla eksploratora plików: jedno `find … -exec stat`, bez ukrytych plików."""

from __future__ import annotations

import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from admenot.engine.adb.transport import AdbError
from admenot.engine.explorer.guard import ExplorerAdb
from admenot.engine.transfer.guard import CONTENT_TAIL, q

__all__ = ["Entry", "ListError", "ListResult", "folder_label", "list_dir", "locked_paths"]

LIST_TIMEOUT = 120.0
_SDCARD = "/sdcard"
_RECORD = re.compile(r"[0-9a-f]{1,8}\|[0-9]+\|-?[0-9]+\|/")
_LABELLED = re.compile(r"(?:^|/)Android/(media|data)/([^/]+)$")
_OFFLINE_KINDS = ("offline", "no_device", "unauthorized")


@dataclass(frozen=True)
class Entry:
    name: str
    path: str
    kind: Literal["dir", "file"]
    size: int
    mtime: int
    label: str | None
    locked: bool


@dataclass(frozen=True)
class ListResult:
    entries: list[Entry]
    skipped: int


class ListError(Exception):
    def __init__(self, kind: Literal["denied", "missing", "offline", "failed"]) -> None:
        super().__init__(kind)
        self.kind = kind


def locked_paths(sdk: int) -> frozenset[str]:
    """Kandydaci na foldery zablokowane przez Androida 11+ (`Android/data`, `Android/obb`).

    To tylko kandydaci: część telefonów (np. Android 12/13 z `adb shell`) je listuje — `list_dir` sprawdza to sondą."""
    if sdk >= 30:
        return frozenset({f"{_SDCARD}/Android/data", f"{_SDCARD}/Android/obb"})
    return frozenset()


def folder_label(path: str, apps: Mapping[str, str]) -> str | None:
    """Ludzka nazwa folderu aplikacji: `Android/media|data/<pakiet>` -> nazwa z `apps`, WhatsApp zawsze „WhatsApp”."""
    m = _LABELLED.search(path.rstrip("/"))
    if m is None:
        return None
    area, package = m.groups()
    if area == "media" and package == "com.whatsapp":
        return "WhatsApp"
    return apps.get(package)


def _list_error(exc: AdbError) -> ListError:
    if exc.kind in _OFFLINE_KINDS:
        return ListError("offline")
    low = exc.message.lower()
    if "permission denied" in low:
        return ListError("denied")
    if "no such file or directory" in low:
        return ListError("missing")
    return ListError("failed")


def _is_denied(adb: ExplorerAdb, folder: str) -> bool:
    """Sonda `ls '<folder>/' 2>&1`: telefon odmawia dostępu (kod 1 albo komunikat na stdout)."""
    try:
        out = adb.shell(f"ls {q(folder + '/')}{CONTENT_TAIL}")
    except AdbError as exc:
        return "permission denied" in exc.message.lower()
    return "permission denied" in out.lower()


def list_dir(adb: ExplorerAdb, path: str, *, sdk: int = 0, apps: Mapping[str, str] | None = None) -> ListResult:
    """Zawartość folderu `path` (bez ukrytych). Nazwy z nową linią są pomijane i liczone w `skipped`."""
    base = path.rstrip("/")
    try:
        out = adb.shell(
            f"find {q(base + '/')} -mindepth 1 -maxdepth 1 -exec stat -c '%f|%s|%Y|%n' {{}} +",
            timeout=LIST_TIMEOUT)
    except AdbError as exc:
        raise _list_error(exc) from exc
    # Rekord zaczyna się od `tryb|rozmiar|mtime|<folder>/`; reszta to ciąg dalszy nazwy z nową linią.
    records: list[list[str]] = []
    for line in out.split("\n"):
        if _RECORD.match(line) and line.split("|", 3)[3].startswith(base + "/"):
            records.append([line])
        elif records and line:
            records[-1].append(line)
    candidates = locked_paths(sdk)
    labels = apps or {}
    entries: list[Entry] = []
    skipped = 0
    for rec in records:
        if len(rec) > 1:
            skipped += 1
            continue
        mode_s, size_s, mtime_s, full = rec[0].split("|", 3)
        name = full[len(base) + 1:]
        if "/" in name or name.startswith("."):
            continue
        is_dir = stat.S_ISDIR(int(mode_s, 16))
        child = f"{base}/{name}"
        locked = is_dir and child in candidates and _is_denied(adb, child)
        entries.append(Entry(name, child, "dir" if is_dir else "file", int(size_s), int(mtime_s),
                             folder_label(child, labels) if is_dir else None, locked))
    return ListResult(entries, skipped)
