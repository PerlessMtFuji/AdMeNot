from __future__ import annotations

import csv
import errno
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from faketransfer import FakeStoragePhone
from telephony_fixtures import install_telephony

from admenot.engine.actions.backup import COMPLETE
from admenot.engine.adb.transport import AdbError
from admenot.engine.device.info import DeviceInfo
from admenot.engine.transfer import backup as backup_mod
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


def test_progress_counts_apps(tmp_path):
    """Pliki kończą się przed aplikacjami: bez licznika aplikacji ekran pokazuje „wszystko”, a kopia trwa."""
    phone = _phone(tmp_path)
    phone.apps = {"com.example.app": {"base.apk": b"base-bytes"}}
    apps = [AppEntry("com.example.app", "Example", 42, "safe", True), AppEntry("com.gone.app", "Gone", 1, "safe", True)]
    seen: list[Progress] = []
    _run(phone, _copy(), _inventory(phone, apps), _sel(apps=frozenset({"com.example.app", "com.gone.app"})),
         on_progress=seen.append)
    assert seen[0].total_apps == 2 and seen[0].done_apps == 0
    files_end = [p for p in seen if p.stage == "files"][-1]
    assert files_end.done_files == files_end.total_files and files_end.done_apps == 0
    assert (seen[-1].done_apps, seen[-1].total_apps) == (2, 2)  # nieudana też jest już obsłużona


def test_app_failure_makes_copy_incomplete(tmp_path):
    phone = _phone(tmp_path)  # pakietu nie ma na telefonie: `pm path` zwraca błąd
    copy = _copy()
    res = _run(phone, copy, _inventory(phone, [AppEntry("com.gone.app", "Gone", 1, "safe", True)]),
               _sel(categories=frozenset(), apps=frozenset({"com.gone.app"})))
    assert res.status == "incomplete"
    assert (res.apps_done, res.apps_failed) == (0, 1)
    assert copy.read_meta().status == "incomplete"


def test_apk_pull_cut_by_disconnect_waits_and_retries(tmp_path, monkeypatch):
    """Wyrwany kabel w trakcie `adb pull` APK daje `command_failed`, nie błąd połączenia
    (próba na Samsungu A13) — telefon offline znaczy rozłączenie, nie nieudaną aplikację."""
    phone = _phone(tmp_path)
    phone.apps = {"com.example.app": {"base.apk": b"base-bytes"}}
    original = backup_mod.backup_apks
    calls: list[int] = []

    def cut_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            phone.online = False
            raise AdbError("command_failed", "adb: error: failed to read copy response")
        return original(*args, **kwargs)

    monkeypatch.setattr(backup_mod, "backup_apks", cut_once)
    waits: list[int] = []

    def wait_device():
        waits.append(1)
        phone.reconnect()

    copy = _copy()
    res = _run(phone, copy, _inventory(phone, [AppEntry("com.example.app", "Example", 42, "safe", True)]),
               _sel(categories=frozenset(), apps=frozenset({"com.example.app"})), wait_device=wait_device)
    assert res.status == "complete"
    assert (res.apps_done, res.apps_failed) == (1, 0)
    assert len(waits) == 1


# ---- poprawki z przeglądu (runda 1) -----------------------------------------------------------

def _pull_leaves_partial(phone: FakeStoragePhone, remote: str) -> None:
    """`pull` tego pliku zostawia ucięty plik, a telefon zostaje online (to nie rozłączenie)."""
    original = phone.pull

    def pull(remotes, target, should_stop, tick):
        if remotes == [remote]:
            phone.fail_after_files = len(phone.pulled)
        res = original(remotes, target, should_stop, tick)
        phone.fail_after_files = None
        phone.online = True
        return res

    phone.pull = pull


def _no_wait():
    raise AssertionError("not a disconnect")


