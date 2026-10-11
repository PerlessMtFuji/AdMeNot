"""Transport ADB — jedyne miejsce, które uruchamia adb.exe."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import IO, Any, Literal, Protocol

from admenot.engine.tools import resolve_adb

AdbErrorKind = Literal[
    "adb_missing", "timeout", "unauthorized", "offline", "no_device", "command_failed"
]

_CREATE_NO_WINDOW = 0x08000000
# Limit wyjścia jednego polecenia: dumpsys dużego telefonu to dziesiątki MB, a wadliwy albo
# złośliwy wynik nie może zająć całej pamięci stanowiska (audyt 2026-10-11, PERF-03).
MAX_STDOUT = 128 * 1024 * 1024
MAX_STDERR = 1024 * 1024
_CHUNK = 64 * 1024
_JOIN = 5.0


class OutputTooLarge(Exception):
    """Polecenie wypisało więcej niż limit — proces zatrzymany przed odczytem reszty."""


def _pump(stream: IO[bytes], sink: list[bytes], cap: int, over: threading.Event) -> None:
    total = 0
    while chunk := stream.read1(_CHUNK):  # type: ignore[attr-defined]
        total += len(chunk)
        if total > cap:
            over.set()
            return
        sink.append(chunk)


def _stop(proc: subprocess.Popen[bytes], threads: list[threading.Thread]) -> None:
    proc.kill()
    proc.wait()
    for thread in threads:
        thread.join(_JOIN)


def _run_capped(cmd: list[str], *, stdin: Any, timeout: float, creationflags: int,
                limit: int = MAX_STDOUT) -> subprocess.CompletedProcess[bytes]:
    """`subprocess.run(capture_output=True)` z limitem bajtów wyjścia i czasu."""
    proc = subprocess.Popen(cmd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=creationflags)
    out: list[bytes] = []
    err: list[bytes] = []
    over = threading.Event()
    threads = [threading.Thread(target=_pump, args=(proc.stdout, out, limit, over), daemon=True),
               threading.Thread(target=_pump, args=(proc.stderr, err, MAX_STDERR, over), daemon=True)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    while True:
        try:
            proc.wait(timeout=0.05)
            break
        except subprocess.TimeoutExpired:
            if over.is_set():
                _stop(proc, threads)
                raise OutputTooLarge(" ".join(cmd[-2:])) from None
            if time.monotonic() > deadline:
                _stop(proc, threads)
                raise subprocess.TimeoutExpired(cmd, timeout) from None
    for thread in threads:
        thread.join(_JOIN)
    if over.is_set():
        raise OutputTooLarge(" ".join(cmd[-2:]))
    return subprocess.CompletedProcess(cmd, proc.returncode, b"".join(out), b"".join(err))


class AdbError(Exception):
    def __init__(self, kind: AdbErrorKind, message: str) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message


class AdbTransport(Protocol):
    serial: str | None

    def shell(self, command: str, timeout: float = 20.0) -> str: ...

    def run(self, args: list[str], timeout: float = 20.0) -> str: ...

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes: ...

    def with_serial(self, serial: str) -> AdbTransport: ...


def classify_error(text: str) -> AdbError:
    low = text.lower()
    if "unauthorized" in low:
        kind: AdbErrorKind = "unauthorized"
    elif "offline" in low:
        kind = "offline"
    elif "no devices" in low or ("device" in low and "not found" in low):
        kind = "no_device"
    else:
        kind = "command_failed"
    return AdbError(kind, text.strip())


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").replace("\r\n", "\n")


class RealAdb:
    def __init__(self, serial: str | None = None, adb_path: str | None = None) -> None:
        self.serial = serial
        self.adb_path = resolve_adb(adb_path).path

    def with_serial(self, serial: str) -> RealAdb:
        return RealAdb(serial=serial, adb_path=self.adb_path)

    def _exec(self, args: list[str], timeout: float) -> bytes:
        if not self.adb_path:
            raise AdbError("adb_missing", "adb executable not found")
        cmd = [self.adb_path] + (["-s", self.serial] if self.serial else []) + list(args)
        flags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            # stdin=DEVNULL: `adb shell` przekazuje stdin na telefon i zjadałby wpisy z konsoli.
            proc = _run_capped(cmd, stdin=subprocess.DEVNULL, timeout=timeout, creationflags=flags)
        except subprocess.TimeoutExpired as exc:
            raise AdbError("timeout", f"{' '.join(args)} (>{timeout}s)") from exc
        except OutputTooLarge as exc:
            raise AdbError("command_failed", f"{' '.join(args)}: output over the limit") from exc
        except OSError as exc:
            raise AdbError("adb_missing", str(exc)) from exc
        if proc.returncode != 0:
            raise classify_error(_decode(proc.stderr) or _decode(proc.stdout))
        return proc.stdout

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        return _decode(self._exec(args, timeout))

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        """Wyjście bez dekodowania (np. PNG z `exec-out screencap -p`)."""
        return self._exec(args, timeout)

    def shell(self, command: str, timeout: float = 20.0) -> str:
        return self.run(["shell", command], timeout=timeout)
