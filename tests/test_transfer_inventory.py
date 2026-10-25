from __future__ import annotations

import os
from datetime import datetime

from faketransfer import FakeStoragePhone
from telephony_fixtures import install_telephony

from admenot.engine.facts import AppFacts
from admenot.engine.scoring import AppResult
from admenot.engine.session import ScanReport
from admenot.engine.transfer.guard import ReadOnlyAdb
from admenot.engine.transfer.inventory import (
    build_inventory,
    classify_apps,
    scan_files,
    whatsapp_backup_time,
)


def _put(root, rel: str, data: bytes = b"x", mtime: int | None = None) -> None:
    path = root / "sdcard" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _ro(tmp_path) -> tuple[FakeStoragePhone, ReadOnlyAdb]:
    phone = FakeStoragePhone(tmp_path / "phone")
    (tmp_path / "phone" / "sdcard").mkdir(parents=True, exist_ok=True)
    return phone, ReadOnlyAdb(phone)


def test_scan_files_assigns_categories(tmp_path):
    root = tmp_path / "phone"
    _put(root, "DCIM/Camera/a.jpg", b"aa")
    _put(root, "Download/x.pdf")
    _put(root, "Android/media/com.whatsapp/WhatsApp/Media/b.jpg")
    _put(root, "Music/c.mp3", b"12345")
    _put(root, ".thumbnails/t.jpg")
    _put(root, "DCIM/.thumbnails/u.jpg")
    _put(root, "DCIM/.trashed-1-x.jpg")
    _, adb = _ro(tmp_path)
    files, others, unreadable = scan_files(adb, lambda: False)
    cats = {f.remote: f.category for f in files}
    assert cats == {
        "/sdcard/DCIM/Camera/a.jpg": "media",
        "/sdcard/Download/x.pdf": "downloads",
        "/sdcard/Android/media/com.whatsapp/WhatsApp/Media/b.jpg": "whatsapp",
        "/sdcard/Music/c.mp3": "other:Music",
    }
    assert others == {"Music": (1, 5)}
    assert unreadable == 0


def test_android_data_excluded(tmp_path):
    root = tmp_path / "phone"
    _put(root, "Android/data/pkg/f")
    _put(root, "DCIM/a.jpg")
    _, adb = _ro(tmp_path)
    files, _, _ = scan_files(adb, lambda: False)
    assert [f.remote for f in files] == ["/sdcard/DCIM/a.jpg"]


def test_whatsapp_backup_time(tmp_path):
    root = tmp_path / "phone"
    a, b = 1_760_000_000, 1_760_100_000
    _put(root, "WhatsApp/Databases/msgstore-2026-10-24.1.db.crypt14", mtime=a)
    _put(root, "Android/media/com.whatsapp/WhatsApp/Databases/msgstore.db.crypt14", mtime=b)
    _, adb = _ro(tmp_path)
    assert whatsapp_backup_time(adb) == datetime.fromtimestamp(b)


def test_whatsapp_backup_time_none(tmp_path):
    _, adb = _ro(tmp_path)
    assert whatsapp_backup_time(adb) is None


def _result(package: str, verdict: str, system: bool = False) -> AppResult:
    facts = AppFacts(package, is_system=system, label=package.upper(), version_code=7)
    return AppResult(facts, [], 0, verdict, False, False)


def _report(*results: AppResult) -> ScanReport:
    return ScanReport(device=None, collectors={}, low_behavior_data=False, results=list(results))


def test_classify_apps():
    report = _report(
        _result("bad", "malicious"),
        _result("sus", "suspicious"),
        _result("ok", "safe"),
        _result("sys", "safe", system=True),
    )
    apps, skipped = classify_apps(report)
    assert [(a.package, a.default_on) for a in apps] == [("sus", False), ("ok", True)]
    assert [a.package for a in skipped] == ["bad"]
    assert apps[1].label == "OK" and apps[1].version_code == 7


def test_build_inventory_unavailable_sms(tmp_path):
    phone = FakeStoragePhone(tmp_path / "phone")
    install_telephony(tmp_path / "phone")
    _put(tmp_path / "phone", "DCIM/a.jpg")
    phone.deny_uris = {"content://sms"}
    inv = build_inventory(ReadOnlyAdb(phone), _report(_result("ok", "safe")), lambda: False)
    assert inv.sms is None
    assert inv.contacts and inv.calls and inv.mms
    assert [f.remote for f in inv.files] == ["/sdcard/DCIM/a.jpg"]
    assert inv.storage == (50_000_000 * 1024, 120_000_000 * 1024)
    assert [a.package for a in inv.apps] == ["ok"]
