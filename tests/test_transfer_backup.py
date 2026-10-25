from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from faketransfer import FakeStoragePhone
from telephony_fixtures import install_telephony

from admenot.engine.actions.backup import COMPLETE
from admenot.engine.device.info import DeviceInfo
from admenot.engine.transfer import store
from admenot.engine.transfer.backup import BackupError, Progress, Selection, run_backup
from admenot.engine.transfer.guard import ReadOnlyAdb, assert_read_only
from admenot.engine.transfer.inventory import AppEntry, Inventory, scan_files
from admenot.engine.transfer.state import State

NOW = datetime(2026, 10, 25, 12, 0, 0)
MTIME = 1_700_000_000
FILES = {
    "DCIM/Camera/a.jpg": b"A" * 300,
    "DCIM/Camera/b.jpg": b"B" * 200,
    "Download/c.pdf": b"%PDF" + b"c" * 50,
    "Music/song.mp3": b"M" * 40,
    "notes.txt": b"loose file",
}
MEDIA_AND_DOWNLOADS = ["/sdcard/DCIM/Camera/a.jpg", "/sdcard/DCIM/Camera/b.jpg", "/sdcard/Download/c.pdf"]


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))


def _device(serial: str = "FAKE") -> DeviceInfo:
    return DeviceInfo(
        serial=serial, brand="oppo", manufacturer="OPPO", model="CPH2127", device="x",
        market_name=None, android_release="11", sdk=30, security_patch=None, uptime_s=1.0,
        local_now=NOW)


def _phone(tmp_path: Path) -> FakeStoragePhone:
    root = tmp_path / "phone"
    for rel, data in FILES.items():
        path = root / "sdcard" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (MTIME, MTIME))
    install_telephony(root, mms=False)
    return FakeStoragePhone(root)


def _inventory(phone: FakeStoragePhone, apps: list[AppEntry] | None = None) -> Inventory:
    files, others, unreadable = scan_files(ReadOnlyAdb(phone), lambda: False)
    return Inventory(contacts=2, sms=2, mms=0, mms_bytes=0, calls=1, files=files, others=others,
                     apps=apps or [], skipped_apps=[], whatsapp_backup=None, storage=None,
                     unreadable=unreadable)


def _sel(**kw) -> Selection:
    opts = {"contacts": False, "sms": False, "mms": False, "calls": False,
            "categories": frozenset({"media", "downloads"}), "others": frozenset(), "apps": frozenset()}
    opts.update(kw)
    return Selection(**opts)


def _run(phone, copy, inv, sel, **kw):
    opts = {"on_progress": lambda p: None, "should_stop": lambda: False,
            "wait_device": phone.reconnect, "free_bytes": lambda p: 10 ** 12}
    opts.update(kw)
    return run_backup(phone, phone, _device(), copy, inv, sel, **opts)


def _copy() -> store.CopyDir:
    return store.create_copy("FAKE", _device(), None, NOW)


def _rows(copy: store.CopyDir) -> dict:
    st = State(copy.state_path)
    try:
        return st.all_files()
    finally:
        st.close()


def _manifest(copy: store.CopyDir) -> list[dict[str, str]]:
    with (copy.path / "manifest.csv").open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def _local_files(copy: store.CopyDir) -> list[Path]:
    return [p for p in copy.files_dir.rglob("*") if p.is_file()]


