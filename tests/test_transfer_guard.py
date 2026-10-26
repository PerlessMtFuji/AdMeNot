from __future__ import annotations

import pytest

from admenot.engine.transfer.guard import (
    ApkReadAdb,
    ReadOnlyAdb,
    UnsafeCommand,
    assert_read_only,
    q,
)


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
    # akcja w cudzysłowie — powłoka zdejmie cudzysłowy, więc to nadal akcja find
    "find /sdcard '-delete'", 'find /sdcard "-delete"', "find /sdcard '-exec' rm {} +",
    "find /sdcard -exec 'rm' {} +", "find /sdcard '-fprint' /sdcard/x",
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


def test_apk_read_adb_allows_pm_path_and_apk_pull_of_its_package():
    inner = Recorder()
    adb = ApkReadAdb(inner, "com.example.app")
    adb.shell("pm path com.example.app")
    adb.run(["pull", "/data/app/~~x==/com.example.app-1/base.apk", "C:/tmp/base.apk"])
    adb.shell("sha256sum /data/app/x/base.apk")
    adb.run(["get-state"])
    assert inner.calls == [
        ("shell", "pm path com.example.app"),
        ("run", ["pull", "/data/app/~~x==/com.example.app-1/base.apk", "C:/tmp/base.apk"]),
        ("shell", "sha256sum /data/app/x/base.apk"),
        ("run", ["get-state"]),
    ]


@pytest.mark.parametrize("command", [
    "pm path com.other.app",
    "pm path com.example.app; rm -rf /sdcard",
    "pm uninstall com.example.app",
    "pm path com.example.app2",
])
def test_apk_read_adb_rejects_other_pm(command):
    inner = Recorder()
    with pytest.raises(UnsafeCommand):
        ApkReadAdb(inner, "com.example.app").shell(command)
    assert inner.calls == []


@pytest.mark.parametrize("args", [
    ["pull", "/sdcard/DCIM/a.jpg", "x"],
    ["pull", "relative/base.apk", "x"],
    ["pull", "/data/app/../../sdcard/base.apk", "x"],
    ["push", "evil.apk", "/data/local/tmp/base.apk"],
    ["install", "base.apk"],
])
def test_apk_read_adb_rejects_other_host_commands(args):
    inner = Recorder()
    with pytest.raises(UnsafeCommand):
        ApkReadAdb(inner, "com.example.app").run(args)
    assert inner.calls == []


def test_apk_read_adb_rejects_bad_package_name():
    with pytest.raises(UnsafeCommand):
        ApkReadAdb(Recorder(), "com.x; reboot")



def test_append_only_allows_mkdir_under_sdcard():
    from admenot.engine.transfer.guard import assert_append_only
    assert_append_only("mkdir -p '/sdcard/DCIM/Ą B' /sdcard/Download/x")
    assert_append_only("stat -c '%s|%Y|%n' /sdcard/a")
    assert_append_only("df -k /sdcard/")
    assert_append_only("getprop ro.build.version.sdk")


def test_append_only_rejects_mkdir_outside():
    from admenot.engine.transfer.guard import assert_append_only
    for cmd in ("mkdir -p /data/x", "mkdir -p /sdcard/../data", "mkdir /sdcard/x", "mkdir -p",
                "mkdir -p /sdcardx/a", "mkdir -p /sdcard/a /data/b"):
        with pytest.raises(UnsafeCommand):
            assert_append_only(cmd)


def test_append_only_rejects_rm_mv():
    from admenot.engine.transfer.guard import assert_append_only
    for cmd in ("rm /sdcard/a", "mv /sdcard/a /sdcard/b", "stat /sdcard/a; rm x", "cp /sdcard/a /sdcard/b",
                "find /sdcard -delete"):
        with pytest.raises(UnsafeCommand):
            assert_append_only(cmd)


def test_append_only_scan_volume_exact():
    from admenot.engine.transfer.guard import assert_append_only
    assert_append_only("content call --uri content://media --method scan_volume --arg external_primary")
    for cmd in ("content call --uri content://media --method other --arg external_primary",
                "content call --uri content://media --method scan_volume --arg internal",
                "content insert --uri content://media --bind a:s:b",
                "content query --uri content://sms"):
        with pytest.raises(UnsafeCommand):
            assert_append_only(cmd)


def test_safe_target():
    from admenot.engine.transfer.guard import safe_target
    assert safe_target("/sdcard/DCIM/a.jpg") == "/sdcard/DCIM/a.jpg"
    for bad in ("/data/a", "/sdcard/../x", "/sdcard/a\nb", "sdcard/a", "/sdcardx/a"):
        with pytest.raises(UnsafeCommand):
            safe_target(bad)


_NEWLINE_PROBES = ["ls /sdcard\nrm -rf /sdcard", "stat /sdcard/a\nreboot", "df -k\nsettings put global x 1",
                   "getprop\nam start x", "ls /sdcard\rrm -rf /sdcard", "ls /sdcard\r\nreboot"]


def test_newline_injection_rejected_by_both_guards():
    from admenot.engine.transfer.guard import assert_append_only
    for cmd in _NEWLINE_PROBES:
        with pytest.raises(UnsafeCommand):
            assert_append_only(cmd)
        with pytest.raises(UnsafeCommand):
            assert_read_only(cmd)
    assert_read_only("stat -c '%s|%Y|%n' '/sdcard/a b'")  # w apostrofach nadal w porządku


def test_append_only_rejects_odd_mkdir_forms():
    from admenot.engine.transfer.guard import assert_append_only
    for cmd in ('"mkdir" -p /sdcard/x', "mkdir -p -m 777 /sdcard/x", 'mkdir -p "/sdcard/$(reboot)"'):
        with pytest.raises(UnsafeCommand):
            assert_append_only(cmd)


def test_append_only_adb_wrapper():
    from admenot.engine.transfer.guard import AppendOnlyAdb
    rec = Recorder()
    adb = AppendOnlyAdb(rec)
    assert adb.serial == "S1"
    assert adb.shell("mkdir -p /sdcard/a") == "ok"
    assert adb.run(["shell", "-T", "df -k /sdcard/"]) == "ok"
    assert adb.run(["get-state"]) == "ok"
    for args in (["push", "a", "/sdcard/a"], ["shell", "-T", "rm /sdcard/a"], ["exec-out", "ls"]):
        with pytest.raises(UnsafeCommand):
            adb.run(args)
    assert adb.run_bytes(["shell", "-T", "ls /sdcard"]) == b"ok"
    with pytest.raises(UnsafeCommand):
        adb.run_bytes(["exec-out", "ls /sdcard"])
    with pytest.raises(UnsafeCommand):
        adb.shell("pm list packages")
    other = adb.with_serial("S2")
    assert isinstance(other, AppendOnlyAdb) and other.serial == "S2"
