"""Strumieniowy `adb pull` z możliwością przerwania."""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from admenot.engine.adb.sessionlog import SessionLogAdb

_CREATE_NO_WINDOW = 0x08000000
TICK_SECONDS = 0.5
_LOG_REMOTES = 3  # w logu sesji tylko początek listy — paczka ma ich tysiące
_JOIN = 2.0


@dataclass(frozen=True)
class PullResult:
    rc: int
    lines: list[str]
    stopped: bool


class Puller(Protocol):
    def pull(self, remotes: list[str], target: Path, should_stop: Callable[[], bool],
             tick: Callable[[], None]) -> PullResult: ...


class RealPuller:
    """`adb -s <serial> pull -a -Z <remotes…> <target>`; `tick()` co 0,5 s, przerwanie na żądanie."""

    def __init__(self, adb_path: str, serial: str, log: SessionLogAdb | None = None) -> None:
        self.adb_path = adb_path
        self.serial = serial
        self.log = log

    def pull(self, remotes: list[str], target: Path, should_stop: Callable[[], bool],
             tick: Callable[[], None]) -> PullResult:
        args = ["pull", "-a", "-Z", *remotes, str(target)]
        if self.log is not None:
            shown = " ".join(remotes[:_LOG_REMOTES])
            more = f" … (+{len(remotes) - _LOG_REMOTES})" if len(remotes) > _LOG_REMOTES else ""
            self.log.note(f"host:pull -a -Z {shown}{more} {target}")
        flags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.Popen([self.adb_path, "-s", self.serial, *args], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        lines: list[str] = []
        lock = threading.Lock()

        def read() -> None:
            assert proc.stdout is not None
            for raw in iter(proc.stdout.readline, b""):
                text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if text:
                    with lock:
                        lines.append(text)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        stopped = False
        while True:
            try:
                proc.wait(timeout=TICK_SECONDS)
                break
            except subprocess.TimeoutExpired:
                tick()
                if should_stop():
                    stopped = True
                    proc.terminate()
                    try:
                        proc.wait(timeout=_JOIN)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    break
        reader.join(_JOIN)
        with lock:
            return PullResult(proc.returncode, list(lines), stopped)