def test_full_copy_layout(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    progress: list[Progress] = []
    res = _run(phone, copy, _inventory(phone), _sel(contacts=True, sms=True), on_progress=progress.append)
    assert res.status == "complete"
    assert (res.files_done, res.files_failed) == (3, 0)
    assert res.bytes == sum(len(FILES[r[len("/sdcard/"):]]) for r in MEDIA_AND_DOWNLOADS)
    assert res.telephony["contacts"].status == "ok" and res.telephony["sms"].status == "ok"
    assert set(res.telephony) == {"contacts", "sms"}
    assert (copy.files_dir / "DCIM" / "Camera" / "a.jpg").read_bytes() == FILES["DCIM/Camera/a.jpg"]
    assert (copy.files_dir / "Download" / "c.pdf").read_bytes() == FILES["Download/c.pdf"]
    assert int((copy.files_dir / "DCIM" / "Camera" / "a.jpg").stat().st_mtime) == MTIME
    assert "BEGIN:VCARD" in (copy.phone_dir / "contacts.vcf").read_text(encoding="utf-8")
    assert (copy.phone_dir / "sms.xml").is_file()
    rows = _manifest(copy)
    assert [r["status"] for r in rows] == ["done"] * 3
    assert [r["remote"] for r in rows] == MEDIA_AND_DOWNLOADS
    assert rows[0]["local_rel"] == f"{copy.files_dir.name}/DCIM/Camera/a.jpg"
    assert rows[0]["size"] == "300"
    meta = copy.read_meta()
    assert meta.status == "complete"
    assert meta.counts["files"] == 3 and meta.bytes == res.bytes
    assert meta.selection["categories"] == ["downloads", "media"]
    assert {p.stage for p in progress} >= {"telephony", "files"}
    assert progress[-1].done_files == 3 and progress[-1].total_files == 3


def test_unselected_category_not_copied(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    res = _run(phone, copy, _inventory(phone), _sel(categories=frozenset({"media"})))
    assert res.status == "complete"
    assert sorted(p.name for p in _local_files(copy)) == ["a.jpg", "b.jpg"]
    assert not any(r.startswith(("/sdcard/Download", "/sdcard/Music")) for r in phone.pulled)
    assert [r["remote"] for r in _manifest(copy)] == MEDIA_AND_DOWNLOADS[:2]
    assert not (copy.phone_dir / "contacts.vcf").exists()


def test_other_folders_and_loose_files_copied_when_selected(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    res = _run(phone, copy, _inventory(phone),
               _sel(categories=frozenset(), others=frozenset({"", "Music"})))
    assert res.status == "complete"
    assert (copy.files_dir / "notes.txt").read_bytes() == FILES["notes.txt"]
    assert (copy.files_dir / "Music" / "song.mp3").read_bytes() == FILES["Music/song.mp3"]
    assert len(_local_files(copy)) == 2


def test_disconnect_mid_chunk_resumes(tmp_path):
    phone = _phone(tmp_path)
    phone.fail_after_files = 1
    copy = _copy()
    waits: list[int] = []

    def wait_device():
        waits.append(1)
        phone.fail_after_files = None
        phone.reconnect()

    res = _run(phone, copy, _inventory(phone), _sel(), wait_device=wait_device)
    assert res.status == "complete"
    assert len(waits) == 1
    assert all(r.status == "done" for r in _rows(copy).values())
    assert len(_local_files(copy)) == 3
    assert (copy.files_dir / "DCIM" / "Camera" / "b.jpg").read_bytes() == FILES["DCIM/Camera/b.jpg"]


def test_too_many_disconnects(tmp_path):
    phone = _phone(tmp_path)
    phone.fail_after_files = 0  # każda próba urywa się, telefon „wraca” i znowu znika
    copy = _copy()
    with pytest.raises(BackupError) as err:
        _run(phone, copy, _inventory(phone), _sel())
    assert err.value.key == "too_many_disconnects"
    assert copy.read_meta().status == "in_progress"


def test_telephony_disconnect_waits_and_retries(tmp_path):
    phone = _phone(tmp_path)
    inv = _inventory(phone)
    phone.online = False
    copy = _copy()
    waits: list[int] = []

    def wait_device():
        waits.append(1)
        phone.reconnect()

    res = _run(phone, copy, inv, _sel(sms=True, categories=frozenset()),
               wait_device=wait_device)
    assert res.status == "complete"
    assert len(waits) == 1
    assert res.telephony["sms"].status == "ok"


def test_resume_skips_done(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    first = _run(phone, copy, inv, _sel(), should_stop=lambda: len(phone.pulled) >= 2)
    assert first.status == "stopped"
    assert first.files_done == 2
    assert copy.read_meta().status == "in_progress"
    assert phone.pull_calls == 1
    assert not (copy.path / "manifest.csv").exists()

    second = _run(phone, copy, inv, _sel())
    assert second.status == "complete"
    assert phone.pull_calls == 2
    assert phone.pulled == MEDIA_AND_DOWNLOADS  # żaden plik nie pobrany dwa razy
    assert len(_local_files(copy)) == 3


def test_stop_mid_chunk_salvages_complete_files(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    res = _run(phone, copy, _inventory(phone), _sel(), should_stop=lambda: len(phone.pulled) >= 1)
    assert res.status == "stopped"
    rows = _rows(copy)
    assert rows["/sdcard/DCIM/Camera/a.jpg"].status == "done"
    assert rows["/sdcard/DCIM/Camera/b.jpg"].status == "pending"


def test_disk_full_stops_resumable(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    with pytest.raises(BackupError) as err:
        _run(phone, copy, _inventory(phone), _sel(), free_bytes=lambda p: 0)
    assert err.value.key == "disk_full"
    assert copy.read_meta().status == "in_progress"
    assert phone.pull_calls == 0


def test_file_changed_during_copy(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    target = phone.local("/sdcard/Download/c.pdf")
    new = b"%PDF changed and longer" * 3

    def change(remotes):
        if "/sdcard/Download/c.pdf" in remotes and target.read_bytes() != new:
            target.write_bytes(new)
            os.utime(target, (MTIME + 60, MTIME + 60))

    phone.before_pull = change
    res = _run(phone, copy, inv, _sel())
    assert res.status == "complete"
    row = _rows(copy)["/sdcard/Download/c.pdf"]
    assert (row.status, row.size, row.mtime) == ("done", len(new), MTIME + 60)
    assert (copy.files_dir / "Download" / "c.pdf").read_bytes() == new


def test_file_vanished_during_copy(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)

    def vanish(remotes):
        if "/sdcard/Download/c.pdf" in remotes:
            phone.local("/sdcard/Download/c.pdf").unlink(missing_ok=True)

    phone.before_pull = vanish
    res = _run(phone, copy, inv, _sel())
    row = _rows(copy)["/sdcard/Download/c.pdf"]
    assert (row.status, row.error) == ("skipped", "vanished")
    assert not (copy.files_dir / "Download" / "c.pdf").exists()
    assert res.files_done == 2 and res.files_failed == 0
    assert res.status == "complete"  # pliku nie ma już na telefonie — nic nie zostało do skopiowania


def test_file_failing_three_times_is_error(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)

    def corrupt(remotes):  # pull zostawia ucięty plik, telefon online, plik bez zmian
        if remotes == ["/sdcard/Download/c.pdf"]:
            phone.fail_after_files = len(phone.pulled)

    def wait_device():
        raise AssertionError("not a disconnect")

    original = phone.pull

    def pull(remotes, target, should_stop, tick):
        res = original(remotes, target, should_stop, tick)
        phone.fail_after_files = None
        phone.online = True
        return res

    phone.before_pull = corrupt
    phone.pull = pull
    res = run_backup(phone, phone, _device(), copy, inv, _sel(), on_progress=lambda p: None,
                     should_stop=lambda: False, wait_device=wait_device, free_bytes=lambda p: 10 ** 12)
    row = _rows(copy)["/sdcard/Download/c.pdf"]
    assert (row.status, row.attempts) == ("error", 3)
    assert res.status == "incomplete" and res.files_failed == 1
    assert copy.read_meta().status == "incomplete"
    assert not (copy.files_dir / "Download" / "c.pdf").exists()


def test_verify_hash_records_sha256(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    res = _run(phone, copy, _inventory(phone), _sel(verify_hash=True))
    assert res.status == "complete"
    rows = {r["remote"]: r for r in _manifest(copy)}
    want = hashlib.sha256(FILES["Download/c.pdf"]).hexdigest()
    assert rows["/sdcard/Download/c.pdf"]["sha256"] == want
    assert any(c.startswith("sha256sum ") for c in phone.commands)


def test_wrong_device_refused(tmp_path):
    phone = _phone(tmp_path)
    copy = store.create_copy("OTHER", _device("OTHER"), None, NOW)
    inv = _inventory(phone)
    issued = len(phone.commands)
    with pytest.raises(BackupError) as err:
        _run(phone, copy, inv, _sel(contacts=True))
    assert err.value.key == "wrong_device"
    assert phone.pull_calls == 0 and len(phone.commands) == issued
    assert not copy.state_path.exists()
    assert not (copy.phone_dir / "contacts.vcf").exists()


def test_apps_copied_with_complete_marker(tmp_path):
    phone = _phone(tmp_path)
    phone.apps = {"com.example.app": {"base.apk": b"base-bytes", "split_config.pl.apk": b"split"}}
    apps = [AppEntry("com.example.app", "Example", 42, "safe", True),
            AppEntry("com.other.app", "Other", 7, "safe", True)]
    copy = _copy()
    res = _run(phone, copy, _inventory(phone, apps),
               _sel(categories=frozenset(), apps=frozenset({"com.example.app"})))
    assert res.status == "complete"
    assert (res.apps_done, res.apps_failed) == (1, 0)
    target = copy.apps_dir / "com.example.app" / "42"
    manifest = json.loads((target / COMPLETE).read_text(encoding="utf-8"))
    assert manifest["package"] == "com.example.app"
    assert (target / "base.apk").read_bytes() == b"base-bytes"
    assert sorted(p.name for p in copy.apps_dir.iterdir()) == ["com.example.app"]
    assert sorted(p.name for p in (copy.apps_dir / "com.example.app").iterdir()) == ["42"]
    assert not (copy.apps_dir / "com.other.app").exists()
    assert not (copy.path / ".apk-tmp").exists()
    assert copy.read_meta().counts["apps"] == 1
    # poza `pm path` tego pakietu na telefon szły wyłącznie odczyty z allowlisty
    for command in phone.commands:
        if command != "pm path com.example.app":
            assert_read_only(command)


def test_app_failure_makes_copy_incomplete(tmp_path):
    phone = _phone(tmp_path)  # pakietu nie ma na telefonie: `pm path` zwraca błąd
    copy = _copy()
    res = _run(phone, copy, _inventory(phone, [AppEntry("com.gone.app", "Gone", 1, "safe", True)]),
               _sel(categories=frozenset(), apps=frozenset({"com.gone.app"})))
    assert res.status == "incomplete"
    assert (res.apps_done, res.apps_failed) == (0, 1)
    assert copy.read_meta().status == "incomplete"
