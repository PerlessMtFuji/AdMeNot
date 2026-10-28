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
from faketransfer import FakeStoragePhone, PhoneHost, TransferPhone
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
    assert done["result"]["telephony"]["contacts"] == {"status": "ok", "count": 2, "error": None, "source": "phone"}
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
    assert backup_result_view(r)["telephony"]["mms"] == {
        "status": "failed", "count": 4, "error": "addresses_missing:3", "source": "phone"}


def test_backup_result_view_source():
    from admenot.app.present import backup_result_view
    from admenot.engine.transfer.backup import BackupResult
    from admenot.engine.transfer.telephony import CategoryResult

    r = BackupResult("complete", "S/1", {"contacts": CategoryResult("ok", 3, None, "export")}, 0, 0, 0, 0, 0, 1)
    assert backup_result_view(r)["telephony"]["contacts"] == {
        "status": "ok", "count": 3, "error": None, "source": "export"}


# --- pliki eksportu zamiast odczytu providera ---------------------------------------------------

VCF_OLD = "".join(f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Osoba {i}\r\nEND:VCARD\r\n" for i in range(2))
VCF_NEW = "".join(f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Osoba {i}\r\nEND:VCARD\r\n" for i in range(3))
SMS_XML = ('<?xml version=\'1.0\' encoding=\'UTF-8\' standalone=\'yes\' ?>\n<smses count="2">\n'
           '<sms address="1" body="a" />\n<sms address="2" body="b" />\n</smses>\n')


def _put(phone: TransferPhone, rel: str, data: str, mtime: int = MTIME) -> str:
    path = phone.storage.local("/sdcard/" + rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return "/sdcard/" + rel


def _denied(tmp_path):
    phone = _phone(tmp_path)
    phone.storage.deny_uris = {"content://com.android.contacts/contacts", "content://sms"}
    old = _put(phone, "Kopia/stare.vcf", VCF_OLD, MTIME - 100)
    new = _put(phone, "Kopia/nowe.vcf", VCF_NEW, MTIME)
    sms = _put(phone, "Backup/sms.xml", SMS_XML)
    api, rec = _api(phone)
    assert "error" not in api.transfer_inventory(SERIAL, "Anna K.")
    return api, rec, phone, old, new, sms


def test_start_backup_with_export_choice(tmp_path, monkeypatch):
    api, rec, _, old, _new, sms = _denied(tmp_path)
    inv = rec.of("transfer:inventory")[0]["inventory"]
    assert inv["denied"] == ["contacts", "sms"] and set(inv["exports"]) == {"contacts", "sms"}
    seen = []
    real = backup_mod.run_backup

    def spy(adb, puller, device, copy, inventory, chosen, **kw):
        seen.append(chosen)
        return real(adb, puller, device, copy, inventory, chosen, **kw)

    monkeypatch.setattr("admenot.app.api.run_backup", spy)
    selection = {**SELECTION, "mms": True, "calls": False, "categories": [], "others": [], "apps": [],
                 "exports": {"contacts": old, "sms": sms}}
    assert "job_id" in api.start_backup(selection)
    (chosen,) = seen
    stat = {e.remote: e for kind in ("contacts", "sms") for e in api._transfer[1].exports[kind]}
    assert {(c.kind, c.remote, c.size, c.mtime) for c in chosen.exports} == {
        ("contacts", old, stat[old].size, stat[old].mtime), ("sms", sms, stat[sms].size, stat[sms].mtime)}
    assert chosen.mms is False
    done = rec.of("transfer:done")[0]
    assert done["result"]["telephony"]["contacts"] == {
        "status": "ok", "count": 2, "error": None, "source": "export"}
    assert done["result"]["telephony"]["sms"]["source"] == "export"


@pytest.mark.parametrize("exports", [
    {"contacts": "/sdcard/Inna/obca.vcf"},           # ścieżka spoza kandydatów
    {"photos": "/sdcard/Kopia/nowe.vcf"},            # nieznany rodzaj
    {"calls": "/sdcard/Kopia/nowe.vcf"},             # rodzaj bez kandydatów
    {"contacts": 5},                                  # zły typ
    ["contacts"],                                     # zły kształt
])
def test_start_backup_rejects_unknown_export(tmp_path, exports):
    api, *_ = _denied(tmp_path)
    assert api.start_backup({**SELECTION, "exports": exports})["error"]["key"] == "bad_request"


def test_start_backup_rejects_export_with_flag_off(tmp_path):
    api, _, _, _, new, _ = _denied(tmp_path)
    selection = {**SELECTION, "contacts": False, "exports": {"contacts": new}}
    assert api.start_backup(selection)["error"]["key"] == "bad_request"


def test_transfer_rescan_without_inventory_is_refused(tmp_path):
    api, _ = _api(_phone(tmp_path))
    assert api.transfer_rescan()["error"]["key"] == "transfer_no_inventory"


def test_transfer_rescan_emits_inventory(tmp_path, monkeypatch):
    api, rec, phone, *_ = _denied(tmp_path)
    before = rec.of("transfer:inventory")[0]
    assert len(before["inventory"]["exports"]["contacts"]) == 2
    _put(phone, "Pobrane/jeszcze-nowsze.vcf", VCF_NEW, MTIME + 50)
    monkeypatch.setattr("admenot.app.api.run_scan",
                        lambda *a, **k: pytest.fail("rescan nie skanuje aplikacji od nowa"))
    assert "job_id" in api.transfer_rescan()
    events = rec.of("transfer:inventory")
    assert len(events) == 2
    after = events[1]
    assert after["inventory"]["exports"]["contacts"][0]["name"] == "jeszcze-nowsze.vcf"
    assert len(after["inventory"]["exports"]["contacts"]) == 3
    assert after["inventory"]["apps"] == before["inventory"]["apps"]
    assert after["client"] == "Anna K." and after["resumable"] is None
    assert api._transfer[1].exports["contacts"][0].remote.endswith("jeszcze-nowsze.vcf")


# --- Etap 2: wgrywanie kopii na nowy telefon -----------------------------------------------------

NEW = "R58NEW00001"
ALL_GROUPS = ["photos", "videos", "downloads", "whatsapp", "other:Music", "other:"]
CHOICE = {"groups": ALL_GROUPS, "apks_on": [], "verify_hash": False}


def _new_phone(tmp_path: Path, files: dict[str, bytes] | None = None) -> TransferPhone:
    root = tmp_path / "new-phone"
    (root / "sdcard").mkdir(parents=True)
    for rel, data in (files or {}).items():
        path = root / "sdcard" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (MTIME, MTIME))
    return TransferPhone(make_cli_phone(), FakeStoragePhone(root, serial=NEW))


def _copied(tmp_path, extra: dict[str, bytes] | None = None, **kw):
    """Kopia Etapu 1 ze starego telefonu (przez most) i nowy telefon obok: (api, rec, host, id kopii)."""
    old = _phone(tmp_path)
    for rel, data in (extra or {}).items():
        path = old.storage.local("/sdcard/" + rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (MTIME, MTIME))
    host = PhoneHost(old, _new_phone(tmp_path))
    api, rec = make_api(host, puller_factory=lambda adb_path, serial, log: host.phone(serial),
                        pusher_factory=lambda adb_path, serial, log: host.phone(serial), **kw)
    api.transfer_inventory(SERIAL, "Anna K.")
    assert api._jobs.wait(5)
    api.start_backup(SELECTION)
    assert api._jobs.wait(5)
    copy_id = rec.wait_for("transfer:done")["copy"]["id"]
    return api, rec, host, copy_id


def _planned(api, rec, copy_id: str, serial: str = NEW) -> dict:
    assert "job_id" in api.restore_plan(copy_id, serial)
    assert api._jobs.wait(5)
    return rec.of("transfer:restore_plan")[-1]


def test_restore_plan_emits_view(tmp_path):
    api, rec, host, copy_id = _copied(tmp_path)
    event = _planned(api, rec, copy_id)
    assert rec.of("scan:device")[-1]["device"]["serial"] == NEW
    plan = event["plan"]
    assert plan["groups"] == {
        "photos": {"files": 2, "bytes": 500, "exists": 0, "rename": 0},
        "videos": {"files": 0, "bytes": 0, "exists": 0, "rename": 0},
        "downloads": {"files": 1, "bytes": len(FILES["Download/c.pdf"]), "exists": 0, "rename": 0},
        "whatsapp": {"files": 0, "bytes": 0, "exists": 0, "rename": 0}}
    assert plan["others"] == [
        {"name": "", "files": 1, "bytes": len(FILES["notes.txt"]), "exists": 0, "rename": 0},
        {"name": "Music", "files": 1, "bytes": 40, "exists": 0, "rename": 0}]
    assert plan["apks"] == [] and plan["missing"] == 0
    assert plan["space"] == {"free": 70_000_000 * 1024, "total": 120_000_000 * 1024}
    assert plan["reserve"] == 120_000_000 * 1024 // 20
    assert event["resumable"] is False and event["same_phone_recent"] is False
    assert event["copy"]["id"] == copy_id and event["copy"]["restores"] == []
    assert not (store.transfers_dir() / copy_id / "restore").exists()  # plan nie zakłada stanu
    assert host.phone(NEW).storage.pushed == []


def test_restore_plan_rejects_bad_copy(tmp_path):
    api, _, _, copy_id = _copied(tmp_path)
    assert api.restore_plan("../x", NEW)["error"]["key"] == "bad_request"
    assert api.restore_plan(copy_id, "")["error"]["key"] == "bad_request"


def test_same_phone_recent_flag(tmp_path):
    api, rec, _, copy_id = _copied(tmp_path)
    assert _planned(api, rec, copy_id, SERIAL)["same_phone_recent"] is True
    copy = store.CopyDir(store.transfers_dir() / copy_id)
    meta = copy.read_meta()
    meta.created = NOW - timedelta(hours=25)
    copy.write_meta(meta)
    assert _planned(api, rec, copy_id, SERIAL)["same_phone_recent"] is False
    assert _planned(api, rec, copy_id, NEW)["same_phone_recent"] is False


def test_start_restore_completes(tmp_path):
    api, rec, host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    assert "job_id" in api.start_restore(CHOICE)
    done = rec.of("transfer:restore_done")[0]
    result = done["result"]
    assert result["status"] == "complete" and result["target_serial"] == NEW
    assert (result["files_done"], result["files_exists"], result["files_missing"]) == (5, 0, 0)
    assert result["media_scan"] == "done" and result["hashed"] is False
    assert rec.of("transfer:restore_progress")
    assert done["copy"]["id"] == copy_id
    new = host.phone(NEW).storage
    for rel, data in FILES.items():
        assert new.local("/sdcard/" + rel).read_bytes() == data, rel
    restores = api.transfers()["copies"][0]["restores"]
    assert [(r["serial"], r["status"], r["resumable"]) for r in restores] == [(NEW, "complete", False)]
    assert restores[0]["updated"].endswith("+00:00")
    # skończone wgrywanie nie jest proponowane do wznowienia; drugi plan widzi pliki jako „już są”
    again = _planned(api, rec, copy_id)
    assert again["resumable"] is False and again["plan"]["groups"]["photos"]["exists"] == 2


def test_restore_resume_offered(tmp_path):
    from admenot.engine.transfer.restore_state import RestoreRow, RestoreState, restore_state_path

    api, rec, _, copy_id = _copied(tmp_path)
    copy = store.CopyDir(store.transfers_dir() / copy_id)
    state = RestoreState(restore_state_path(copy, NEW))
    state.set_meta("serial", NEW)
    state.set_meta("status", "stopped")
    state.set_meta("updated", "2026-09-26T12:00:00+00:00")
    state.insert(RestoreRow("/sdcard/DCIM/Camera/a.jpg", "/sdcard/DCIM/Camera/a.jpg", "photos", 300,
                            MTIME, "pending", 0, None))
    state.close()
    event = _planned(api, rec, copy_id)
    assert event["resumable"] is True
    assert event["copy"]["restores"] == [{"serial": NEW, "status": "stopped",
                                          "updated": "2026-09-26T12:00:00+00:00", "resumable": True}]
    assert _planned(api, rec, copy_id, SERIAL)["resumable"] is False  # stan innego telefonu


def test_running_restore_after_hard_kill_shown_stopped(tmp_path):
    """Stan `running` bez trwającego zadania `restore` (program zabity) → w widoku kopii `stopped`;
    w trakcie wgrywania tej kopii — `running`."""
    from admenot.engine.transfer.restore_state import RestoreRow, RestoreState, restore_state_path

    api, rec, host, copy_id = _copied(tmp_path)
    copy = store.CopyDir(store.transfers_dir() / copy_id)
    state = RestoreState(restore_state_path(copy, NEW))
    state.set_meta("serial", NEW)
    state.set_meta("status", "running")
    state.set_meta("updated", "2026-09-26T12:00:00+00:00")
    state.insert(RestoreRow("/sdcard/DCIM/Camera/a.jpg", "/sdcard/DCIM/Camera/a.jpg", "photos", 300,
                            MTIME, "pushing", 0, None))
    state.close()
    (entry,) = api.transfers()["copies"][0]["restores"]
    assert (entry["status"], entry["resumable"]) == ("stopped", True)
    assert _planned(api, rec, copy_id)["copy"]["restores"][0]["status"] == "stopped"

    seen: list[str] = []

    def during(command: str) -> None:
        if command.startswith("mkdir ") and not seen:
            seen.append(api.transfers()["copies"][0]["restores"][0]["status"])

    host.phone(NEW).storage.on_shell = during
    api.start_restore(CHOICE)
    assert seen == ["running"]
    assert rec.of("transfer:restore_done")[0]["copy"]["restores"][0]["status"] == "complete"


def test_finished_incomplete_upload_is_not_resumable(tmp_path):
    """Skończone wgrywanie z odmową Androida (`denied`, bez plików w kolejce) to wynik, nie przerwanie:
    ani widok kopii, ani plan nie proponują wznowienia."""
    api, rec, host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    host.phone(NEW).storage.deny_prefixes.add("/sdcard/Music")
    api.start_restore(CHOICE)
    result = rec.of("transfer:restore_done")[0]["result"]
    assert result["status"] == "incomplete" and result["files_denied"] == 1
    (entry,) = api.transfers()["copies"][0]["restores"]
    assert (entry["status"], entry["resumable"]) == ("incomplete", False)
    assert _planned(api, rec, copy_id)["resumable"] is False


def test_restore_phone_full_maps_to_job_error(tmp_path):
    api, rec, host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    host.phone(NEW).storage.free_kb = 1000
    api.start_restore(CHOICE)
    assert rec.of("job:error")[-1]["key"] == "transfer_phone_full"
    assert not rec.of("transfer:restore_done")
    (entry,) = api.transfers()["copies"][0]["restores"]
    assert (entry["status"], entry["resumable"]) == ("phone_full", True)  # przerwane: pliki w kolejce


def test_start_restore_rejects_unknown_group(tmp_path):
    api, rec, _, copy_id = _copied(tmp_path)
    assert api.start_restore(CHOICE)["error"]["key"] == "transfer_no_plan"
    _planned(api, rec, copy_id)
    for bad in ({**CHOICE, "groups": ["Music"]}, {**CHOICE, "groups": ["other:Nope"]},
                {**CHOICE, "groups": "photos"}, {**CHOICE, "apks_on": ["/sdcard/Download/x.apk"]},
                {**CHOICE, "verify_hash": "yes"}, ["photos"]):
        assert api.start_restore(bad)["error"]["key"] == "bad_request", bad
    assert not rec.of("transfer:restore_done")


def test_failed_replan_drops_previous_plan(tmp_path):
    api, rec, host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    host.phone(NEW).storage.online = False  # `stat` planu dostaje AdbError
    api.restore_plan(copy_id, NEW)
    assert rec.of("job:error")
    host.phone(NEW).storage.reconnect()
    assert api.start_restore(CHOICE)["error"]["key"] == "transfer_no_plan"


def test_start_restore_refused_when_new_phone_is_gone(tmp_path):
    api, rec, host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    host.connected.discard(NEW)
    assert api.start_restore(CHOICE)["error"]["key"] == "transfer_no_plan"


def test_purge_skips_copy_being_restored(tmp_path):
    api, rec, host, copy_id = _copied(tmp_path, sync=False, transfer_purge_s=None, poll_interval=0.01)
    _planned(api, rec, copy_id)
    copy = store.CopyDir(store.transfers_dir() / copy_id)
    meta = copy.read_meta()
    meta.expires = NOW - timedelta(days=1)
    copy.write_meta(meta)
    new = host.phone(NEW).storage
    new.fail_after_push_files = 0  # pierwszy plik urwany, telefon znika: zadanie czeka na telefon
    api.start_restore(CHOICE)
    try:
        rec.wait_for("transfer:waiting")
        api._purge_transfers()
        api.transfers()
        assert copy.path.exists()
        assert api.delete_transfer(copy_id)["error"]["key"] == "busy"
    finally:
        new.fail_after_push_files = None
        new.reconnect()
    assert rec.wait_for("transfer:restore_done")["result"]["status"] == "complete"
    assert api._jobs.wait(5)
    api._purge_transfers()  # po wgraniu kopia po terminie znika jak każda inna
    assert not copy.path.exists()


def test_restore_telemetry_has_no_paths(tmp_path, monkeypatch):
    from admenot.engine.transfer import restore_plan as rp
    from admenot.engine.transfer.apkcheck import ApkCheck

    monkeypatch.setattr(rp, "load_or_check", lambda copy, files: [
        ApkCheck(remote, "com.evil.game", "suspicious", "static", False) for remote, _ in files])
    api, rec, _, copy_id = _copied(tmp_path, extra={"Download/gra.apk": b"PK" + b"g" * 70})
    api.set_telemetry(True, True)
    plan = _planned(api, rec, copy_id)["plan"]
    assert plan["apks"] == [{"remote": "/sdcard/Download/gra.apk", "name": "gra.apk", "group": "downloads",
                             "bytes": 72, "action": "push", "outcome": "suspicious", "level": "static",
                             "default_on": False}]
    api.start_restore(CHOICE)
    result = rec.of("transfer:restore_done")[0]["result"]
    assert result["apk_suspicious_skipped"] == 1 and result["files_done"] == 5
    events = [json.loads(x) for x in telemetry_path().read_text("utf-8").splitlines()]
    event = next(e for e in events if e["type"] == "transfer_restore")
    assert event["status"] == "complete" and event["files"] == 5 and event["apk_suspicious_skipped"] == 1
    assert event["groups"] == {"photos": True, "videos": True, "downloads": True, "whatsapp": True,
                               "others": True}
    assert event["streams"] == 4 and event["media_scan"] == "done" and event["missing"] == 0
    text = json.dumps(event)
    for name in ("DCIM", "Camera", "a.jpg", "Music", "notes.txt", "Download", "gra.apk", "com.evil.game",
                 "Anna", SERIAL, NEW, "sdcard"):
        assert name not in text, name