def test_stat_timeout_is_an_attempt_not_vanished(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    _pull_leaves_partial(phone, "/sdcard/Download/c.pdf")

    def on_shell(command):
        if command.startswith("stat "):
            raise AdbError("timeout", "stat (>120s)")

    phone.on_shell = on_shell
    res = _run(phone, copy, inv, _sel(), wait_device=_no_wait)
    row = _rows(copy)["/sdcard/Download/c.pdf"]
    assert (row.status, row.attempts, row.error) == ("error", 3, "pull_failed")
    assert res.status == "incomplete"


def test_sha256sum_missing_falls_back_to_size_and_is_recorded(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)

    def on_shell(command):
        if command.startswith("sha256sum "):
            raise AdbError("command_failed", "/system/bin/sh: sha256sum: inaccessible or not found")

    phone.on_shell = on_shell
    res = _run(phone, copy, inv, _sel(verify_hash=True))
    assert res.status == "complete"
    assert copy.read_meta().counts["size_only"] == 3
    assert all(r["sha256"] == "" for r in _manifest(copy))


def test_sha256sum_other_error_charges_attempts_per_file(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)

    def on_shell(command):
        if command.startswith("sha256sum ") and "c.pdf" in command:
            raise AdbError("timeout", "sha256sum (>3600s)")

    phone.on_shell = on_shell
    res = _run(phone, copy, inv, _sel(verify_hash=True), wait_device=_no_wait)
    rows = _rows(copy)
    assert (rows["/sdcard/Download/c.pdf"].status, rows["/sdcard/Download/c.pdf"].error) == (
        "error", "hash_unavailable")
    assert rows["/sdcard/DCIM/Camera/a.jpg"].sha256 == hashlib.sha256(FILES["DCIM/Camera/a.jpg"]).hexdigest()
    assert res.status == "incomplete"
    assert copy.read_meta().counts["size_only"] == 0


def test_hash_mismatch_is_repulled(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    calls = {"n": 0}
    original = phone.pull

    def pull(remotes, target, should_stop, tick):
        res = original(remotes, target, should_stop, tick)
        if remotes == ["/sdcard/Download/c.pdf"] and calls["n"] == 0:
            calls["n"] += 1
            local = copy.files_dir / "Download" / "c.pdf"
            data = bytearray(local.read_bytes())
            data[0] ^= 0xFF  # ta sama długość, inna treść
            local.write_bytes(bytes(data))
        return res

    phone.pull = pull
    res = _run(phone, copy, inv, _sel(verify_hash=True))
    assert res.status == "complete"
    row = _rows(copy)["/sdcard/Download/c.pdf"]
    assert (row.status, row.attempts) == ("done", 1)
    assert (copy.files_dir / "Download" / "c.pdf").read_bytes() == FILES["Download/c.pdf"]


def test_hash_mismatch_three_times_reason_in_manifest(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    original = phone.pull

    def pull(remotes, target, should_stop, tick):
        res = original(remotes, target, should_stop, tick)
        local = copy.files_dir / "Download" / "c.pdf"
        if "/sdcard/Download/c.pdf" in remotes and local.exists():
            local.write_bytes(b"X" * local.stat().st_size)
        return res

    phone.pull = pull
    res = _run(phone, copy, inv, _sel(verify_hash=True), wait_device=_no_wait)
    assert res.status == "incomplete"
    rows = {r["remote"]: r for r in _manifest(copy)}
    assert (rows["/sdcard/Download/c.pdf"]["status"], rows["/sdcard/Download/c.pdf"]["reason"]) == (
        "error", "hash_mismatch")
    assert rows["/sdcard/DCIM/Camera/a.jpg"]["reason"] == ""


def test_disk_full_before_telephony(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    issued = len(phone.commands)
    with pytest.raises(BackupError) as err:
        _run(phone, copy, inv, _sel(sms=True, categories=frozenset()), free_bytes=lambda p: 0)
    assert err.value.key == "disk_full"
    assert len(phone.commands) == issued  # nic nie eksportowano
    assert copy.read_meta().status == "in_progress"


def test_disk_full_before_apk(tmp_path):
    phone = _phone(tmp_path)
    phone.apps = {"com.example.app": {"base.apk": b"base"}}
    copy = _copy()
    inv = _inventory(phone, [AppEntry("com.example.app", "Example", 1, "safe", True)])
    with pytest.raises(BackupError) as err:
        _run(phone, copy, inv, _sel(categories=frozenset(), apps=frozenset({"com.example.app"})),
             free_bytes=lambda p: 0)
    assert err.value.key == "disk_full"
    assert not any(c.startswith("pm path") for c in phone.commands)


def _no_space(*args, **kwargs):
    raise OSError(errno.ENOSPC, "No space left on device")


def test_enospc_during_apk_copy_is_disk_full(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_mod, "backup_apks", _no_space)
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone, [AppEntry("com.example.app", "Example", 1, "safe", True)])
    with pytest.raises(BackupError) as err:
        _run(phone, copy, inv, _sel(categories=frozenset(), apps=frozenset({"com.example.app"})))
    assert err.value.key == "disk_full"
    assert copy.read_meta().status == "in_progress"


def test_enospc_during_telephony_is_disk_full(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_mod, "export_telephony", _no_space)
    phone = _phone(tmp_path)
    copy = _copy()
    with pytest.raises(BackupError) as err:
        _run(phone, copy, _inventory(phone), _sel(sms=True))
    assert err.value.key == "disk_full"


def test_second_run_after_disk_full_completes(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    with pytest.raises(BackupError):
        _run(phone, copy, inv, _sel(), free_bytes=lambda p: 0)
    res = _run(phone, copy, inv, _sel())
    assert res.status == "complete"
    assert copy.read_meta().status == "complete"
    assert len(_local_files(copy)) == 3


def test_too_many_disconnects_keeps_done_rows(tmp_path):
    phone = _phone(tmp_path)
    phone.fail_after_files = 0
    copy = _copy()
    waits: list[int] = []

    def wait_device():
        waits.append(1)
        phone.reconnect()
        if len(waits) == 20:  # następna paczka [a, b]: a przejdzie, b urwie się po raz 21.
            phone.fail_after_files = len(phone.pulled) + 1

    with pytest.raises(BackupError) as err:
        _run(phone, copy, _inventory(phone), _sel(), wait_device=wait_device)
    assert err.value.key == "too_many_disconnects"
    assert phone.pulled == ["/sdcard/DCIM/Camera/a.jpg"]
    assert _rows(copy)["/sdcard/DCIM/Camera/a.jpg"].status == "done"


def test_selected_app_missing_from_inventory_is_counted(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    res = _run(phone, copy, _inventory(phone), _sel(categories=frozenset(), apps=frozenset({"com.evil.app"})))
    assert (res.apps_done, res.apps_failed) == (0, 0)
    assert copy.read_meta().counts["apps_skipped"] == 1


def test_file_gone_between_runs_is_vanished_not_unselected(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    _run(phone, copy, inv, _sel(), should_stop=lambda: len(phone.pulled) >= 2)
    phone.local("/sdcard/Download/c.pdf").unlink()
    res = _run(phone, copy, _inventory(phone), _sel())
    assert res.status == "complete"
    rows = {r["remote"]: r for r in _manifest(copy)}
    assert (rows["/sdcard/Download/c.pdf"]["status"], rows["/sdcard/Download/c.pdf"]["reason"]) == (
        "skipped", "vanished")


def test_unselected_on_resume_is_not_selected(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    _run(phone, copy, inv, _sel(), should_stop=lambda: len(phone.pulled) >= 2)
    res = _run(phone, copy, inv, _sel(categories=frozenset({"media"})))
    assert res.status == "complete"
    rows = {r["remote"]: r for r in _manifest(copy)}
    assert (rows["/sdcard/Download/c.pdf"]["status"], rows["/sdcard/Download/c.pdf"]["reason"]) == (
        "skipped", "not_selected")
    assert copy.read_meta().selection["categories"] == ["media"]


def test_rerun_resets_status_to_in_progress(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    _pull_leaves_partial(phone, "/sdcard/Download/c.pdf")
    assert _run(phone, copy, inv, _sel(), wait_device=_no_wait).status == "incomplete"
    assert copy.read_meta().status == "incomplete"
    with pytest.raises(BackupError):
        _run(phone, copy, inv, _sel(categories=frozenset({"downloads"})), free_bytes=lambda p: 0)
    meta = copy.read_meta()
    assert meta.status == "in_progress"
    assert meta.selection["categories"] == ["downloads"]


def test_vanished_file_not_in_total(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    phone.before_pull = lambda remotes: phone.local("/sdcard/Download/c.pdf").unlink(missing_ok=True)
    progress: list[Progress] = []
    _run(phone, copy, inv, _sel(), on_progress=progress.append)
    assert (progress[-1].done_files, progress[-1].total_files) == (2, 2)
    assert progress[-1].total_bytes == progress[-1].done_bytes


def test_stop_during_telephony(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    asked = {"n": 0}

    def should_stop():
        asked["n"] += 1
        return asked["n"] > 1  # pierwsze pytanie przed eksportem, kolejne już w export_telephony

    res = _run(phone, copy, _inventory(phone), _sel(contacts=True, sms=True), should_stop=should_stop)
    assert res.status == "stopped"
    assert phone.pull_calls == 0
    assert copy.read_meta().status == "in_progress"
    assert not (copy.phone_dir / "sms.xml").exists()


def test_stop_mid_chunk_with_locked_partial_file_does_not_crash(tmp_path, monkeypatch):
    """Niedokończony plik zablokowany (np. antywirus): zostaje `pending`, kopia kończy się `stopped`."""
    phone = _phone(tmp_path)
    copy = _copy()
    partial = copy.files_dir / "DCIM" / "Camera" / "b.jpg"

    def leave_partial(remotes):
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(b"B" * 10)

    phone.before_pull = leave_partial
    real_unlink = Path.unlink

    def unlink(self, missing_ok=False):
        if self == partial:
            raise PermissionError(13, "Permission denied", str(self))
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    res = _run(phone, copy, _inventory(phone), _sel(), should_stop=lambda: len(phone.pulled) >= 1)
    assert res.status == "stopped"
    rows = _rows(copy)
    assert rows["/sdcard/DCIM/Camera/a.jpg"].status == "done"
    assert rows["/sdcard/DCIM/Camera/b.jpg"].status == "pending"


def test_stop_and_disk_full_record_bytes_and_counts_in_meta(tmp_path):
    """Przerwana kopia zostaje do wznowienia, ale `meta.json` ma już bajty i liczniki zrobionego."""
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    res = _run(phone, copy, inv, _sel(sms=True), should_stop=lambda: len(phone.pulled) >= 2)
    assert res.status == "stopped" and res.bytes == 500
    meta = copy.read_meta()
    assert meta.status == "in_progress" and meta.bytes == 500
    assert meta.counts["files"] == 2 and meta.counts["sms"] == 2

    copy2 = store.create_copy("FAKE", _device(), None, NOW.replace(minute=5))
    calls = {"n": 0}

    def free(path):  # pierwsza paczka (DCIM/Camera) się mieści, następna (Download) już nie
        calls["n"] += 1
        return 10 ** 12 if calls["n"] == 1 else 0

    with pytest.raises(BackupError):
        _run(phone, copy2, inv, _sel(), free_bytes=free)
    meta = copy2.read_meta()
    assert meta.status == "in_progress" and meta.bytes == 500 and meta.counts["files"] == 2


def test_unreadable_count_lands_in_meta(tmp_path):
    phone = _phone(tmp_path)
    copy = _copy()
    inv = _inventory(phone)
    inv.unreadable = 3
    assert _run(phone, copy, inv, _sel()).status == "complete"
    assert copy.read_meta().counts["unreadable"] == 3


def test_resume_after_expiry_keeps_the_copy_for_keep_days(tmp_path):
    phone = _phone(tmp_path)
    copy = store.create_copy("FAKE", _device(), None, NOW - timedelta(days=7, hours=1))
    _run(phone, copy, _inventory(phone), _sel(), now=NOW)
    assert copy.read_meta().expires == NOW + timedelta(days=store.KEEP_DAYS)
    fresh = _copy()  # termin daleko: bez zmian
    before = fresh.read_meta().expires
    _run(phone, fresh, _inventory(phone), _sel(), now=NOW + timedelta(days=2))
    assert fresh.read_meta().expires == before


def test_enospc_writing_meta_before_start_is_disk_full(tmp_path, monkeypatch):
    phone = _phone(tmp_path)
    copy = _copy()
    monkeypatch.setattr(store.CopyDir, "write_meta", _no_space)
    with pytest.raises(BackupError) as err:
        _run(phone, copy, _inventory(phone), _sel())
    assert err.value.key == "disk_full"


def test_sqlite_disk_full_is_disk_full(tmp_path, monkeypatch):
    phone = _phone(tmp_path)
    copy = _copy()

    def full(*args, **kwargs):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(State, "commit", full)
    with pytest.raises(BackupError) as err:
        _run(phone, copy, _inventory(phone), _sel())
    assert err.value.key == "disk_full"
