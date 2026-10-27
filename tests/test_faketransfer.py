from __future__ import annotations

import re

import pytest
from faketransfer import FakeStoragePhone, provider_file

from admenot.engine.adb.transport import AdbError
from admenot.engine.transfer.guard import CONTENT_TAIL, ReadOnlyAdb


def _phone(tmp_path):
    (tmp_path / "sdcard" / "DCIM").mkdir(parents=True)
    (tmp_path / "sdcard" / "DCIM" / "a.jpg").write_bytes(b"12345")
    (tmp_path / "sdcard" / "DCIM" / "b.jpg").write_bytes(b"xy")
    return FakeStoragePhone(tmp_path)


def test_fake_storage_find_stat(tmp_path):
    phone = _phone(tmp_path)
    out = ReadOnlyAdb(phone).shell("find -H '/sdcard/DCIM' -type f -exec stat -c '%s|%Y|%n' {} +")
    rows = out.splitlines()
    assert len(rows) == 2
    for row in rows:
        assert re.fullmatch(r"\d+\|\d+\|/sdcard/DCIM/[ab]\.jpg", row)
    assert sorted(int(r.split("|")[0]) for r in rows) == [2, 5]
    stat = phone.shell("stat -c '%s|%Y|%n' /sdcard/DCIM/a.jpg")
    assert stat.startswith("5|") and stat.strip().endswith("|/sdcard/DCIM/a.jpg")


def test_fake_df_sha_content_and_state(tmp_path):
    phone = _phone(tmp_path)
    assert "70000000" in phone.shell("df -k /sdcard")
    assert phone.shell("sha256sum /sdcard/DCIM/b.jpg").endswith("  /sdcard/DCIM/b.jpg\n")
    provider_file(tmp_path, "content://sms").parent.mkdir(parents=True)
    provider_file(tmp_path, "content://sms").write_text("Row: 0 _id=1, body=hi\n", encoding="utf-8")
    (tmp_path / "mms_parts").mkdir()
    (tmp_path / "mms_parts" / "7").write_bytes(b"\x00\x01")
    assert "body=hi" in phone.shell("content query --uri 'content://sms' --projection '_id:body'")
    assert phone.run_bytes(["shell", "-T", "content read --uri content://mms/part/7"]) == b"\x00\x01"
    phone.deny_uris.add("content://sms")
    # odmowa: kod 0, komunikat tylko na stderr (jak Xiaomi bez „ustawień zabezpieczeń”)
    assert phone.shell("content query --uri 'content://sms' --projection '_id'") == ""
    merged = phone.shell("content query --uri 'content://sms' --projection '_id'" + CONTENT_TAIL)
    assert "SecurityException" in merged
    assert phone.get_state() == "device"
    phone.online = False
    assert phone.get_state() == "offline"
    with pytest.raises(AdbError):
        phone.shell("df -k")


