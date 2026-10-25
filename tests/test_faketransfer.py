from __future__ import annotations

import re

import pytest
from faketransfer import FakeStoragePhone, provider_file

from admenot.engine.adb.transport import AdbError
from admenot.engine.transfer.guard import ReadOnlyAdb


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
    with pytest.raises(AdbError):
        phone.shell("content query --uri 'content://sms' --projection '_id'")
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
