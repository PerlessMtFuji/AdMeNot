"""Nowy folder i nowy plik TXT na telefonie (spec §5.7).

Nic nie jest nadpisywane: istniejąca nazwa to `CreateError("exists")` (bez kopii obok). Folder:
`stat` (czy już jest) → `mkdir -p` → `stat` (czy to folder). TXT: `stat` celu → plik w `%TEMP%` → `push`
do `<folder>/.admenot-<12 hex>.part` → `mv -n` → `stat` obu: sukces tylko, gdy cel ma oczekiwany rozmiar,
a pliku tymczasowego już nie ma. Cel, który pojawił się w międzyczasie, zostaje nietknięty (`mv -n` nie
nadpisuje), a nasz plik tymczasowy jest usuwany. Folder z plikiem tymczasowym jest na liście na dysku
(`explorer_tmp`) od przed `push` do usunięcia pliku — po zabitym programie sprząta go `sweep_recorded`.
Bez nazw w logach.
"""

from __future__ import annotations

import contextlib
import os
import posixpath
import secrets
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from admenot.engine.adb.transport import AdbError
from admenot.engine.explorer.guard import (
    TMP_PREFIX,
    TMP_SUFFIX,
    ExplorerAdb,
    explorer_pusher,
    is_tmp_name,
)
from admenot.engine.explorer.queue import (
    _DENIED,
    forget_tmp_folder,
    read_tmp_folders,
    record_tmp_folder,
)
from admenot.engine.transfer.guard import STAT_TAIL, q, safe_target
from admenot.engine.transfer.pusher import Pusher

__all__ = ["CreateError", "make_folder", "make_text"]

NAME_MAX = 255  # bajtów UTF-8
_Key = Literal["exists", "bad_name", "denied", "offline"]


class CreateError(Exception):
    def __init__(self, key: _Key) -> None:
        super().__init__(key)
        self.key = key


def _check_name(name: str) -> None:
    if (not name or name in (".", "..") or "/" in name or "\n" in name or "\x00" in name
            or len(name.encode("utf-8")) > NAME_MAX):
        raise CreateError("bad_name")


def _join(parent: str, name: str) -> str:
    return safe_target(parent.rstrip("/") + "/" + name)


def _online(adb: ExplorerAdb) -> bool:
    try:
        return adb.run(["get-state"]).strip() == "device"
    except AdbError:
        return False


def _failure(adb: ExplorerAdb, exc: AdbError) -> CreateError:
    """Błąd adb → `offline` (odłączenie) albo `denied` (telefon odmówił; inna awaria też kończy się tu).
    Odłączenie rozstrzyga `get-state`, nie tekst błędu (folder „Mapy offline” to nie odłączenie)."""
    if not _online(adb):
        return CreateError("offline")
    return CreateError("denied")


def _stat(adb: ExplorerAdb, paths: list[str]) -> dict[str, tuple[bool, int]]:
    """Istniejące ścieżki → (czy folder, rozmiar). Brak pliku to linia błędu (`STAT_TAIL`);
    „Permission denied” przy `stat` → `CreateError("denied")`."""
    try:
        out = adb.shell("stat -c '%f|%s|%Y|%n' " + " ".join(q(p) for p in paths) + STAT_TAIL)
    except AdbError as exc:
        raise _failure(adb, exc) from exc
    found: dict[str, tuple[bool, int]] = {}
    for line in out.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4 and parts[1].isdigit() and parts[3] in paths:
            try:
                is_dir = int(parts[0], 16) & 0o170000 == 0o040000
            except ValueError:
                continue
            found[parts[3]] = (is_dir, int(parts[1]))
        elif "permission denied" in line.lower():
            raise CreateError("denied")
    return found


def make_folder(adb: ExplorerAdb, parent: str, name: str) -> str:
    """Tworzy `<parent>/<name>`; zwraca pełną ścieżkę nowego folderu."""
    _check_name(name)
    path = _join(parent, name)
    if _stat(adb, [path]):
        raise CreateError("exists")
    try:
        adb.shell(f"mkdir -p {q(path)}")
    except AdbError as exc:
        raise _failure(adb, exc) from exc
    made = _stat(adb, [path]).get(path)
    if made is None or not made[0]:
        raise CreateError("denied")
    return path


def make_text(adb: ExplorerAdb, pusher: Pusher, parent: str, name: str, text: str, *,
              token: Callable[[], str] = lambda: secrets.token_hex(6),
              tmp_dir: Path | None = None, temp_dir: Path | None = None) -> str:
    """Tworzy `<parent>/<name>[.txt]` z `text` (UTF-8 bez BOM, końce linii `\\n`); zwraca pełną ścieżkę.
    `tmp_dir` — gdzie leży lista folderów z plikami tymczasowymi, `temp_dir` — folder pliku lokalnego."""
    _check_name(name)
    if not name.lower().endswith(".txt"):
        name += ".txt"
    _check_name(name)  # rozszerzenie mogło przekroczyć limit
    target = _join(parent, name)
    folder = posixpath.dirname(target)
    if _stat(adb, [target]):
        raise CreateError("exists")
    data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    tmp = f"{folder}/{TMP_PREFIX}{token()}{TMP_SUFFIX}"
    if not is_tmp_name(posixpath.basename(tmp)):
        raise CreateError("denied")
    serial = adb.serial or "unknown"
    fd, local = tempfile.mkstemp(suffix=".txt", dir=temp_dir)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        listed = folder in read_tmp_folders(serial, directory=tmp_dir)
        record_tmp_folder(serial, folder, directory=tmp_dir)
        tmp_gone = False
        try:
            _push(adb, pusher, Path(local), tmp)
            tmp_gone = _commit(adb, tmp, target, len(data))
        finally:
            if not tmp_gone:
                tmp_gone = _rm_tmp(adb, tmp)
            if tmp_gone and not listed:
                forget_tmp_folder(serial, folder, directory=tmp_dir)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(local)
    return target


def _push(adb: ExplorerAdb, pusher: Pusher, local: Path, tmp: str) -> None:
    try:  # strażnik eksploratora: tylko nasz plik tymczasowy pod /sdcard/
        res = explorer_pusher(pusher).push([local], tmp, lambda: False, lambda: None)
    except AdbError as exc:
        raise _failure(adb, exc) from exc
    if res.rc != 0:
        text = "\n".join(res.lines).lower()
        if any(d in text for d in _DENIED):
            raise CreateError("denied")
        raise CreateError("offline" if not _online(adb) else "denied")


def _commit(adb: ExplorerAdb, tmp: str, target: str, size: int) -> bool:
    """`mv -n` i weryfikacja; zwraca True, gdy pliku tymczasowego już nie ma (przeniesiony)."""
    if _stat(adb, [tmp]).get(tmp, (True, -1))[1] != size:
        raise CreateError("denied")
    try:
        adb.shell(f"mv -n {q(tmp)} {q(target)}")
    except AdbError as exc:
        raise _failure(adb, exc) from exc
    found = _stat(adb, [tmp, target])
    if tmp not in found:
        if found.get(target) == (False, size):
            return True
        raise CreateError("denied")
    if target in found:  # cel pojawił się w trakcie: `mv -n` go nie ruszył
        raise CreateError("exists")
    raise CreateError("denied")


def _rm_tmp(adb: ExplorerAdb, tmp: str) -> bool:
    try:
        adb.shell(f"rm -f {q(tmp)}")
    except AdbError:
        return False
    return True