def test_fake_pull_and_disconnect(tmp_path):
    phone = _phone(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    result = phone.pull(["/sdcard/DCIM"], out, lambda: False, lambda: None)
    assert result.rc == 0 and (out / "DCIM" / "a.jpg").read_bytes() == b"12345"
    phone.fail_after_files = 3
    result = phone.pull(["/sdcard/DCIM/a.jpg", "/sdcard/DCIM/b.jpg"], out, lambda: False, lambda: None)
    assert result.rc == 1 and phone.get_state() == "offline"


def test_fake_push_preserves_mtime_and_denies(tmp_path):
    import os
    src = tmp_path / "src"
    src.mkdir()
    f = src / "a.jpg"
    f.write_bytes(b"hello")
    os.utime(f, (1_600_000_000, 1_600_000_000))
    phone = FakeStoragePhone(tmp_path / "phone")
    (tmp_path / "phone" / "sdcard").mkdir(parents=True)
    phone.free_kb = 1000
    # katalog nie istnieje bez mkdir -p
    res = phone.push([f], "/sdcard/DCIM/", lambda: False, lambda: None)
    assert res.rc != 0
    phone.shell("mkdir -p /sdcard/DCIM")
    res = phone.push([f], "/sdcard/DCIM/", lambda: False, lambda: None)
    assert res.rc == 0 and phone.push_calls == 2
    dest = tmp_path / "phone" / "sdcard" / "DCIM" / "a.jpg"
    assert dest.read_bytes() == b"hello" and int(dest.stat().st_mtime) == 1_600_000_000
    assert phone.shell("stat -c '%s|%Y|%n' /sdcard/DCIM/a.jpg") == "5|1600000000|/sdcard/DCIM/a.jpg\n"
    # push pod nową nazwą (pełna ścieżka pliku)
    assert phone.push([f], "/sdcard/DCIM/b.jpg", lambda: False, lambda: None).rc == 0
    assert (tmp_path / "phone" / "sdcard" / "DCIM" / "b.jpg").exists()
    # df: nagłówek + jedna linia, Available zmniejszone o wgrane (2 x 5 B -> zaokrąglone w górę do 1 KB)
    lines = phone.shell("df -k /sdcard/").splitlines()
    assert len(lines) == 2 and lines[1].split()[3] == "998"
    # odmowa
    phone.shell("mkdir -p /sdcard/Android/media/com.x")
    phone.deny_prefixes = {"/sdcard/Android/media"}
    phone.shell("mkdir -p /sdcard/Android/media/com.x")  # istniejący katalog — bez błędu
    with pytest.raises(AdbError, match="mkdir: '/sdcard/Android/media/com.y': Permission denied"):
        phone.shell("mkdir -p /sdcard/DCIM/new /sdcard/Android/media/com.y")
    assert (tmp_path / "phone" / "sdcard" / "DCIM" / "new").is_dir()
    res = phone.push([f], "/sdcard/Android/media/com.x/", lambda: False, lambda: None)
    assert res.rc == 1 and "Permission denied" in res.lines[0] and res.lines[0].startswith("adb: error:")
    assert not (tmp_path / "phone" / "sdcard" / "Android" / "media" / "com.x" / "a.jpg").exists()


def test_fake_scan_volume_and_default_df(tmp_path):
    phone = _phone(tmp_path)
    assert phone.scans == 0
    phone.shell("content call --uri content://media --method scan_volume --arg external_primary")
    assert phone.scans == 1
    assert phone.free_kb is None and phone.shell("df -k /sdcard/").splitlines()[1].split()[3] == "70000000"


def test_fake_fail_after_push_files_goes_offline_and_reconnects(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    files = []
    for n in "abc":
        (src / f"{n}.bin").write_bytes(b"0123456789")
        files.append(src / f"{n}.bin")
    phone = FakeStoragePhone(tmp_path / "phone")
    (tmp_path / "phone" / "sdcard").mkdir(parents=True)
    phone.shell("mkdir -p /sdcard/X")
    phone.fail_after_push_files = 2
    res = phone.push(files, "/sdcard/X/", lambda: False, lambda: None)
    assert res.rc != 0 and phone.get_state() == "offline"
    out = tmp_path / "phone" / "sdcard" / "X"
    assert (out / "a.bin").stat().st_size == 10 and (out / "b.bin").stat().st_size == 10
    assert (out / "c.bin").stat().st_size == 5  # urwany w połowie
    assert phone.push([files[2]], "/sdcard/X/", lambda: False, lambda: None).rc != 0  # offline
    phone.reconnect()
    phone.fail_after_push_files = None
    assert phone.push([files[2]], "/sdcard/X/", lambda: False, lambda: None).rc == 0
    assert (out / "c.bin").stat().st_size == 10


def test_fake_push_after_offline_writes_nothing_and_rejects_unsafe_target(tmp_path):
    from admenot.engine.transfer.guard import UnsafeCommand
    src = tmp_path / "a.bin"
    src.write_bytes(b"0123456789")
    phone = FakeStoragePhone(tmp_path / "phone")
    (tmp_path / "phone" / "sdcard").mkdir(parents=True)
    phone.shell("mkdir -p /sdcard/X")
    phone.fail_after_push_files = 0
    assert phone.push([src], "/sdcard/X/", lambda: False, lambda: None).rc == 1  # urwanie
    other = tmp_path / "b.bin"
    other.write_bytes(b"zz")
    res = phone.push([other, src], "/sdcard/X/", lambda: False, lambda: None)  # "równoległe", już offline
    assert res.rc == 1 and "device offline" in res.lines[-1]
    assert not (tmp_path / "phone" / "sdcard" / "X" / "b.bin").exists()
    with pytest.raises(UnsafeCommand):
        phone.push([src], "/sdcard/../x/", lambda: False, lambda: None)


def test_fake_stat_tail_reports_errors_as_lines(tmp_path):
    from admenot.engine.transfer.guard import STAT_TAIL
    phone = _phone(tmp_path)
    phone.deny_stat_prefixes = {"/sdcard/DCIM/b"}
    with pytest.raises(AdbError):
        phone.shell("stat -c '%s|%Y|%n' /sdcard/DCIM/a.jpg /sdcard/nope")
    out = phone.shell("stat -c '%s|%Y|%n' /sdcard/DCIM/a.jpg /sdcard/nope /sdcard/DCIM/b.jpg" + STAT_TAIL)
    lines = out.splitlines()
    assert lines[0].startswith("5|") and lines[0].endswith("|/sdcard/DCIM/a.jpg")
    assert lines[1:] == ["stat: '/sdcard/nope': No such file or directory",
                         "stat: '/sdcard/DCIM/b.jpg': Permission denied"]
