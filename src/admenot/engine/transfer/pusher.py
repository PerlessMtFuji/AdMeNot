"""Strumieniowy `adb push` na nowy telefon z możliwością przerwania."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from admenot.engine.adb.sessionlog import SessionLogAdb
from admenot.engine.transfer.guard import safe_target
from admenot.engine.transfer.puller import PullResult, run_stream


class Pusher(Protocol):
    def push(self, locals_: list[Path], remote: str, should_stop: Callable[[], bool],
             tick: Callable[[], None]) -> PullResult: ...


class RealPusher:
    """`adb -s <serial> push <lokalne bezwzględne…> <cel>`.

    `remote` to katalog z `/` na końcu (wiele plików) albo pełna ścieżka pliku (jeden plik, inna nazwa).
    """

    def __init__(self, adb_path: str, serial: str, log: SessionLogAdb | None = None) -> None:
        self.adb_path = adb_path
        self.serial = serial
        self.log = log

    def push(self, locals_: list[Path], remote: str, should_stop: Callable[[], bool],
             tick: Callable[[], None]) -> PullResult:
        target = safe_target(remote)
        # bezwzględne ścieżki: żadna nie zaczyna się od `-`, więc adb nie weźmie nazwy pliku za opcję
        args = ["push", *(str(p.resolve()) for p in locals_), target]
        if self.log is not None:  # w logu sesji tylko liczba plików — bez nazw i folderów klienta
            self.log.note(f"host:push <{len(locals_)} files>")
        return run_stream(self.adb_path, self.serial, args, should_stop, tick)
