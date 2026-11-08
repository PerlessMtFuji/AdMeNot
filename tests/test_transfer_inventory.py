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
    app_sizes,
    build_inventory,
    classify_apps,
    refresh_inventory,
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


def _app(package: str, apk_path: str | None):
    from admenot.engine.transfer.inventory import AppEntry
    return AppEntry(package, package, 1, "safe", True, apk_path=apk_path)


def test_app_sizes_sum_base_and_splits(tmp_path):
    """Rozmiar aplikacji = base.apk + wszystkie splity z jej katalogu (jak `pm path`)."""
    phone, adb = _ro(tmp_path)
    root = tmp_path / "phone"
    _put(root, "app/a-1/base.apk", b"a" * 100)
    _put(root, "app/a-1/split_config.pl.apk", b"a" * 20)
    _put(root, "app/a-1/lib/x.so", b"a" * 999)  # nie APK, głębiej — nie liczymy
    _put(root, "app/b-1/base.apk", b"b" * 7)
    apps = [_app("a", "/sdcard/app/a-1/base.apk"), _app("b", "/sdcard/app/b-1/base.apk"),
            _app("nopath", None)]
    assert app_sizes(adb, apps, lambda: False) == {"a": 120, "b": 7}
    assert len(phone.commands) == 1  # jedno `find` na wszystkie aplikacje


def test_app_sizes_shared_dir_uses_exact_path(tmp_path):
    """Stary układ: kilka APK w jednym katalogu — liczymy tylko jawną ścieżkę pakietu."""
    _phone, adb = _ro(tmp_path)
    root = tmp_path / "phone"
    _put(root, "legacy/a.apk", b"a" * 5)
    _put(root, "legacy/b.apk", b"b" * 9)
    apps = [_app("a", "/sdcard/legacy/a.apk"), _app("b", "/sdcard/legacy/b.apk")]
    sizes = app_sizes(adb, apps, lambda: False)
    assert sizes == {"a": 5, "b": 9}


def test_app_sizes_failed_dir_does_not_lose_others(tmp_path):
    """Błąd `find` (kod ≠ 0) gubi cały wynik — wtedy katalogi po kolei, a nieczytelny bez rozmiaru."""
    _phone, adb = _ro(tmp_path)
    _put(tmp_path / "phone", "app/a-1/base.apk", b"a" * 3)
    apps = [_app("a", "/sdcard/app/a-1/base.apk"), _app("gone", "/sdcard/app/gone-1/base.apk")]
    assert app_sizes(adb, apps, lambda: False) == {"a": 3}


def test_build_inventory_fills_app_sizes(tmp_path):
    phone = FakeStoragePhone(tmp_path / "phone")
    install_telephony(tmp_path / "phone")
    _put(tmp_path / "phone", "app/ok-1/base.apk", b"o" * 42)
    r = _result("ok", "safe")
    r.facts.apk_path = "/sdcard/app/ok-1/base.apk"
    inv = build_inventory(ReadOnlyAdb(phone), _report(r, _result("nopath", "safe")), lambda: False)
    assert [(a.package, a.size) for a in inv.apps] == [("ok", 42), ("nopath", None)]
    again = refresh_inventory(ReadOnlyAdb(phone), inv, lambda: False)
    assert [a.size for a in again.apps] == [42, None]


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


VCARD = "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Ala\r\nEND:VCARD\r\n"
CONTACTS_URI = "content://com.android.contacts/contacts"


def _vcf(root, rel: str = "Kopia kontaktów/kontakty.vcf", mtime: int | None = None) -> None:
    _put(root, rel, (VCARD * 3).encode(), mtime)


def _inv(phone, tmp_path):
    return build_inventory(ReadOnlyAdb(phone), _report(_result("ok", "safe")), lambda: False)


def test_inventory_denied_contacts_with_exports(tmp_path):
    phone = FakeStoragePhone(tmp_path / "phone")
    install_telephony(tmp_path / "phone")
    _vcf(tmp_path / "phone")
    phone.deny_uris = {CONTACTS_URI}
    inv = _inv(phone, tmp_path)
    assert inv.contacts is None
    assert inv.denied == {"contacts"}
    assert [e.remote for e in inv.exports["contacts"]] == ["/sdcard/Kopia kontaktów/kontakty.vcf"]
    assert inv.exports["contacts"][0].count == 3
    assert "sms" not in inv.exports


def test_inventory_readable_contacts_ignore_exports(tmp_path):
    phone = FakeStoragePhone(tmp_path / "phone")
    install_telephony(tmp_path / "phone")
    _vcf(tmp_path / "phone")
    inv = _inv(phone, tmp_path)
    assert inv.contacts
    assert inv.denied == frozenset()
    assert inv.exports == {}
    assert not any(c.startswith("head") for c in phone.commands)


def test_inventory_failed_query_is_not_denied(tmp_path):
    phone = FakeStoragePhone(tmp_path / "phone")
    (tmp_path / "phone" / "sdcard").mkdir(parents=True, exist_ok=True)
    _vcf(tmp_path / "phone")
    inv = _inv(phone, tmp_path)
    assert inv.contacts is None
    assert "contacts" not in inv.denied
    assert "contacts" in inv.exports


def test_refresh_inventory_keeps_apps(tmp_path):
    phone = FakeStoragePhone(tmp_path / "phone")
    install_telephony(tmp_path / "phone")
    phone.deny_uris = {CONTACTS_URI}
    _put(tmp_path / "phone", "DCIM/a.jpg")
    previous = _inv(phone, tmp_path)
    assert previous.exports == {}
    _vcf(tmp_path / "phone")
    inv = refresh_inventory(ReadOnlyAdb(phone), previous, lambda: False)
    assert [e.remote for e in inv.exports["contacts"]] == ["/sdcard/Kopia kontaktów/kontakty.vcf"]
    assert inv.denied == {"contacts"}
    assert inv.apps is previous.apps and inv.skipped_apps is previous.skipped_apps


def test_loose_files_in_main_folder_go_to_empty_other(tmp_path):
    root = tmp_path / "phone"
    _put(root, "notes.txt", b"abc")
    _put(root, ".hidden", b"z")
    _put(root, "Music/c.mp3", b"12")
    _, adb = _ro(tmp_path)
    files, others, _ = scan_files(adb, lambda: False)
    assert {f.remote: f.category for f in files} == {
        "/sdcard/notes.txt": "other:", "/sdcard/Music/c.mp3": "other:Music"}
    assert others == {"": (1, 3), "Music": (1, 2)}


def test_unreadable_sdcard_listing_raises(tmp_path):
    import pytest

    from admenot.engine.adb.transport import AdbError

    phone, adb = _ro(tmp_path)
    orig = phone._ls

    def boom(args):
        if args[1] == "/sdcard":
            raise AdbError("command_failed", "ls: /sdcard: Permission denied")
        return orig(args)

    phone._ls = boom
    with pytest.raises(AdbError):
        scan_files(adb, lambda: False)


def test_find_timeout_propagates_without_per_root_retry(tmp_path):
    import pytest

    from admenot.engine.adb.transport import AdbError

    root = tmp_path / "phone"
    _put(root, "DCIM/a.jpg")
    phone, adb = _ro(tmp_path)
    orig = phone._find

    def slow(args):
        if "-maxdepth" not in args:
            raise AdbError("timeout", "find (>600s)")
        return orig(args)

    phone._find = slow
    with pytest.raises(AdbError) as ei:
        scan_files(adb, lambda: False)
    assert ei.value.kind == "timeout"
    assert sum(c.startswith("find") and "-maxdepth" not in c for c in phone.commands) == 1
