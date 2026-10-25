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
from admenot.engine.adb.transport import AdbError

_CREATE_NO_WINDOW = 0x08000000
TICK_SECONDS = 0.5
_JOIN = 2.0
_JOIN_STOPPED = 0.3


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Zatrzymuje proces razem z potomkami (na Windows `taskkill /T`), by nic nie pisało dalej."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                       stdin=subprocess.DEVNULL, creationflags=_CREATE_NO_WINDOW, check=False)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=_JOIN)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


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
        if self.log is not None:  # w logu sesji tylko liczba plików — bez nazw plików klienta
            self.log.note(f"host:pull -a -Z <{len(remotes)} files>")
        flags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            proc = subprocess.Popen([self.adb_path, "-s", self.serial, *args], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        except OSError as exc:
            raise AdbError("adb_missing", str(exc)) from exc
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
        try:
            while True:
                try:
                    proc.wait(timeout=TICK_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    tick()
                    if should_stop():
                        stopped = True
                        break
        finally:
            if proc.poll() is None:  # także gdy tick()/should_stop() rzuciły wyjątek
                _kill_tree(proc)
        reader.join(_JOIN_STOPPED if stopped else _JOIN)
        with lock:
            return PullResult(proc.returncode, list(lines), stopped)
