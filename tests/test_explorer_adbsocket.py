"""Polecenia i pliki przez serwer adb (`explorer/adbsocket.py`) na atrapie serwera adb."""

from __future__ import annotations

import socket
import struct
import threading
from pathlib import Path

import pytest

from admenot.engine.adb.transport import AdbError, RealAdb
from admenot.engine.explorer.adbsocket import (
    SocketShell,
    SyncFailed,
    SyncPuller,
    fast_puller,
    fast_shell,
    sync_stream,
)
from admenot.engine.explorer.guard import UnsafeCommand
from admenot.engine.transfer.puller import PullResult, RealPuller


class Server:
    """Atrapa serwera adb: `host:transport:` i jedna usługa; `reply(conn)` odpowiada na usługę."""

    def __init__(self, reply=None, *, device_error: str | None = None, service_error: str | None = None) -> None:
        self.reply = reply
        self.device_error = device_error
        self.service_error = service_error
        self.requests: list[str] = []
        self.received = b""
        self.closed = threading.Event()
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    @staticmethod
    def _read(conn: socket.socket, n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = conn.recv(n - len(out))
            if not chunk:
                raise ConnectionError
            out += chunk
        return out

    def _ask(self, conn: socket.socket) -> str:
        message = self._read(conn, int(self._read(conn, 4), 16)).decode()
        self.requests.append(message)
        return message

    @staticmethod
    def _fail(conn: socket.socket, reason: str) -> None:
        conn.sendall(b"FAIL" + b"%04x" % len(reason) + reason.encode())

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                try:
                    self._ask(conn)
                    if self.device_error is not None:
                        self._fail(conn, self.device_error)
                        continue
                    conn.sendall(b"OKAY")
                    self._ask(conn)
                    if self.service_error is not None:
                        self._fail(conn, self.service_error)
                        continue
                    conn.sendall(b"OKAY")
                    if self.reply is not None:
                        self.reply(self, conn)
                    while conn.recv(4096):
                        pass
                except OSError:
                    pass
                self.closed.set()


def packet(kind: int, data: bytes) -> bytes:
    return bytes([kind]) + struct.pack("<I", len(data)) + data


def shell_reply(out: bytes = b"", err: bytes = b"", rc: int = 0):
    def reply(_server: Server, conn: socket.socket) -> None:
        conn.sendall((packet(1, out) if out else b"") + (packet(2, err) if err else b"") + packet(3, bytes([rc])))
        conn.close()
    return reply


class Inner:
    """`AdbTransport` procesu; zapisuje, co do niego trafiło."""

    serial = "SER1"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def shell(self, command: str, timeout: float = 20.0) -> str:
        self.calls.append(command)
        return "z procesu"

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        self.calls.append(" ".join(args))
        return "uruchomione"

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        return b""

    def with_serial(self, serial: str) -> Inner:
        return self


def test_shell_returns_stdout_through_the_server():
    server = Server(shell_reply("linia\r\nzażółć\n".encode()))
    inner = Inner()
    assert SocketShell(inner, server.port).shell("echo x") == "linia\nzażółć\n"
    assert server.requests == ["host:transport:SER1", "shell,v2,raw:echo x"]
    assert inner.calls == []


def test_shell_nonzero_exit_raises_like_the_process_with_stderr_first():
    server = Server(shell_reply(b"czesciowo", b"stat: Permission denied\n", 1))
    with pytest.raises(AdbError) as caught:
        SocketShell(Inner(), server.port).shell("stat x")
    assert caught.value.kind == "command_failed" and "Permission denied" in caught.value.message


def test_shell_nonzero_exit_without_stderr_uses_stdout():
    server = Server(shell_reply(b"opis bledu", b"", 2))
    with pytest.raises(AdbError) as caught:
        SocketShell(Inner(), server.port).shell("x")
    assert "opis bledu" in caught.value.message


@pytest.mark.parametrize(("reason", "kind"), [("device 'SER1' not found", "no_device"), ("device offline", "offline"),
                                              ("device unauthorized.", "unauthorized")])
def test_shell_device_problems_keep_their_kind(reason, kind):
    inner = Inner()
    with pytest.raises(AdbError) as caught:
        SocketShell(inner, Server(device_error=reason).port).shell("x")
    assert caught.value.kind == kind and inner.calls == []


def test_shell_falls_back_to_the_process_when_the_server_is_down():
    sock = socket.create_server(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    inner = Inner()
    assert SocketShell(inner, port).shell("x") == "z procesu"
    assert inner.calls == ["x"]


def test_shell_without_shell_v2_uses_the_process_from_then_on():
    server = Server(service_error="closed")
    inner = Inner()
    shell = SocketShell(inner, server.port)
    assert shell.shell("a") == "z procesu"
    assert shell.shell("b") == "z procesu"
    assert inner.calls == ["a", "b"]
    assert server.requests.count("host:transport:SER1") == 1  # drugi raz już bez gniazda


def test_shell_connection_cut_mid_output_is_an_adb_error():
    def cut(_server: Server, conn: socket.socket) -> None:
        conn.sendall(packet(1, b"polowa"))
        conn.close()
    with pytest.raises(AdbError) as caught:
        SocketShell(Inner(), Server(cut).port).shell("x")
    assert caught.value.kind == "command_failed"


def test_shell_timeout_is_an_adb_error():
    server = Server(lambda _s, _c: None)
    with pytest.raises(AdbError) as caught:
        SocketShell(Inner(), server.port).shell("x", timeout=0.05)
    assert caught.value.kind == "timeout"


def test_run_and_run_bytes_stay_with_the_process():
    inner = Inner()
    assert SocketShell(inner, 1).run(["get-state"]) == "uruchomione"
    assert inner.calls == ["get-state"]


def test_fast_shell_wraps_only_the_real_adb():
    inner = Inner()
    assert fast_shell(inner) is inner
    assert isinstance(fast_shell(RealAdb(serial="S", adb_path="adb")), SocketShell)


def sync_reply(*chunks: bytes, end: bytes = b"DONE\0\0\0\0"):
    def reply(server: Server, conn: socket.socket) -> None:
        head = server._read(conn, 8)
        assert head[:4] == b"RECV"
        server.received = server._read(conn, struct.unpack("<I", head[4:])[0])
        for chunk in chunks:
            conn.sendall(b"DATA" + struct.pack("<I", len(chunk)) + chunk)
        conn.sendall(end)
    return reply


def fail_packet(text: bytes) -> bytes:
    return b"FAIL" + struct.pack("<I", len(text)) + text


def read_all(stream) -> bytes:
    out = bytearray()
    while chunk := stream.read(5):
        out += chunk
    return bytes(out)


def test_sync_stream_reads_the_whole_file_across_packets():
    server = Server(sync_reply(b"abcdefgh", b"ij"))
    stream = sync_stream(server.port, "SER1", "/sdcard/DCIM/ą b.jpg")
    assert read_all(stream) == b"abcdefghij"
    assert stream.read(5) == b""
    stream.close()
    assert server.requests == ["host:transport:SER1", "sync:"]
    assert server.received == "/sdcard/DCIM/ą b.jpg".encode()


def test_sync_stream_empty_file():
    stream = sync_stream(Server(sync_reply()).port, "SER1", "/sdcard/a")
    assert stream.read(5) == b""
    stream.close()


def test_sync_stream_closes_early_without_reading_the_rest():
    server = Server(sync_reply(b"x" * 1000))
    stream = sync_stream(server.port, "SER1", "/sdcard/a")
    assert stream.read(10)
    stream.close()
    assert server.closed.wait(2)


def test_sync_stream_refused_file_raises_sync_failed():
    server = Server(sync_reply(end=fail_packet(b"open failed: Permission denied")))
    with pytest.raises(SyncFailed, match="Permission denied"):
        sync_stream(server.port, "SER1", "/sdcard/Android/data/x")


def test_sync_stream_failure_mid_file_raises():
    stream = sync_stream(Server(sync_reply(b"abc", end=fail_packet(b"read failed"))).port, "SER1", "/sdcard/a")
    with pytest.raises(SyncFailed):
        read_all(stream)
    stream.close()


@pytest.mark.parametrize("path", ["/data/local/tmp/x", "/sdcard/../data/x", "/sdcard/a\nb"])
def test_sync_stream_only_reads_under_sdcard(path):
    server = Server(sync_reply(b"x"))
    with pytest.raises(UnsafeCommand):
        sync_stream(server.port, "SER1", path)
    assert server.requests == []


class InnerPuller:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def pull(self, remotes, target, should_stop, tick) -> PullResult:
        self.calls.append(remotes)
        return PullResult(0, ["z procesu"], False)


def pull(server: Server, target: Path, *, stop=lambda: False, tick=lambda: None, inner=None) -> PullResult:
    return SyncPuller(inner or InnerPuller(), "SER1", server.port).pull(["/sdcard/a.jpg"], target, stop, tick)


def test_sync_puller_writes_the_file(tmp_path):
    target = tmp_path / "a.jpg.part"
    notes: list[str] = []
    server = Server(sync_reply(b"abc", b"def"))
    result = SyncPuller(InnerPuller(), "SER1", server.port, note=notes.append).pull(
        ["/sdcard/a.jpg"], target, lambda: False, lambda: None)
    assert result == PullResult(0, [], False)
    assert target.read_bytes() == b"abcdef"
    assert notes == ["host:sync pull <1 files>"]  # bez nazwy pliku klienta


def test_sync_puller_stops_on_request(tmp_path):
    result = pull(Server(sync_reply(b"x" * 100_000)), tmp_path / "a", stop=lambda: True)
    assert result.stopped


def test_sync_puller_refused_file_keeps_the_reason_for_the_queue(tmp_path):
    result = pull(Server(sync_reply(end=fail_packet(b"open failed: Permission denied"))), tmp_path / "a")
    assert result.rc == 1 and "permission denied" in result.lines[0].lower() and not result.stopped


def test_sync_puller_cable_pull_is_a_failed_result_not_an_exception(tmp_path):
    def cut(server: Server, conn: socket.socket) -> None:
        server._read(conn, 8 + len("/sdcard/a.jpg"))
        conn.sendall(b"DATA" + struct.pack("<I", 100) + b"polowa")
        conn.close()
    result = pull(Server(cut), tmp_path / "a")
    assert result.rc == 1 and not result.stopped


def test_sync_puller_falls_back_to_adb_pull_when_the_server_is_down(tmp_path):
    sock = socket.create_server(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    inner = InnerPuller()
    result = SyncPuller(inner, "SER1", port).pull(["/sdcard/a"], tmp_path / "a", lambda: False, lambda: None)
    assert result.lines == ["z procesu"] and inner.calls == [["/sdcard/a"]]


def test_sync_puller_many_files_go_through_adb_pull(tmp_path):
    inner = InnerPuller()
    SyncPuller(inner, "SER1", 1).pull(["/sdcard/a", "/sdcard/b"], tmp_path, lambda: False, lambda: None)
    assert inner.calls == [["/sdcard/a", "/sdcard/b"]]


def test_fast_puller_wraps_only_the_real_puller():
    inner = InnerPuller()
    assert fast_puller(inner, "S") is inner
    assert isinstance(fast_puller(RealPuller("adb", "S"), "S"), SyncPuller)
