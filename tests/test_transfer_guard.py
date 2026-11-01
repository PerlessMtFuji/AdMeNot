from __future__ import annotations

import pytest

from admenot.engine.transfer.guard import (
    CONTENT_TAIL,
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


def test_head_allowed():
    from admenot.engine.transfer.exports import head_cmd

    assert_read_only(head_cmd("/sdcard/Kopia kontaktów/it's.vcf"))
    assert_read_only(f"head -c 10 {q('/sdcard/a.vcf')}")


@pytest.mark.parametrize("bad", [
    "head -c 70000 '/sdcard/a.vcf'", "head -c 10 '/data/a'", "head -c 10 '/sdcard/../data/a'",
    "head -c 10 '/sdcard/a' '/sdcard/b'", "head '/sdcard/a'", "head -n 5 '/sdcard/a'",
    "head -c 10 '/sdcard/a'; rm x", "head -c 10 '/sdcard/a' > /sdcard/b", "head -c -1 '/sdcard/a'",
    "head -c 10 \"/sdcard/a\"", "head  -c 10 '/sdcard/a'", "head -c 010 '/sdcard/a'",
])
def test_head_blocked(bad):
    with pytest.raises(UnsafeCommand):
        assert_read_only(bad)


def test_content_query_may_merge_stderr():
    assert_read_only("content query --uri 'content://sms' --projection '_id'" + CONTENT_TAIL)


@pytest.mark.parametrize("bad", [
    "ls /sdcard" + CONTENT_TAIL,
    "content read --uri content://mms/part/1" + CONTENT_TAIL,
    "content delete --uri content://sms" + CONTENT_TAIL,
    "content query --uri 'content://sms'; rm x" + CONTENT_TAIL,
    "content query --uri 'content://sms' 2>&1" + CONTENT_TAIL,
    "content query --uri 'content://sms' 2>/sdcard/x",
    "content query --uri 'content://sms' 2>&1 || true",
])
def test_content_tail_only_after_query(bad):
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


def test_append_only_stat_tail_exact():
    from admenot.engine.transfer.guard import STAT_TAIL, assert_append_only
    assert_append_only("stat -c '%s|%Y|%n' /sdcard/a '/sdcard/it'\"'\"'s.jpg'" + STAT_TAIL)
    for cmd in ("ls /sdcard" + STAT_TAIL, "df -k /sdcard/" + STAT_TAIL, "mkdir -p /sdcard/x" + STAT_TAIL,
                "stat /sdcard/a 2>&1 || reboot", "stat /sdcard/a 2>/dev/null", "stat /sdcard/a || true",
                "stat /sdcard/a 2>&1", "stat /sdcard/a 2>&1 || true; reboot",
                "stat /sdcard/a; reboot" + STAT_TAIL, "stat /sdcard/a" + STAT_TAIL + STAT_TAIL,
                "stat '/sdcard/a" + STAT_TAIL):
        with pytest.raises(UnsafeCommand):
            assert_append_only(cmd)


# --------------------------------------------------------------------------------------
# TelephonyWriteAdb
# --------------------------------------------------------------------------------------
from admenot.engine.transfer import helper
from admenot.engine.transfer.guard import TelephonyWriteAdb, safe_helper_target

_PKG = "pl.admenot.helper"
_SAVED = "com.google.android.apps.messaging"
_CP = ("CLASSPATH=/data/local/tmp/admenot/admenot-helper.dex app_process / pl.admenot.helper.Main write ")
_IN = "/data/local/tmp/admenot/in/"


def _tel(saved=frozenset({_SAVED})):
    rec = Recorder()
    return TelephonyWriteAdb(rec, lambda: saved), rec


_TEL_ALLOWED = [
    "mkdir -p /data/local/tmp/admenot/in",
    "rm -rf /data/local/tmp/admenot/in",
    "rm -rf /data/local/tmp/admenot",
    "sha256sum /data/local/tmp/admenot/admenot-helper.dex",
    _CP + _IN + "input.jsonl",
    _CP + _IN + "input.jsonl --account vnd.sec.contact.phone 'my phone'",
    "appops get com.android.shell WRITE_SMS",
    *(f"appops set com.android.shell WRITE_SMS {m}" for m in ("allow", "default", "ignore", "deny", "foreground")),
    "pm list packages pl.admenot.helper",
    *(f"pm grant pl.admenot.helper android.permission.{p}"
      for p in ("READ_CONTACTS", "WRITE_CONTACTS", "READ_CALL_LOG", "WRITE_CALL_LOG", "READ_SMS")),
    "pm uninstall pl.admenot.helper",
    "dumpsys role",
    f"cmd role add-role-holder android.app.role.SMS {_PKG}",
    f"cmd role add-role-holder android.app.role.SMS {_SAVED}",
    f"cmd role remove-role-holder android.app.role.SMS {_PKG}",
    f"am instrument -w -r -e cmd write -e input {helper.COMPANION_IN}/input.jsonl pl.admenot.helper/.Runner",
    (f"am instrument -w -r -e cmd write -e input {helper.COMPANION_IN}/input.jsonl "
     "-e account_type com.google -e account_name 'a b@x.pl' pl.admenot.helper/.Runner"),
    "am start -n pl.admenot.helper/.RoleActivity",
    "am start -a android.settings.MANAGE_DEFAULT_APPS_SETTINGS",
    "am start -a android.intent.action.VIEW -t text/x-vcard -d content://media/external/file/1234",
    "content call --uri content://media --method scan_file --arg /storage/emulated/0/Download/admenot-1.vcf",
    ("content query --uri content://media/external/file --projection _id --where "
     "\"_data='/storage/emulated/0/Download/admenot-1.vcf'\""),
    "dumpsys account",
]


@pytest.mark.parametrize("cmd", _TEL_ALLOWED)
def test_tel_guard_allows_exact_forms(cmd):
    adb, rec = _tel()
    assert adb.shell(cmd) == "ok"
    assert rec.calls == [("shell", cmd)]


def test_tel_guard_allows_append_only_shell_T_and_install():
    adb, rec = _tel()
    adb.shell("mkdir -p /sdcard/DCIM/")
    adb.run(["shell", "-T", "dumpsys role"])
    adb.run(["get-state"])
    apk = str(helper.artifact("apk")[0])
    adb.run(["install", "-g", apk])
    assert ("run", ["install", "-g", apk]) in rec.calls


@pytest.mark.parametrize("cmd", [
    "rm -rf /data/local/tmp",
    "rm -rf /data/local/tmp/admenot/../x",
    "rm -rf /data/local/tmp/admenot/in/x",
    "rm /sdcard/a",
    "rm -rf /sdcard",
    "mkdir -p /data/local/tmp/other",
])
def test_tel_guard_rejects_rm_elsewhere(cmd):
    adb, rec = _tel()
    with pytest.raises(UnsafeCommand):
        adb.shell(cmd)
    assert rec.calls == []


@pytest.mark.parametrize("cmd", [
    "pm uninstall com.whatsapp", "pm uninstall --user 0 pl.admenot.helper", "pm uninstall -k pl.admenot.helper",
    "pm grant com.evil android.permission.READ_CONTACTS",
    "pm grant pl.admenot.helper android.permission.CAMERA",
    "pm clear pl.admenot.helper",
])
def test_tel_guard_rejects_other_package_uninstall(cmd):
    adb, _ = _tel()
    with pytest.raises(UnsafeCommand):
        adb.shell(cmd)


def test_tel_guard_role_only_ours_or_saved():
    adb, _ = _tel()
    for cmd in ("cmd role add-role-holder android.app.role.SMS com.evil",
                f"cmd role remove-role-holder android.app.role.SMS {_SAVED}",
                f"cmd role add-role-holder android.app.role.DIALER {_PKG}",
                "cmd role get-role-holders android.app.role.SMS"):
        with pytest.raises(UnsafeCommand):
            adb.shell(cmd)
    nothing, _ = _tel(saved=frozenset())
    with pytest.raises(UnsafeCommand):
        nothing.shell(f"cmd role add-role-holder android.app.role.SMS {_SAVED}")
    nothing.shell(f"cmd role add-role-holder android.app.role.SMS {_PKG}")


@pytest.mark.parametrize("cmd", [
    "appops set com.whatsapp WRITE_SMS allow",
    "appops set com.android.shell READ_SMS allow",
    "appops set com.android.shell WRITE_SMS maybe",
    "appops set --user 0 com.android.shell WRITE_SMS allow",
    "appops get com.whatsapp WRITE_SMS",
    "appops reset",
])
def test_tel_guard_rejects_appops_other_package_or_op(cmd):
    adb, _ = _tel()
    with pytest.raises(UnsafeCommand):
        adb.shell(cmd)


def test_tel_guard_install_only_artifact(tmp_path):
    adb, rec = _tel()
    other = tmp_path / "evil.apk"
    other.write_bytes(b"x")
    apk = str(helper.artifact("apk")[0])
    for args in (["install", "-g", str(other)], ["install", apk], ["install", "-r", "-g", apk],
                 ["uninstall", _PKG], ["push", "a", "/sdcard/b"]):
        with pytest.raises(UnsafeCommand):
            adb.run(args)
    assert rec.calls == []


@pytest.mark.parametrize("cmd", [
    "rm -rf /data/local/tmp/admenot; rm -rf /sdcard",
    "rm -rf /data/local/tmp/admenot/in && id",
    "dumpsys role | cat",
    "dumpsys role\nid",
    "dumpsys role $(id)",
    "dumpsys package pl.admenot.helper",
    _CP + _IN + "a;id",
    _CP + _IN + "a$(id).jsonl",
    _CP + "'" + _IN + "a\nb'",
    _CP + _IN + "../x.jsonl",
    _CP + "/sdcard/x.jsonl",
    _CP + _IN + "a.jsonl --account t 'n\nx'",
    _CP + _IN + "a.jsonl --account t n; id",
    _CP + _IN + "a.jsonl --account t",
    "CLASSPATH=/data/local/tmp/other.dex app_process / pl.admenot.helper.Main write " + _IN + "a",
    f"am instrument -w -r -e cmd write -e input {helper.COMPANION_IN}/../x pl.admenot.helper/.Runner",
    f"am instrument -w -r -e cmd write -e input {helper.COMPANION_IN}/a;id pl.admenot.helper/.Runner",
    f"am instrument -w -r -e cmd write -e input {helper.COMPANION_IN}/a pl.evil/.Runner",
    (f"am instrument -w -r -e cmd write -e input {helper.COMPANION_IN}/a -e account_type 'x\ny' "
     "-e account_name n pl.admenot.helper/.Runner"),
    "am start -a android.intent.action.VIEW -t text/x-vcard -d content://media/external/file/12a",
    "am start -a android.intent.action.VIEW -t text/x-vcard -d file:///sdcard/x.vcf",
    "am start -n com.evil/.Main",
    "content call --uri content://media --method scan_file --arg /sdcard/x.vcf",
    "content call --uri content://media --method scan_file --arg /storage/emulated/0/Download/../x.vcf",
    "content call --uri content://media --method scan_file --arg /storage/emulated/0/Download/a.vcf;id",
    "content delete --uri content://sms",
    "content query --uri content://sms",
    ("content query --uri content://media/external/file --projection _id --where "
     "\"_data='/storage/emulated/0/Download/a.vcf' OR 1=1\""),
    ("content query --uri content://media/external/file --projection _id --where "
     "\"_data='/storage/emulated/0/Download/$(id).vcf'\""),
])
def test_tel_guard_rejects_injection(cmd):
    adb, rec = _tel()
    with pytest.raises(UnsafeCommand):
        adb.shell(cmd)
    assert rec.calls == []


def test_tel_guard_serial_and_with_serial():
    adb, _ = _tel()
    assert adb.serial == "S1"
    other = adb.with_serial("S2")
    assert isinstance(other, TelephonyWriteAdb) and other.serial == "S2"
    assert other.role_restore is adb.role_restore


def test_tel_guard_run_bytes_only_shell_T():
    adb, _ = _tel()
    assert adb.run_bytes(["shell", "-T", "dumpsys role"]) == b"ok"
    with pytest.raises(UnsafeCommand):
        adb.run_bytes(["exec-out", "dumpsys role"])
    with pytest.raises(UnsafeCommand):
        adb.run_bytes(["shell", "-T", "rm -rf /data/local/tmp"])


def test_safe_helper_target():
    assert safe_helper_target("/data/local/tmp/admenot/in/") == "/data/local/tmp/admenot/in/"
    assert safe_helper_target("/data/local/tmp/admenot/admenot-helper.dex")
    assert safe_helper_target(helper.COMPANION_IN + "/")
    for bad in ("/data/local/tmp/", "/data/local/tmp/admenot", "/data/local/tmp/admenot/../x", "/sdcard/x",
                "/data/local/tmp/admenotx/", "/data/local/tmp/admenot/a\nb"):
        with pytest.raises(UnsafeCommand):
            safe_helper_target(bad)


def test_tel_guard_allows_everything_helper_writers_issue():
    """Polecenia budowane przez prawdziwe AppProcessWriter i CompanionWriter przechodzą przez strażnika."""
    from admenot.engine.transfer.guard import safe_push_target
    from admenot.engine.transfer.puller import PullResult
    from admenot.engine.transfer.telrecords import SmsRecord

    digest = helper.artifact("dex")[1]
    cmds: list[str] = []

    class Fake(Recorder):
        def shell(self, command, timeout=20.0):
            cmds.append(command)
            return f"{digest}  x\n" if command.startswith("sha256sum") else "DONE 0 0\n"

    class Pusher:
        def push(self, locals_, remote, should_stop, tick):
            safe_push_target(remote)
            return PullResult(0, [], False)

    adb = TelephonyWriteAdb(Fake(), lambda: frozenset())
    sms = [("a1", SmsRecord("+48000000001", 1, 1, 1, 1, -1, None, "x"))]
    for account in (None, ("vnd.sec.contact.phone", "my phone"), ("com.google", "o'neil $x@x.pl")):
        helper.AppProcessWriter(adb, Pusher(), account).write("sms", sms, lambda: None)
        helper.CompanionWriter(adb, Pusher(), account).write("sms", sms, lambda: None)
    assert any(c.startswith("CLASSPATH=") and "--account" in c for c in cmds)
    assert any(c.startswith("am instrument") and "account_name" in c for c in cmds)


# --------------------------------------------------------------------------------------
# TelPlanReadAdb (plan telefonii na nowym telefonie)
# --------------------------------------------------------------------------------------
from admenot.engine.transfer.guard import TelPlanReadAdb


def test_tel_plan_read_adb_allows_reads_and_dumpsys_account_only():
    inner = Recorder()
    adb = TelPlanReadAdb(inner)
    assert adb.shell("dumpsys account", timeout=30) == "ok"
    assert adb.shell("content query --uri content://sms --projection _id" + CONTENT_TAIL) == "ok"
    assert adb.run(["get-state"]) == "ok"
    assert [c[1] for c in inner.calls] == [
        "dumpsys account", "content query --uri content://sms --projection _id" + CONTENT_TAIL, ["get-state"]]
    for bad in ("dumpsys account; rm -rf /sdcard", "dumpsys role", "dumpsys",
                "appops set com.android.shell WRITE_SMS allow", "cmd role add-role-holder android.app.role.SMS x.y",
                "pm uninstall x.y", "dumpsys account --verbose", "content insert --uri content://sms"):
        with pytest.raises(UnsafeCommand):
            adb.shell(bad)
    for args in (["install", "-g", "x.apk"], ["shell", "-T", "dumpsys account"], ["push", "a", "/sdcard/"]):
        with pytest.raises(UnsafeCommand):
            adb.run(args)
    assert len(inner.calls) == 3
    other = adb.with_serial("B")
    assert isinstance(other, TelPlanReadAdb) and other.serial == "B"
