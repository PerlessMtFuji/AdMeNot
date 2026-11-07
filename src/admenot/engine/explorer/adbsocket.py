"""Polecenia i pliki przez lokalny serwer adb: gniazdo zamiast procesu `adb.exe`.

Nowy proces `adb` na Windows to ok. 100 ms na polecenie, a `exec:` z `dd` daje ok. 25 MB/s; gniazdo to 15 ms,
a `sync:` — pełne 130 MB/s kabla (pomiar 2026-11-06, Vivo V2405A). Tu jest tylko odczyt plików (`RECV`) i `shell`
z tym samym strażnikiem co dotąd: `SocketShell` siedzi pod `ExplorerAdb`, a `sync_stream` sam sprawdza ścieżkę.
Serwer adb nieosiągalny albo telefon bez `shell_v2` — wywołujący wraca do procesu `adb`.
"""

from __future__ import annotations

import logging
import os
import socket
import struct
import time
from collections.abc import Callable
from pathlib import Path

from admenot.engine.adb.transport import (
    MAX_STDERR,
    MAX_STDOUT,
    AdbError,
    AdbTransport,
    RealAdb,
    _decode,
    classify_error,
)
from admenot.engine.explorer.guard import safe_read_path
from admenot.engine.transfer.puller import TICK_SECONDS, Puller, PullResult, RealPuller

__all__ = ["AdbRefused", "SocketShell", "SyncFailed", "SyncPuller", "SyncStream", "adb_server_port", "fast_puller",
           "fast_shell", "socket_stream", "sync_stream"]

_LOG = logging.getLogger(__name__)
_ADB_PORT = 5037
TIMEOUT = 30.0  # s: telefon, który przestał odpowiadać, nie może trzymać wątku bez końca
_RCVBUF = 1024 * 1024  # bez tego `sync:` traci połowę prędkości
_WRITE_BUFFER = 1024 * 1024
_READ = 1024 * 1024
_STDOUT, _STDERR, _EXIT = 1, 2, 3  # pakiety `shell,v2`


class AdbRefused(ConnectionError):
    """Serwer adb odmówił (`FAIL`); `message` — jego powód."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SyncFailed(OSError):
    """Telefon odmówił odczytu pliku (`FAIL` usługi `sync:`), np. brak pliku albo brak dostępu."""


def adb_server_port() -> int:
    try:
        return int(os.environ.get("ANDROID_ADB_SERVER_PORT", ""))
    except ValueError:
        return _ADB_PORT


def _exact(sock: socket.socket, n: int) -> bytes:
    out = bytearray()
    while len(out) < n:
        chunk = sock.recv(n - len(out))
        if not chunk:
            raise ConnectionError("adb connection closed")
        out += chunk
    return bytes(out)


def _request(sock: socket.socket, message: str) -> None:
    data = message.encode()
    sock.sendall(b"%04x" % len(data) + data)
    status = _exact(sock, 4)
    if status == b"OKAY":
        return
    try:
        reason = _exact(sock, int(_exact(sock, 4), 16)).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        reason = ""
    raise AdbRefused(reason or "adb server refused the request")


def _connect(port: int, timeout: float, rcvbuf: int | None = None) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if rcvbuf is not None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
    except OSError:
        sock.close()
        raise
    return sock


def _service(port: int, serial: str, service: str, timeout: float = TIMEOUT,
             rcvbuf: int | None = None) -> socket.socket:
    sock = _connect(port, timeout, rcvbuf)
    try:
        _request(sock, f"host:transport:{serial}")
        _request(sock, service)
    except OSError:
        sock.close()
        raise
    return sock


class _SocketStream:
    """Wyjście polecenia na telefonie prosto z serwera adb. Zamknięcie gniazda kończy `dd` na telefonie, bez
    `taskkill`: na Windows sam `_kill_tree` trwał 0,5 s i to on, nie odczyt, spowalniał miniatury i przewijanie."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def read(self, n: int, /) -> bytes:
        return self._sock.recv(n)

    def close(self) -> None:
        self._sock.close()


def socket_stream(port: int, serial: str, command: str) -> _SocketStream:
    """`exec:` przez lokalny serwer adb, bez nowego procesu; OSError — wywołujący wraca do `adb exec-out`."""
    return _SocketStream(_service(port, serial, f"exec:{command}"))


