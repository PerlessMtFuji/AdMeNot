from __future__ import annotations

import pytest

from admenot.engine.transfer.guard import ReadOnlyAdb, UnsafeCommand, assert_read_only, q


class Recorder:
    def __init__(self, serial: str | None = "S1") -> None:
        self.serial = serial
        self.calls: list[tuple[str, object]] = []

    def shell(self, command: str, timeout: float = 20.0) -> str:
        self.calls.append(("shell", command))
        return "ok"

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        self.calls.append(("run", args))
        return "ok"

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        self.calls.append(("run_bytes", args))
        return b"ok"

    def with_serial(self, serial: str) -> Recorder:
        return Recorder(serial)


def test_allowed_reads():
    assert_read_only("find -H '/sdcard/DCIM' -type f -exec stat -c '%s|%Y|%n' {} +")
    assert_read_only("stat -c '%s' " + q("/sdcard/a'b;rm -rf $(x)|.txt"))
    assert_read_only("content query --uri 'content://sms' --projection '_id:body'")
    assert_read_only("content read --uri content://mms/part/12")
    for cmd in ("getprop", "df -k /sdcard", "sha256sum '/sdcard/a'", "md5sum '/sdcard/a'", "ls /sdcard"):
        assert_read_only(cmd)


@pytest.mark.parametrize("bad", [
    "rm -rf /sdcard", "find /sdcard -delete", "find /sdcard -exec rm {} +",
    "find /sdcard -execdir sh {} +", "find /sdcard -fprint /sdcard/x",
    "content delete --uri content://sms", "content insert --uri content://sms",
    "ls; rm x", "ls $(rm x)", "ls `rm x`", "getprop > /sdcard/x", "ls && reboot",
    "ls 'unclosed", 'ls "$HOME"',
])
def test_blocked(bad):
    with pytest.raises(UnsafeCommand):
        assert_read_only(bad)


@pytest.mark.parametrize("bad", [
    "content read --uri content://sms/1",
    "content read --uri content://mms/part/abc",
    "content read --uri content://mms/part/1 --extra",
    "content read --uri content://mms/part/1/../2",
])
def test_content_read_only_mms_parts(bad):
    with pytest.raises(UnsafeCommand):
        assert_read_only(bad)


def test_readonly_adb_rejects_push():
    inner = Recorder()
    with pytest.raises(UnsafeCommand):
        ReadOnlyAdb(inner).run(["push", "a", "/sdcard/"])
    assert inner.calls == []


def test_readonly_adb_allows_shell_T_read():
    inner = Recorder()
    adb = ReadOnlyAdb(inner)
    cmd = "content read --uri content://mms/part/7"
    assert adb.run_bytes(["shell", "-T", cmd]) == b"ok"
    assert adb.run(["shell", "-T", "getprop"]) == "ok"
    assert adb.run(["get-state"]) == "ok"
    assert adb.shell("df -k") == "ok"
    assert [c[0] for c in inner.calls] == ["run_bytes", "run", "run", "shell"]


def test_readonly_adb_run_bytes_allows_exec_out_read_only():
    inner = Recorder()
    adb = ReadOnlyAdb(inner)
    assert adb.run_bytes(["exec-out", "content read --uri content://mms/part/7"]) == b"ok"
    with pytest.raises(UnsafeCommand):
        adb.run_bytes(["exec-out", "rm x"])
    with pytest.raises(UnsafeCommand):
        adb.run_bytes(["exec-out", "ls", "extra"])
    assert [c[0] for c in inner.calls] == ["run_bytes"]


def test_readonly_adb_rejects_other_host_and_unsafe_shell():
    adb = ReadOnlyAdb(Recorder())
    for args in (["shell", "ls"], ["exec-out", "ls"], ["install", "a.apk"], ["shell", "-T", "rm x"]):
        with pytest.raises(UnsafeCommand):
            adb.run(args)
    with pytest.raises(UnsafeCommand):
        adb.run_bytes(["get-state"])
    with pytest.raises(UnsafeCommand):
        adb.run_bytes(["shell", "-T", "rm x"])
    with pytest.raises(UnsafeCommand):
        adb.shell("rm x")


def test_readonly_adb_serial_mirrors_inner():
    adb = ReadOnlyAdb(Recorder("A"))
    assert adb.serial == "A"
    other = adb.with_serial("B")
    assert isinstance(other, ReadOnlyAdb) and other.serial == "B"
