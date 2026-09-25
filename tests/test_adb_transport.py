import subprocess

import pytest

from demalware.engine.adb.fake import FakeAdb
from demalware.engine.adb.transport import AdbError, RealAdb, classify_error


class _Proc:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_real_adb_builds_command_with_serial(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["timeout"] = kw["timeout"]
        return _Proc(stdout=b"ok\r\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    adb = RealAdb(serial="R58T", adb_path="adb.exe")
    assert adb.shell("getprop", timeout=5) == "ok\n"
    assert seen["cmd"] == ["adb.exe", "-s", "R58T", "shell", "getprop"]
    assert seen["timeout"] == 5


def test_real_adb_decodes_invalid_utf8(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Proc(stdout=b"a\xffb\r\n"))
    assert RealAdb(adb_path="adb.exe").shell("x") == "a�b\n"


def test_real_adb_timeout(monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(AdbError) as exc:
        RealAdb(adb_path="adb.exe").shell("dumpsys x", timeout=1)
    assert exc.value.kind == "timeout"


def test_real_adb_missing_binary(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(AdbError) as exc:
        RealAdb().shell("x")
    assert exc.value.kind == "adb_missing"


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("error: device unauthorized.\nThis adb server's $ADB_VENDOR_KEYS is not set", "unauthorized"),
        ("error: device offline", "offline"),
        ("error: no devices/emulators found", "no_device"),
        ("error: device 'X' not found", "no_device"),
        ("Error: unknown command 'get-role-holders'", "command_failed"),
    ],
)
def test_classify_error(text, kind):
    assert classify_error(text).kind == kind


def test_nonzero_exit_raises_classified(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: _Proc(returncode=1, stderr=b"error: device offline")
    )
    with pytest.raises(AdbError) as exc:
        RealAdb(adb_path="adb.exe").shell("x")
    assert exc.value.kind == "offline"


def test_with_serial_keeps_adb_path():
    adb = RealAdb(adb_path="adb.exe").with_serial("ABC")
    assert (adb.serial, adb.adb_path) == ("ABC", "adb.exe")


def test_fake_adb_returns_and_records():
    fake = FakeAdb({"getprop": "[a]: [b]\n"})
    assert fake.shell("getprop") == "[a]: [b]\n"
    assert fake.calls == ["getprop"]


def test_fake_adb_unknown_command_raises():
    with pytest.raises(AdbError) as exc:
        FakeAdb({}).shell("nope")
    assert exc.value.kind == "command_failed"


def test_fake_adb_can_raise_configured_error():
    fake = FakeAdb({"x": AdbError("timeout", "slow")})
    with pytest.raises(AdbError) as exc:
        fake.shell("x")
    assert exc.value.kind == "timeout"


def test_fake_adb_host_run_and_shell_via_run():
    fake = FakeAdb({"getprop": "p"}, host={"devices -l": "List of devices attached\n"})
    assert fake.run(["devices", "-l"]).startswith("List")
    assert fake.run(["shell", "getprop"]) == "p"
