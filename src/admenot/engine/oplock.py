"""Blokada operacji na telefonie wspólna dla procesów (okno, CLI, instalator).

`JobRunner` chroni tylko jedną instancję okna. Dwa procesy wykonujące to samo zlecenie mogłyby
nadpisać zapisany krok odwrotny (audyt 2026-10-11, BUG-06), a instalator zabić naprawę w toku
(REL-05). Blokada to plik obok dziennika, zablokowany przez system (zwalniany także, gdy proces
zginie): `locks/<skrót numeru seryjnego>.lock`.
"""

from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class DeviceBusy(Exception):
    """Inny proces wykonuje albo cofa zlecenie na tym telefonie."""

    def __init__(self, serial: str) -> None:
        super().__init__(serial)
        self.serial = serial


def lock_dir(journal_path: Path | str) -> Path:
    if str(journal_path) == ":memory:":
        return Path(os.environ.get("TEMP") or "/tmp") / "admenot-locks"
    return Path(journal_path).parent / "locks"


def lock_name(serial: str) -> str:
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()[:24] + ".lock"


def _try_lock(fd: int) -> bool:
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def device_lock(journal_path: Path | str, serial: str) -> Iterator[None]:
    """Wyłączność operacji na telefonie `serial`; DeviceBusy, gdy trzyma ją inny proces/wątek."""
    path = lock_dir(journal_path) / lock_name(serial)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if not _try_lock(fd):
            raise DeviceBusy(serial)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def operation_active(journal_path: Path | str) -> bool:
    """Czy jakiś proces wykonuje albo cofa teraz zlecenie (na dowolnym telefonie)."""
    for path in sorted(lock_dir(journal_path).glob("*.lock")):
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError:
            continue
        try:
            if not _try_lock(fd):
                return True
            _unlock(fd)
        finally:
            os.close(fd)
    return False