class SyncStream:
    """Plik z telefonu od początku, protokołem `adb pull`. `read` oddaje b"" na końcu pliku; zamknięcie gniazda
    w połowie przerywa odczyt, bez czytania reszty."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._left = 0
        self._done = False
        self._next()

    def _next(self) -> None:
        head = _exact(self._sock, 8)
        tag, size = head[:4], struct.unpack("<I", head[4:])[0]
        if tag == b"DATA":
            self._left = size
        elif tag == b"DONE":
            self._done = True
        elif tag == b"FAIL":
            raise SyncFailed(_exact(self._sock, size).decode("utf-8", errors="replace"))
        else:
            raise ConnectionError("unexpected adb sync reply")

    def read(self, n: int, /) -> bytes:
        if self._left == 0 and not self._done:
            self._next()
        if self._done:
            return b""
        chunk = self._sock.recv(min(n, self._left))
        if not chunk:
            raise ConnectionError("adb connection closed")
        self._left -= len(chunk)
        return chunk

    def close(self) -> None:
        self._sock.close()


def sync_stream(port: int, serial: str, path: str) -> SyncStream:
    """Odczyt pliku spod `/sdcard/`. `SyncFailed` — telefon odmówił; inny OSError — serwer adb nieosiągalny."""
    data = safe_read_path(path).encode()
    sock = _service(port, serial, "sync:", rcvbuf=_RCVBUF)
    try:
        sock.sendall(b"RECV" + struct.pack("<I", len(data)) + data)
        return SyncStream(sock)
    except BaseException:
        sock.close()
        raise


class SocketShell:
    """`AdbTransport`, którego `shell` idzie usługą `shell,v2` (osobno wyjście, błędy i kod wyjścia, jak `adb shell`);
    reszta i wszystko, czego gniazdo nie umie, idzie przez `inner`."""

    def __init__(self, inner: AdbTransport, port: int | None = None) -> None:
        self.inner = inner
        self.serial = inner.serial
        self._port = adb_server_port() if port is None else port
        self._v2 = True

    def with_serial(self, serial: str) -> SocketShell:
        return SocketShell(self.inner.with_serial(serial), self._port)

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        return self.inner.run(args, timeout=timeout)

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        return self.inner.run_bytes(args, timeout=timeout)

    def shell(self, command: str, timeout: float = 20.0) -> str:
        if not self._v2 or self.serial is None:
            return self.inner.shell(command, timeout=timeout)
        try:
            sock = _connect(self._port, timeout)
        except OSError:  # serwer adb nie działa: uruchomi go proces
            return self.inner.shell(command, timeout=timeout)
        try:
            try:
                _request(sock, f"host:transport:{self.serial}")
            except AdbRefused as exc:  # telefon odłączony, offline, bez zgody
                raise classify_error(exc.message) from None
            try:
                _request(sock, "shell,v2,raw:" + command)
            except AdbRefused:  # Android bez `shell_v2`
                self._v2 = False
                return self.inner.shell(command, timeout=timeout)
            return self._collect(sock, command, timeout)
        except TimeoutError as exc:
            raise AdbError("timeout", f"shell {command} (>{timeout}s)") from exc
        except OSError as exc:
            raise AdbError("command_failed", f"shell {command}: {exc}") from exc
        finally:
            sock.close()

    @staticmethod
    def _collect(sock: socket.socket, command: str, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        out = bytearray()
        err = bytearray()
        while True:
            sock.settimeout(max(0.001, deadline - time.monotonic()))
            head = _exact(sock, 5)
            data = _exact(sock, struct.unpack("<I", head[1:])[0])
            if head[0] == _STDOUT:
                out += data
                if len(out) > MAX_STDOUT:
                    raise AdbError("command_failed", f"shell {command}: output over the limit")
            elif head[0] == _STDERR and len(err) < MAX_STDERR:
                err += data
            elif head[0] == _EXIT:
                if data[:1] != b"\0":
                    raise classify_error(_decode(bytes(err)) or _decode(bytes(out)))
                return _decode(bytes(out))


def fast_shell(inner: AdbTransport) -> AdbTransport:
    """`SocketShell` nad prawdziwym adb; atrapa w testach zostaje bez zmian."""
    return SocketShell(inner) if isinstance(inner, RealAdb) else inner


class SyncPuller:
    """`Puller` jednego pliku przez `sync:`: bez procesu na każdy plik, co przy małych plikach kosztowało więcej niż
    sama kopia. Serwer adb nieosiągalny — `inner`."""

    def __init__(self, inner: Puller, serial: str, port: int | None = None,
                 note: Callable[[str], None] | None = None) -> None:
        self.inner = inner
        self.serial = serial
        self._port = adb_server_port() if port is None else port
        self._note = note

    def pull(self, remotes: list[str], target: Path, should_stop: Callable[[], bool],
             tick: Callable[[], None]) -> PullResult:
        if len(remotes) != 1:
            return self.inner.pull(remotes, target, should_stop, tick)
        try:
            stream = sync_stream(self._port, self.serial, remotes[0])
        except SyncFailed as exc:
            return PullResult(1, [f"adb: error: {exc}"], False)
        except OSError:
            _LOG.info("adb server socket unavailable, using adb pull")
            return self.inner.pull(remotes, target, should_stop, tick)
        if self._note is not None:  # w logu sesji tylko liczba plików — bez nazw plików klienta
            self._note("host:sync pull <1 files>")
        last = time.monotonic()
        try:
            with open(target, "wb", buffering=_WRITE_BUFFER) as out:
                while chunk := stream.read(_READ):
                    out.write(chunk)
                    if should_stop():
                        return PullResult(0, [], True)
                    if (now := time.monotonic()) - last >= TICK_SECONDS:
                        last = now
                        out.flush()  # postęp zadania to rozmiar pliku na dysku
                        tick()
        except (ConnectionError, TimeoutError, SyncFailed) as exc:  # kabel: kolejka sprawdza, czy telefon jest
            return PullResult(1, [f"adb: error: {exc}"], False)
        finally:
            stream.close()
        return PullResult(0, [], False)


def fast_puller(inner: Puller, serial: str) -> Puller:
    """`SyncPuller` nad prawdziwym `adb pull`; atrapa w testach zostaje bez zmian."""
    if not isinstance(inner, RealPuller):
        return inner
    log = inner.log
    return SyncPuller(inner, serial, note=log.note if log is not None else None)
