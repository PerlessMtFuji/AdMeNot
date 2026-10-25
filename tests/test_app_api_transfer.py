"""Most GUI ↔ kopia danych starego telefonu (przenoszenie danych, Etap 1)."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from apphelpers import NOW, Disk, make_api
from conftest import SERIAL
from fakephone import make_cli_phone
from faketransfer import FakeStoragePhone, TransferPhone
from telephony_fixtures import install_telephony

from admenot.engine.device.info import DeviceInfo
from admenot.engine.paths import crashes_dir, telemetry_path
from admenot.engine.transfer import backup as backup_mod
from admenot.engine.transfer import store

MTIME = 1_700_000_000
FILES = {
    "DCIM/Camera/a.jpg": b"A" * 300,
    "DCIM/Camera/b.jpg": b"B" * 200,
    "Download/c.pdf": b"%PDF" + b"c" * 50,
    "Music/song.mp3": b"M" * 40,
    "notes.txt": b"loose file",
}
SELECTION = {"contacts": True, "sms": True, "mms": False, "calls": True,
             "categories": ["media", "downloads"], "others": ["Music", ""], "apps": ["com.whatsapp"]}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))


def _phone(tmp_path: Path) -> TransferPhone:
    root = tmp_path / "phone"
    for rel, data in FILES.items():
        path = root / "sdcard" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (MTIME, MTIME))
    install_telephony(root, mms=False)
    storage = FakeStoragePhone(root, serial=SERIAL)
    storage.apps = {"com.whatsapp": {"base.apk": b"PK-whatsapp"}}
    return TransferPhone(make_cli_phone(), storage)


def _api(phone: TransferPhone, **kw):
    return make_api(phone, puller_factory=lambda adb_path, serial, log: phone, **kw)


def _device() -> DeviceInfo:
    return DeviceInfo(serial=SERIAL, brand="samsung", manufacturer="samsung", model="SM-A145R",
                      device="a14", market_name=None, android_release="14", sdk=34,
                      security_patch=None, uptime_s=1.0, local_now=NOW)


def _inventoried(tmp_path, **kw):
    phone = _phone(tmp_path)
    api, rec = _api(phone, **kw)
    assert "error" not in api.transfer_inventory(SERIAL, "Anna K.")
    return api, rec, phone


def test_transfer_inventory_emits_view(tmp_path):
    _, rec, _ = _inventoried(tmp_path)
    assert rec.of("scan:device")[0]["device"]["serial"] == SERIAL
    event = rec.of("transfer:inventory")[0]
    inv = event["inventory"]
    assert event["resumable"] is None and event["client"] == "Anna K."
    assert (inv["contacts"], inv["sms"], inv["calls"]) == (2, 2, 1)
    assert inv["categories"]["media"] == {"files": 2, "bytes": 500}
    assert inv["categories"]["downloads"] == {"files": 1, "bytes": len(FILES["Download/c.pdf"])}
    assert inv["categories"]["whatsapp"] == {"files": 0, "bytes": 0}
    assert inv["others"] == [{"name": "", "files": 1, "bytes": len(FILES["notes.txt"])},
                             {"name": "Music", "files": 1, "bytes": 40}]
    assert {a["package"] for a in inv["apps"]} == {"com.whatsapp", "com.wlive.forecast"}
    assert all(a["bytes"] is None for a in inv["apps"])
    assert inv["skipped_apps"] == [{"package": "com.clean.pro.boost", "label": "com.clean.pro.boost"}]
    assert inv["storage"]["total"] > inv["storage"]["used"] > 0
    assert isinstance(inv["free_pc"], int) and inv["unreadable"] == 0


def test_start_backup_without_inventory_is_refused(tmp_path):
    api, _ = _api(_phone(tmp_path))
    assert api.start_backup(SELECTION)["error"]["key"] == "transfer_no_inventory"


def test_start_backup_rejects_bad_selection(tmp_path):
    api, _, _ = _inventoried(tmp_path)
    assert api.start_backup({**SELECTION, "categories": ["Music"]})["error"]["key"] == "bad_request"
    assert api.start_backup({**SELECTION, "sms": "yes"})["error"]["key"] == "bad_request"


def test_start_backup_completes_and_lists(tmp_path):
    api, rec, _ = _inventoried(tmp_path)
    assert "job_id" in api.start_backup(SELECTION)
    done = rec.of("transfer:done")[0]
    assert done["result"]["status"] == "complete"
    assert done["result"]["files_done"] == 5 and done["result"]["apps_done"] == 1
    assert done["result"]["telephony"]["contacts"] == {"status": "ok", "count": 2, "error": None}
    assert done["copy"]["status"] == "complete" and done["copy"]["client"] == "Anna K."
    assert rec.of("transfer:progress")
    copies = api.transfers()["copies"]
    assert len(copies) == 1
    assert copies[0]["days_left"] == 7 and copies[0]["id"] == done["copy"]["id"]
    assert copies[0]["serial"] == SERIAL  # baner „Wznów” na ekranie Połącz trafia w ten telefon
    assert copies[0]["counts"]["files"] == 5
    # wybór zapisany w kopii wraca w widoku — wznowienie zaczyna od niego
    assert copies[0]["selection"]["others"] == ["", "Music"]
    assert copies[0]["selection"]["apps"] == ["com.whatsapp"] and copies[0]["selection"]["mms"] is False


def test_backup_error_maps_to_job_error(tmp_path, monkeypatch):
    api, rec, _ = _inventoried(tmp_path)
    monkeypatch.setattr(backup_mod.shutil, "disk_usage", lambda path: Disk(10, 10, 0))
    api.start_backup(SELECTION)
    assert rec.of("job:error")[0]["key"] == "transfer_disk_full"
    assert not rec.of("transfer:done")
    assert api.transfers()["copies"][0]["status"] == "in_progress"


def test_inventory_offers_resume(tmp_path):
    copy = store.create_copy(SERIAL, _device(), "Anna K.", NOW)
    api, rec, _ = _inventoried(tmp_path)
    resumable = rec.of("transfer:inventory")[0]["resumable"]
    assert resumable is not None and resumable["id"] == copy.read_meta().id
    assert resumable["status"] == "in_progress"
    api.start_backup(SELECTION)  # wznawia tę kopię zamiast zakładać nową
    copies = api.transfers()["copies"]
    assert [c["id"] for c in copies] == [resumable["id"]] and copies[0]["status"] == "complete"


def test_extend_transfer(tmp_path):
    copy = store.create_copy(SERIAL, _device(), None, NOW)
    api, _ = _api(_phone(tmp_path))
    copy_id = copy.read_meta().id
    view = api.extend_transfer(copy_id)["copy"]
    assert view["days_left"] == 14
    assert view["expires"] == (NOW + timedelta(days=14)).isoformat(timespec="seconds")
    assert api.extend_transfer("../x")["error"]["key"] == "bad_request"


def test_delete_transfer(tmp_path):
    copy = store.create_copy(SERIAL, _device(), None, NOW)
    api, _ = _api(_phone(tmp_path))
    copy_id = copy.read_meta().id
    assert api.delete_transfer(copy_id) == {"deleted": copy_id}
    assert api.transfers()["copies"] == []
    assert api.delete_transfer(copy_id)["error"]["key"] == "bad_request"


def _held_backup(tmp_path):
    """Kopia w toku (sync=False) zatrzymana w pierwszym `pull` do `release.set()`."""
    api, rec, phone = _inventoried(tmp_path, sync=False, transfer_purge_s=None)
    assert api._jobs.wait(5)
    entered, release = threading.Event(), threading.Event()

    def hold(remotes):
        entered.set()
        release.wait(5)

    phone.storage.before_pull = hold
    api.start_backup(SELECTION)
    assert entered.wait(5)
    return api, rec, release


def test_delete_transfer_busy(tmp_path):
    api, rec, release = _held_backup(tmp_path)
    try:
        copy_id = api.transfers()["copies"][0]["id"]
        assert api.delete_transfer(copy_id)["error"]["key"] == "busy"
    finally:
        release.set()
    rec.wait_for("transfer:done")
    assert api._jobs.wait(5)
    assert api.delete_transfer(copy_id) == {"deleted": copy_id}


def test_purge_skips_copy_of_busy_phone(tmp_path):
    api, rec, release = _held_backup(tmp_path)
    try:
        old = store.create_copy(SERIAL, _device(), None, NOW - timedelta(days=8))
        api.transfers()
        assert old.path.exists()  # telefon zajęty kopią: nic z jego kopii nie znika
    finally:
        release.set()
    rec.wait_for("transfer:done")
    assert api._jobs.wait(5)
    api.transfers()
    assert not old.path.exists()


def test_closing_window_during_backup_does_not_wait(tmp_path):
    api, rec, release = _held_backup(tmp_path)
    closed = threading.Event()
    api._attach(pick_folder=lambda: None, close=closed.set)
    started = time.monotonic()
    try:
        assert api._on_closing() is False  # wątek GUI wraca od razu
        assert time.monotonic() - started < 1.0
        assert not closed.is_set()
    finally:
        release.set()
    assert closed.wait(5)  # okno zamyka się samo po porządnym zatrzymaniu kopii
    assert rec.wait_for("transfer:done")["result"]["status"] == "stopped"
    assert api.transfers()["copies"][0]["status"] == "in_progress"
    assert api._on_closing() is True


def _offline_after_first_file(phone, on_offline):
    """Pull urywa się po pierwszym pliku; każde `get-state` bez telefonu woła `on_offline(n)`."""
    phone.storage.fail_after_files = 1
    real = phone.storage.run
    calls = {"n": 0}

    def run(args, timeout=20.0):
        if args == ["get-state"] and not phone.storage.online:
            calls["n"] += 1
            on_offline(calls["n"])
        return real(args, timeout)

    phone.storage.run = run


def test_wait_device_emits_waiting_once_and_resumes(tmp_path):
    api, rec, phone = _inventoried(tmp_path, poll_interval=0.0)

    def back_after_three(n):
        if n >= 4:
            phone.storage.fail_after_files = None
            phone.storage.reconnect()

    _offline_after_first_file(phone, back_after_three)
    api.start_backup(SELECTION)
    assert len(rec.of("transfer:waiting")) == 1
    assert rec.of("transfer:done")[0]["result"]["status"] == "complete"
    # telefon wrócił: od razu postęp (UI chowa „Telefon odłączony”), mimo dławienia zdarzeń
    after = [(n, d) for n, d in rec.events if n.startswith("transfer:")]
    i = [n for n, _ in after].index("transfer:waiting")
    assert after[i + 1][0] == "transfer:progress" and after[i + 1][1]["stage"] == "files"


def test_stop_while_waiting_for_phone_finishes_as_stopped(tmp_path):
    api, rec, phone = _inventoried(tmp_path, poll_interval=0.0)
    api.set_telemetry(True, False)

    def stop(n):
        if n >= 3:
            api.stop(api._jobs.current().id)

    _offline_after_first_file(phone, stop)
    api.start_backup(SELECTION)
    assert len(rec.of("transfer:waiting")) == 1
    done = rec.of("transfer:done")[0]
    assert done["result"]["status"] == "stopped" and done["copy"]["status"] == "in_progress"
    # przerwana kopia: Historia i wznowienie widzą, ile już skopiowano
    assert done["copy"]["bytes"] == done["result"]["bytes"] > 0
    assert done["copy"]["counts"]["files"] == done["result"]["files_done"] >= 1
    assert not rec.of("job:error")
    events = [json.loads(x) for x in telemetry_path().read_text("utf-8").splitlines()]
    assert [e["status"] for e in events if e["type"] == "transfer_backup"] == ["stopped"]


def test_start_backup_refused_when_phone_is_gone(tmp_path):
    api, _, phone = _inventoried(tmp_path)
    phone.cli.host["devices -l"] = "List of devices attached\n\n"
    assert api.start_backup(SELECTION)["error"]["key"] == "transfer_no_inventory"
    assert api.transfer_whatsapp()["error"]["key"] == "transfer_no_inventory"


def test_unexpected_backup_error_has_fixed_key_and_no_file_names(tmp_path, monkeypatch):
    api, rec, _ = _inventoried(tmp_path)

    def broken(*args, **kwargs):
        message = "cannot read '/sdcard/DCIM/Camera/a.jpg' into " + str(
            store.transfers_dir() / "x" / "files" / "DCIM" / "a.jpg")
        raise RuntimeError(message)

    monkeypatch.setattr("admenot.app.api.run_backup", broken)
    api.start_backup(SELECTION)
    error = rec.of("job:error")[0]
    assert error["key"] == "transfer_failed" and error["message"] == "RuntimeError"
    report = json.loads((crashes_dir() / f"{error['crash']}.json").read_text("utf-8"))
    text = json.dumps(report)
    assert report["context"]["job"] == "backup" and "<path>" in report["error"]["message"]
    for name in ("DCIM", "Camera", "a.jpg"):
        assert name not in text, name
    log = Path(error["log"]).read_text("utf-8")  # lokalny app-*.log też bez nazw plików klienta
    assert "RuntimeError" in log and "<path>" in log
    for name in ("Camera", "a.jpg"):
        assert name not in log, name


def test_delete_and_extend_of_locked_copy_have_a_friendly_key(tmp_path, monkeypatch):
    copy = store.create_copy(SERIAL, _device(), None, NOW)
    api, _ = _api(_phone(tmp_path))
    copy_id = copy.read_meta().id
    locked = str(copy.files_dir / "DCIM" / "urlop.jpg")

    def deny(*args, **kwargs):
        raise PermissionError(13, "Permission denied", locked)

    monkeypatch.setattr(store.shutil, "rmtree", deny)
    error = api.delete_transfer(copy_id)["error"]
    assert error["key"] == "transfer_in_use" and "urlop" not in json.dumps(error)
    monkeypatch.setattr(store.CopyDir, "write_meta", deny)
    error = api.extend_transfer(copy_id)["error"]
    assert error["key"] == "transfer_in_use" and "urlop" not in json.dumps(error)


def test_purge_on_start(tmp_path):
    old = store.create_copy(SERIAL, _device(), None, NOW - timedelta(days=8))
    fresh = store.create_copy(SERIAL, _device(), None, NOW - timedelta(days=1))
    api, _ = _api(_phone(tmp_path))
    assert not old.path.exists() and fresh.path.exists()
    assert [c["id"] for c in api.transfers()["copies"]] == [fresh.read_meta().id]


def test_transfer_whatsapp(tmp_path):
    api, _, phone = _inventoried(tmp_path)
    assert api.transfer_whatsapp() == {"whatsapp_backup": None}
    db = phone.storage.root / "sdcard" / "WhatsApp" / "Databases" / "msgstore.db.crypt14"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"x")
    os.utime(db, (MTIME, MTIME))
    from datetime import datetime
    expected = datetime.fromtimestamp(MTIME).isoformat(timespec="seconds")
    assert api.transfer_whatsapp() == {"whatsapp_backup": expected}


def test_transfer_telemetry_has_no_paths(tmp_path):
    api, _, _ = _inventoried(tmp_path)
    api.set_telemetry(True, True)
    api.start_backup(SELECTION)
    events = [json.loads(x) for x in telemetry_path().read_text("utf-8").splitlines()]
    event = next(e for e in events if e["type"] == "transfer_backup")
    assert event["status"] == "complete" and event["files"] == 5 and event["apps"] == 1
    assert event["categories"] == {"contacts": True, "sms": True, "mms": False, "calls": True,
                                   "media": True, "downloads": True, "whatsapp": False,
                                   "others": True, "apps": True}
    text = json.dumps(event)
    for name in ("DCIM", "Music", "Camera", "a.jpg", "notes.txt", "Download", "com.whatsapp",
                 "Anna", SERIAL):
        assert name not in text, name


def test_transfer_telemetry_off_without_consent(tmp_path):
    api, _, _ = _inventoried(tmp_path)
    api.start_backup(SELECTION)
    assert not telemetry_path().exists()


def test_backup_result_view_keeps_telephony_error():
    from admenot.app.present import backup_result_view
    from admenot.engine.transfer.backup import BackupResult
    from admenot.engine.transfer.telephony import CategoryResult

    r = BackupResult("incomplete", "S/1", {"mms": CategoryResult("failed", 4, "addresses_missing:3")}, 0, 0, 0, 0, 0, 1)
    assert backup_result_view(r)["telephony"]["mms"] == {"status": "failed", "count": 4, "error": "addresses_missing:3"}
