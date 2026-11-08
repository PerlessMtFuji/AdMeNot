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


def test_transfer_note(tmp_path):
    copy = store.create_copy(SERIAL, _device(), None, NOW)
    api, _ = _api(_phone(tmp_path))
    copy_id = copy.read_meta().id
    assert api.transfers()["copies"][0]["note"] is None
    view = api.set_transfer_note(copy_id, "  Klient chce tylko zdjęcia z 2025.\nTelefon z pękniętą szybką.  ")
    assert view["copy"]["note"] == "Klient chce tylko zdjęcia z 2025.\nTelefon z pękniętą szybką."
    assert api.transfers()["copies"][0]["note"] == view["copy"]["note"]
    copy.write_meta(copy.read_meta())  # kopia w toku przepisuje meta.json — notatka zostaje
    assert api.transfers()["copies"][0]["note"] == view["copy"]["note"]
    assert api.set_transfer_note(copy_id, "")["copy"]["note"] is None
    assert not (copy.path / store.NOTE).exists()
    assert api.set_transfer_note(copy_id, "x" * (store.NOTE_MAX + 1))["error"]["key"] == "bad_request"
    assert api.set_transfer_note(copy_id, 5)["error"]["key"] == "bad_request"
    assert api.set_transfer_note("../x", "a")["error"]["key"] == "bad_request"


def test_backup_announces_its_copy_before_copying(tmp_path):
    api, rec, _ = _inventoried(tmp_path)
    api.start_backup(SELECTION)
    announced = rec.of("transfer:copy")[0]["copy"]
    assert announced["status"] == "in_progress"
    assert announced["id"] == rec.of("transfer:done")[0]["copy"]["id"]
    assert rec.names().index("transfer:copy") < rec.names().index("transfer:progress")


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
    storage = FakeStoragePhone(root, serial=NEW)
    storage.props["ro.product.cpu.abilist"] = "arm64-v8a,armeabi-v7a"
    return TransferPhone(make_cli_phone(), storage)


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
    assert not rec.of("job:error"), rec.of("job:error")
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


def test_restore_records_the_new_phone_imei(tmp_path, monkeypatch):
    # „wgrano na …” w Historii pokazuje IMEI nowego telefonu (zapisany w stanie wgrywania), nie numer seryjny
    monkeypatch.setattr("admenot.engine.device.info.read_imei", lambda adb: "861485069821024")
    api, rec, _, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    assert "job_id" in api.start_restore(CHOICE)
    api._identities.clear()  # po ponownym uruchomieniu programu: IMEI tylko ze stanu wgrywania
    (entry,) = api.transfers()["copies"][0]["restores"]
    assert (entry["serial"], entry["imei"]) == (NEW, "861485069821024")


def test_older_restore_without_imei_takes_it_from_the_connected_phone(tmp_path):
    from admenot.engine.transfer.restore_state import RestoreState, restore_state_path

    api, _, _, copy_id = _copied(tmp_path)
    state = RestoreState(restore_state_path(store.CopyDir(store.transfers_dir() / copy_id), NEW))
    state.set_meta("serial", NEW)
    state.set_meta("status", "complete")
    state.close()
    assert api.transfers()["copies"][0]["restores"][0]["imei"] is None
    api._identities[NEW] = ("Oppo A16s", "861580056585051", None, "12")
    assert api.transfers()["copies"][0]["restores"][0]["imei"] == "861580056585051"


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
    assert event["copy"]["restores"] == [{"serial": NEW, "imei": None, "status": "stopped",
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


# --- Etap 3: kontakty, wiadomości i połączenia na nowym telefonie --------------------------------

PREV = "com.google.android.apps.messaging"
TEL_CHOICE = {**CHOICE, "tel": ["contacts", "sms", "calls"]}


@pytest.fixture
def no_tap_wait(monkeypatch):
    from admenot.engine.transfer import phonesetup

    monkeypatch.setattr(phonesetup, "_sleep", lambda s: None)


def _helper_pkg() -> str:
    from admenot.engine.transfer import helper

    return helper.PACKAGE


def _tel_copied(tmp_path, **kw):
    """Kopia ze starego telefonu (2 kontakty do zapisu, 2 SMS, 1 połączenie) i nowy telefon z pustą
    telefonią, na którym Wiadomości Google są domyślną aplikacją SMS."""
    api, rec, host, copy_id = _copied(tmp_path, **kw)
    new = host.phone(NEW).storage
    new.telephony = True
    new.role_holders = [PREV]
    (new.root / "sdcard" / "Download").mkdir(parents=True, exist_ok=True)
    return api, rec, host, copy_id


def _on_event(rec, hook):
    """Woła `hook(nazwa, szczegóły)` po każdym zdarzeniu (zadania w testach są synchroniczne)."""
    emit = rec.emit

    def emit_and_hook(name, detail=None):
        emit(name, detail)
        hook(name, rec.of(name)[-1])

    rec.emit = emit_and_hook


def _synced_account(new) -> None:
    """Na nowym telefonie jest już konto Google `a@b` z kontaktami: kontakt z tego konta przyjdzie
    z synchronizacji, więc plan go pomija."""
    new.accounts = [("com.google", "a@b")]
    new.providers["raw_contacts"] = [{"_id": "1", "contact_id": "1", "deleted": "0",
                                      "account_type": "com.google", "account_name": "a@b"}]
    new.providers["contacts"] = [{"_id": "1", "starred": "0", "display_name": "Ktoś inny"}]


def test_restore_plan_includes_tel_view(tmp_path):
    api, rec, host, copy_id = _tel_copied(tmp_path)
    tel = _planned(api, rec, copy_id)["tel"]
    assert tel["contacts"] == {"write": 2, "existing": 0, "skipped_synced": [], "skipped_messenger": 0}
    assert tel["sms"] == {"write": 2, "existing": 0} and tel["calls"] == {"write": 1, "existing": 0}
    assert tel["mms"] is None  # kopia bez MMS
    assert tel["phone_has_contacts"] is False
    assert tel["readable"] == {"contacts": True, "sms": True, "calls": True}
    new = host.phone(NEW).storage
    assert new.providers["sms"] == [] and new.installed == set() and new.appop == "default"


def test_restore_plan_tel_skips_synced_account(tmp_path):
    api, rec, host, copy_id = _tel_copied(tmp_path)
    _synced_account(host.phone(NEW).storage)
    tel = _planned(api, rec, copy_id)["tel"]
    assert tel["contacts"]["write"] == 1 and tel["phone_has_contacts"] is True
    assert tel["contacts"]["skipped_synced"] == [{"account": "a@b", "count": 1}]


def test_start_restore_with_tel_completes(tmp_path, no_tap_wait):
    api, rec, host, copy_id = _tel_copied(tmp_path)
    _planned(api, rec, copy_id)
    assert "job_id" in api.start_restore(TEL_CHOICE)
    done = rec.of("transfer:restore_done")[0]
    assert done["result"]["status"] == "complete" and done["result"]["files_done"] == 5
    tel = done["tel"]
    assert {k: (v["written"], v["path"]) for k, v in tel["kinds"].items()} == {
        "contacts": (2, "app_process"), "sms": (2, "app_process"), "calls": (1, "app_process")}
    assert tel["status"] == "complete" and tel["stopped"] is False and tel["manual"] == []
    assert tel["cleanup"]["ok"] is True and tel["safety"] == {"contacts": True, "sms": True, "calls": True}
    assert rec.of("transfer:tel_progress")
    new = host.phone(NEW).storage
    assert (len(new.providers["contacts"]), len(new.providers["sms"]), len(new.providers["calls"])) == (2, 2, 1)
    assert new.role_holders == [PREV] and new.appop == "default" and new.tmp_files == set()
    (entry,) = api.transfers()["copies"][0]["restores"]
    assert (entry["status"], entry["resumable"]) == ("complete", False)
    assert api.start_restore({**CHOICE, "tel": ["rcs"]})["error"]["key"] == "bad_request"
    assert api.start_restore({**CHOICE, "tel": ["mms"]})["error"]["key"] == "bad_request"
    assert api.start_restore({**CHOICE, "tel": "sms"})["error"]["key"] == "bad_request"


def test_tap_event_and_skip(tmp_path, no_tap_wait):
    api, rec, host, copy_id = _tel_copied(tmp_path)
    new = host.phone(NEW).storage
    new.helper_denied = {"sms"}  # SMS przez aplikację pomocniczą: rola SMS, a ta wymaga stuknięcia
    new.role_needs_tap = True
    _planned(api, rec, copy_id)
    assert api.skip_tap()["error"]["key"] == "bad_request"  # nic nie czeka na stuknięcie
    skipped = []

    def hook(name, detail):
        if name == "transfer:tap" and detail["request"] == "sms_role_grant":
            skipped.append(api.skip_tap())

    _on_event(rec, hook)
    api.start_restore(TEL_CHOICE)
    assert skipped == [{}]
    assert rec.of("transfer:tap") == [{"request": "sms_role_grant", "package": PREV},
                                      {"request": None, "package": PREV}]
    tel = rec.of("transfer:restore_done")[0]["tel"]
    assert tel["kinds"]["sms"]["path"] == "file" and tel["kinds"]["sms"]["manual"] == 2
    assert [m["kind"] for m in tel["manual"]] == ["sms"]
    assert "/" not in tel["manual"][0]["name"] and tel["manual"][0]["name"].endswith(".xml")
    assert tel["status"] == "incomplete" and tel["cleanup"]["ok"] is True
    assert new.role_holders == [PREV] and _helper_pkg() not in new.installed


def test_skip_not_allowed_on_role_restore(tmp_path, no_tap_wait):
    api, rec, host, copy_id = _tel_copied(tmp_path)
    new = host.phone(NEW).storage
    new.helper_denied = {"sms"}
    new.role_restore_needs_tap = True  # rola nie wraca sama z ADB: serwisant stuka w ustawieniach
    _planned(api, rec, copy_id)
    answers = []

    def hook(name, detail):
        if name == "transfer:tap" and detail["request"] == "sms_role_restore":
            answers.append(api.skip_tap())
            new.tap_role(PREV)

    _on_event(rec, hook)
    api.start_restore(TEL_CHOICE)
    assert [(a["error"]["key"], a["error"]["message"]) for a in answers] == [("bad_request", "restore_required")]
    tel = rec.of("transfer:restore_done")[0]["tel"]
    assert tel["kinds"]["sms"]["path"] == "companion" and tel["cleanup"]["ok"] is True
    assert new.role_holders == [PREV] and _helper_pkg() not in new.installed


def _leftover_changes(host, copy_id):
    """Stan wgrywania po zamknięciu programu w trakcie: rolę SMS i aplikację pomocniczą ma nasz pakiet."""
    from admenot.engine.transfer.restore_state import RestoreState, restore_state_path

    copy = store.CopyDir(store.transfers_dir() / copy_id)
    state = RestoreState(restore_state_path(copy, NEW))
    state.set_meta("serial", NEW)
    state.set_meta("status", "running")
    state.set_meta("device_changes", {"appop_prev": None, "role_prev": [PREV], "companion": True,
                                      "helper_dir": False})
    state.close()
    new = host.phone(NEW).storage
    new.installed = {_helper_pkg()}
    new.role_holders = [_helper_pkg()]
    return copy, new


def test_connect_runs_cleanup_before_scan(tmp_path, no_tap_wait):
    from admenot.engine.transfer.phonesetup import device_changes
    from admenot.engine.transfer.restore_state import RestoreState, restore_state_path

    api, rec, host, copy_id = _tel_copied(tmp_path)
    copy, new = _leftover_changes(host, copy_id)
    during = []

    def on_shell(command):
        if command == "dumpsys role" and not during:
            during.append(api.start_scan(NEW)["error"])
            during.append(api.restore_plan(copy_id, NEW)["error"])

    new.on_shell = on_shell
    assert api.list_devices()["error"] is None  # telefon na liście: sprzątanie startuje samo
    assert [(e["key"], e["message"]) for e in during] == [("busy", "phone_cleanup")] * 2
    assert rec.of("transfer:cleanup_done") == [{"ok": True, "serial": NEW}]
    assert new.role_holders == [PREV] and new.installed == set()
    state = RestoreState(restore_state_path(copy, NEW))
    try:
        assert not device_changes(state).pending
    finally:
        state.close()
    new.on_shell = None
    api.list_devices()  # ten sam telefon dalej podłączony: sprzątanie nie startuje drugi raz
    assert len(rec.of("transfer:cleanup_done")) == 1
    assert "job_id" in api.start_scan(NEW)


def test_connect_cleanup_waits_for_tap_and_refuses_skip(tmp_path, no_tap_wait):
    api, rec, host, copy_id = _tel_copied(tmp_path)
    _copy, new = _leftover_changes(host, copy_id)
    new.role_restore_needs_tap = True
    answers = []

    def hook(name, detail):
        if name == "transfer:tap" and detail["request"] == "sms_role_restore":
            answers.append(api.skip_tap()["error"]["message"])
            new.tap_role(PREV)

    _on_event(rec, hook)
    api.list_devices()
    assert answers == ["restore_required"]
    assert rec.of("transfer:tap")[0] == {"request": "sms_role_restore", "package": PREV}
    assert rec.of("transfer:cleanup_done") == [{"ok": True, "serial": NEW}] and new.installed == set()


def test_tel_telemetry_has_no_names_or_numbers(tmp_path, no_tap_wait):
    api, rec, host, copy_id = _tel_copied(tmp_path)
    _synced_account(host.phone(NEW).storage)
    api.set_telemetry(True, True)
    _planned(api, rec, copy_id)
    api.start_restore(TEL_CHOICE)
    assert rec.of("transfer:restore_done")[0]["tel"]["synced_accounts"] == [{"account": "a@b", "count": 1}]
    events = [json.loads(x) for x in telemetry_path().read_text("utf-8").splitlines()]
    event = next(e for e in events if e["type"] == "transfer_restore")
    assert event["status"] == "complete" and event["cleanup_ok"] is True
    assert event["tel"]["contacts"] == {"written": 1, "existed": 0, "skipped": 1, "failed": 0, "manual": 0,
                                        "path": "app_process", "visible_warning": False}
    assert set(event["tel"]) == {"contacts", "sms", "calls"} and set(event["safety"]) == set(event["tel"])
    text = json.dumps(event, ensure_ascii=False)
    for secret in ("a@b", "Jan", "Kowalski", "Firma", "biuro@firma.pl", "600100200", "999888777",
                   "Cześć", "Emoji", PREV, NEW, SERIAL):
        assert secret not in text, secret


# --- sprzątanie przy podłączeniu: poprawki (przegląd zadania 8, runda 1) ----------------------------


def _recorded_changes(host, copy_id):
    """Jak `_leftover_changes`, ale zapisane tak jak robi to wgrywanie (`phonesetup`): w kopii i w zapisie
    telefonu poza kopią; do tego appop shell zmieniony na `allow`."""
    from admenot.engine.transfer import phonesetup
    from admenot.engine.transfer.restore_state import RestoreState, restore_state_path

    copy = store.CopyDir(store.transfers_dir() / copy_id)
    state = RestoreState(restore_state_path(copy, NEW))
    state.set_meta("serial", NEW)
    state.set_meta("status", "running")
    phonesetup._save(state, phonesetup.DeviceChanges("default", (PREV,), True, False))
    state.close()
    new = host.phone(NEW).storage
    new.installed = {_helper_pkg()}
    new.role_holders = [_helper_pkg()]
    new.appop = "allow"
    return copy, new


@pytest.mark.parametrize("how", ["delete", "purge"])
@pytest.mark.parametrize("leftover", ["recorded", "in_copy_only"])
def test_deleted_copy_keeps_phone_changes_and_cleanup_still_runs(tmp_path, no_tap_wait, how, leftover):
    """Zapis zmian nowego telefonu nie ginie z kopią („Usuń” albo termin 7 dni): po podłączeniu telefonu
    sprzątanie i tak oddaje rolę SMS, przywraca appop i odinstalowuje aplikację pomocniczą. Stan sprzed
    zapisu poza kopią (`in_copy_only`) przenosimy do zapisu telefonu przed usunięciem kopii."""
    from admenot.engine.paths import device_dir_name, phone_changes_dir

    api, rec, host, copy_id = _tel_copied(tmp_path)
    if leftover == "recorded":
        copy, new = _recorded_changes(host, copy_id)
    else:
        copy, new = _leftover_changes(host, copy_id)
        new.appop = "default"  # stan w kopii nie zmieniał appop
    if how == "delete":
        assert api.delete_transfer(copy_id) == {"deleted": copy_id}
    else:
        meta = copy.read_meta()
        meta.expires = NOW - timedelta(days=1)
        copy.write_meta(meta)
        assert api.transfers()["copies"] == []  # `transfers` najpierw usuwa kopie po terminie
    assert not copy.path.exists()
    record = phone_changes_dir() / f"{device_dir_name(NEW)}.json"
    assert record.is_file()
    api.list_devices()  # telefon podłączony: sprzątanie z zapisu telefonu
    assert rec.of("transfer:cleanup_done") == [{"ok": True, "serial": NEW}]
    assert new.role_holders == [PREV] and new.installed == set() and new.appop == "default"
    assert not record.exists()


def test_unreadable_phone_record_fails_cleanup_within_the_try_limit(tmp_path, no_tap_wait):
    """Zapis telefonu, którego nie da się odczytać: lista telefonów działa, sprzątanie kończy się
    niepowodzeniem (najwyżej 3 próby), zapis zostaje nietknięty, a po limicie zadania nie czekają."""
    from admenot.engine.paths import device_dir_name, phone_changes_dir

    api, rec, _host, _copy_id = _tel_copied(tmp_path)
    record = phone_changes_dir() / f"{device_dir_name(NEW)}.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_bytes(b"{broken")
    clock = [0.0]
    api._clock = lambda: clock[0]
    for _ in range(5):
        assert api.list_devices()["error"] is None
        clock[0] += 60.0
    assert rec.of("transfer:cleanup_done") == [{"ok": False, "serial": NEW}] * 3
    assert record.read_bytes() == b"{broken"
    assert "job_id" in api.start_scan(NEW)


def test_copy_view_has_no_cleanup_flag(tmp_path):
    api, _rec, _host, _copy_id = _copied(tmp_path)
    assert "cleanup_pending" not in api.transfers()["copies"][0]


@pytest.mark.parametrize("call", ["start_scan", "transfer_inventory", "restore_plan"])
def test_entry_point_runs_cleanup_missed_while_another_job_ran(tmp_path, no_tap_wait, call):
    """Telefon podłączony w trakcie innego zadania (lista telefonów nie mogła wtedy wystartować
    sprzątania): pierwsze wywołanie na tym serialu startuje sprzątanie i dostaje `busy`; potem działa."""
    api, rec, host, copy_id = _tel_copied(tmp_path)
    _copy, new = _leftover_changes(host, copy_id)
    api._jobs.start("apk", lambda job: api.list_devices())  # inne zadanie trwa w chwili podłączenia
    assert rec.of("transfer:cleanup_done") == [] and new.role_holders == [_helper_pkg()]

    def go():
        return api.restore_plan(copy_id, NEW) if call == "restore_plan" else getattr(api, call)(NEW)

    err = go()["error"]
    assert (err["key"], err["message"]) == ("busy", "phone_cleanup")
    assert rec.of("transfer:cleanup_done") == [{"ok": True, "serial": NEW}] and new.role_holders == [PREV]
    assert "job_id" in go()
    assert len(rec.of("transfer:cleanup_done")) == 1


def test_failed_cleanup_is_retried_on_same_connection(tmp_path, no_tap_wait, monkeypatch):
    from admenot.app import api as api_mod
    from admenot.engine.transfer.phonesetup import CleanupResult

    api, rec, host, copy_id = _tel_copied(tmp_path)
    _copy, new = _leftover_changes(host, copy_id)
    real, calls = api_mod.cleanup, []

    def flaky(*args):
        calls.append(1)
        if len(calls) == 1:
            return CleanupResult(False, True, False, True)  # np. rola nie wróciła
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real(*args)

    monkeypatch.setattr(api_mod, "cleanup", flaky)
    clock = [0.0]
    api._clock = lambda: clock[0]
    for step in (0.0, 5.0, 5.0, 29.0, 1.0, 100.0):  # odczyt listy co chwilę, czas mija między nimi
        clock[0] += step
        assert api.list_devices()["error"] is None
    # ponowienia w tle po 10 s i po 30 s od nieudanej próby, nie co odczyt listy; po udanym — już nie
    assert len(calls) == 3
    assert rec.of("transfer:cleanup_done") == [{"ok": False, "serial": NEW}] * 2 + [{"ok": True, "serial": NEW}]
    assert rec.of("transfer:cleanup_started") == [{"serial": NEW}] * 3
    assert new.role_holders == [PREV]


def test_cleanup_gives_up_after_three_tries_until_reconnect(tmp_path, no_tap_wait, monkeypatch):
    """Sprzątanie, które ciągle się nie udaje: najwyżej 3 próby na podłączenie, potem bez ponowień i bez
    `busy` dla zadań na tym telefonie (czerwony baner ostrzega); ponowne podłączenie zaczyna od nowa."""
    from admenot.app import api as api_mod
    from admenot.engine.transfer.phonesetup import CleanupResult

    api, rec, host, copy_id = _tel_copied(tmp_path)
    _leftover_changes(host, copy_id)
    calls = []

    def failing(*args):
        calls.append(1)
        return CleanupResult(False, True, False, True)

    monkeypatch.setattr(api_mod, "cleanup", failing)
    clock = [0.0]
    api._clock = lambda: clock[0]
    api.list_devices()
    err = api.start_scan(NEW)["error"]  # wejście zadania w odstępie: `busy`, bez nowej próby
    assert (err["key"], err["message"]) == ("busy", "phone_cleanup") and len(calls) == 1
    for _ in range(5):
        clock[0] += 60.0
        api.list_devices()
    assert len(calls) == 3 and rec.of("transfer:cleanup_done")[-1] == {"ok": False, "serial": NEW}
    assert "job_id" in api.start_scan(NEW)  # po limicie zadania nie czekają na sprzątanie
    assert len(calls) == 3
    host.connected.discard(NEW)
    api.list_devices()
    host.connected.add(NEW)
    api.list_devices()  # ponowne podłączenie: znów automatyczna próba
    assert len(calls) == 4


def test_job_entries_during_backoff_do_not_use_up_cleanup_tries(tmp_path, no_tap_wait, monkeypatch):
    """Trzy szybkie kliknięcia po nieudanym sprzątaniu: każde dostaje `busy/phone_cleanup` (baner już jest),
    ale żadne nie startuje próby — 3 próby zostają przy swoich odstępach (10 s, 30 s)."""
    from admenot.app import api as api_mod
    from admenot.engine.transfer.phonesetup import CleanupResult

    api, rec, host, copy_id = _tel_copied(tmp_path)
    _leftover_changes(host, copy_id)
    calls = []

    def failing(*args):
        calls.append(1)
        return CleanupResult(False, True, False, True)

    monkeypatch.setattr(api_mod, "cleanup", failing)
    clock = [0.0]
    api._clock = lambda: clock[0]
    api.list_devices()
    assert len(calls) == 1
    for call in (lambda: api.start_scan(NEW), lambda: api.transfer_inventory(NEW),
                 lambda: api.restore_plan(copy_id, NEW)):
        clock[0] += 1.0
        err = call()["error"]
        assert (err["key"], err["message"]) == ("busy", "phone_cleanup")
    assert len(calls) == 1
    clock[0] = 10.0  # po odstępie wejście zadania startuje drugą próbę
    err = api.start_scan(NEW)["error"]
    assert (err["key"], err["message"]) == ("busy", "phone_cleanup") and len(calls) == 2
    clock[0] = 20.0
    assert api.start_scan(NEW)["error"]["message"] == "phone_cleanup" and len(calls) == 2
    clock[0] = 40.0
    api.list_devices()
    assert len(calls) == 3
    assert "job_id" in api.start_scan(NEW)  # po limicie zadania nie czekają
    assert rec.of("transfer:cleanup_started") == [{"serial": NEW}] * 3


def test_stopped_cleanup_not_prompted_again_on_same_connection(tmp_path, no_tap_wait, monkeypatch):
    from admenot.app import api as api_mod
    from admenot.engine.transfer.phonesetup import CleanupResult

    api, rec, host, copy_id = _tel_copied(tmp_path)
    _leftover_changes(host, copy_id)
    calls = []

    def stopped(*args):
        calls.append(1)
        api._jobs.stop()  # serwisant zatrzymał sprzątanie
        return CleanupResult(False, True, False, True)

    monkeypatch.setattr(api_mod, "cleanup", stopped)
    api.list_devices()
    api.list_devices()
    assert len(calls) == 1 and rec.of("transfer:cleanup_done") == [{"ok": False, "serial": NEW}]


def test_cleanup_check_error_logged_once_per_connection(tmp_path, monkeypatch):
    from admenot.app import api as api_mod

    api, _rec, _host, _copy_id = _tel_copied(tmp_path)
    calls, logged = [], []

    def broken(copies, serial):
        calls.append(serial)
        raise RuntimeError("zepsuty stan")

    monkeypatch.setattr(api_mod, "pending_cleanup", broken)
    monkeypatch.setattr(api_mod, "log_exception", lambda exc, **kw: logged.append(exc))
    for _ in range(3):
        assert api.list_devices()["error"] is None
    assert calls.count(NEW) == 3  # sprawdzamy dalej przy każdym odczycie listy
    assert len(logged) == len(set(calls))  # ale log raz na telefon i podłączenie


def test_cleanup_check_not_run_twice_concurrently(tmp_path, monkeypatch):
    from admenot.app import api as api_mod

    api, _rec, _host, _copy_id = _tel_copied(tmp_path)
    real, calls = api_mod.pending_cleanup, []
    entered, go = threading.Event(), threading.Event()

    def slow(copies, serial):
        calls.append(serial)
        if serial == NEW and not entered.is_set():
            entered.set()
            go.wait(5)
        return real(copies, serial)

    monkeypatch.setattr(api_mod, "pending_cleanup", slow)
    first = threading.Thread(target=api.list_devices)  # wątek obserwatora telefonów
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=api.list_devices)  # `list_devices` z UI w tym samym czasie
    second.start()
    second.join(0.3)
    go.set()
    first.join(5)
    second.join(5)
    assert calls.count(NEW) == 1


def test_restore_of_a_deleted_copy_does_not_recreate_it(tmp_path, no_tap_wait):
    """U7: kopia usunięta z dysku między planem a „Wgraj” — zapis `tel_left` nie zakłada jej katalogu
    na nowo (pusty katalog z samym stanem wgrywania), wgrywanie kończy się błędem kopii."""
    import shutil

    api, rec, _host, copy_id = _tel_copied(tmp_path)
    _planned(api, rec, copy_id)
    copy = store.CopyDir(store.transfers_dir() / copy_id)
    shutil.rmtree(copy.path)
    api.start_restore(TEL_CHOICE)
    assert rec.of("job:error")[-1]["key"] == "transfer_copy_missing"
    assert not copy.path.exists()


def test_tel_record_counts_have_one_definition():
    """U8: `sms` z ekranu obejmuje MMS — jedna funkcja liczy rekordy dla mostu, silnika i zamykania stanu."""
    from admenot.engine.transfer.restore import engine_tel_kinds, tel_records_to_write
    from admenot.engine.transfer.telplan import ContactSelection, TelPlan
    from admenot.engine.transfer.telrecords import TelSources

    plan = TelPlan(TelSources(None, None, None, None), ContactSelection([object()] * 2, {}, 0),  # type: ignore[list-item]
                   [object()] * 3, [object()] * 4, [object()] * 5, {}, False, {}, None)  # type: ignore[list-item]
    assert engine_tel_kinds({"sms"}) == {"sms", "mms"} and engine_tel_kinds({"calls"}) == {"calls"}
    assert tel_records_to_write(plan, frozenset({"contacts", "sms"})) == {"contacts": 2, "sms": 3, "mms": 4}
    assert tel_records_to_write(plan, frozenset({"calls"})) == {"calls": 5}


def test_tel_error_after_files_still_reports_files(tmp_path, no_tap_wait, monkeypatch):
    from admenot.app import api as api_mod

    api, rec, _host, copy_id = _tel_copied(tmp_path)
    api.set_telemetry(True, True)
    _planned(api, rec, copy_id)

    def boom(*args, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(api_mod, "run_tel_restore", boom)
    assert "job_id" in api.start_restore(TEL_CHOICE)
    done = rec.of("transfer:restore_done")[0]
    assert done["result"]["status"] == "complete" and done["result"]["files_done"] == 5
    assert done["tel"] is None and done["tel_error"] == "transfer_failed"
    events = [json.loads(x) for x in telemetry_path().read_text("utf-8").splitlines()]
    event = next(e for e in events if e["type"] == "transfer_restore")
    assert event["status"] == "incomplete" and event["files"] == 5 and "tel" not in event


def test_files_only_restore_done_has_no_tel_error(tmp_path):
    api, rec, _host, copy_id = _tel_copied(tmp_path)
    _planned(api, rec, copy_id)
    api.start_restore(CHOICE)
    done = rec.of("transfer:restore_done")[0]
    assert done["tel"] is None and done["tel_error"] is None


def _kill_mid_write(copy: store.CopyDir, serial: str = NEW) -> None:
    """Jak po twardym zamknięciu programu w trakcie zapisu: przebieg `running`, rekordy telefonii w kolejce."""
    from admenot.engine.transfer.restore_state import RestoreState, restore_state_path

    state = RestoreState(restore_state_path(copy, serial))
    try:
        state.set_meta("status", "running")
        state.set_meta("tel_left", 5)
        pushed = next(iter(state.all_files()))
        state.update(pushed, status="pushing")
        state.commit()
    finally:
        state.close()


def test_resume_banner_closes_when_phone_already_has_everything(tmp_path, no_tap_wait):
    from admenot.engine.transfer.restore_state import (
        RestoreState,
        read_restores,
        restore_state_path,
    )

    api, rec, _host, copy_id = _tel_copied(tmp_path)
    _planned(api, rec, copy_id)
    api.start_restore({**CHOICE, "tel": ["sms", "calls"]})
    copy = store.CopyDir(store.transfers_dir() / copy_id)
    _kill_mid_write(copy)
    assert read_restores(copy)[0].resumable is True
    event = _planned(api, rec, copy_id)  # plan wznowienia: telefon ma już wszystko
    assert event["resumable"] is False
    (entry,) = read_restores(copy)
    assert (entry.status, entry.resumable) == ("complete", False)
    assert entry.updated is not None
    state = RestoreState(restore_state_path(copy, NEW))
    try:
        assert state.get_meta("tel_left") == 0
        assert not state.by_status("pushing") and not state.by_status("pending")
    finally:
        state.close()
    assert [e["copy"]["restores"][0]["resumable"] for e in rec.of("transfer:restore_plan")[-1:]] == [False]


def test_resume_banner_stays_when_records_are_still_missing(tmp_path, no_tap_wait):
    from admenot.engine.transfer.restore_state import read_restores

    api, rec, host, copy_id = _tel_copied(tmp_path)
    _planned(api, rec, copy_id)
    api.start_restore({**CHOICE, "tel": ["sms", "calls"]})
    copy = store.CopyDir(store.transfers_dir() / copy_id)
    _kill_mid_write(copy)
    host.phone(NEW).storage.providers["sms"] = []  # SMS zniknęły z telefonu: jest co dopisać
    event = _planned(api, rec, copy_id)
    assert event["resumable"] is True and read_restores(copy)[0].resumable is True


def test_tel_choice_keeps_resume_banner_between_files_and_tel(tmp_path, no_tap_wait, monkeypatch):
    """Program zamknięty po plikach, a przed telefonią: stan i tak daje Banner wznowienia."""
    from admenot.app import api as api_mod
    from admenot.engine.transfer.restore_state import read_restores

    api, rec, _host, copy_id = _tel_copied(tmp_path)
    _planned(api, rec, copy_id)
    copy = store.CopyDir(store.transfers_dir() / copy_id)
    seen = []

    def died(*args, **kw):
        seen.extend(read_restores(copy))  # stan dokładnie w chwili po plikach
        raise RuntimeError("program zamknięty")

    monkeypatch.setattr(api_mod, "run_tel_restore", died)
    api.start_restore(TEL_CHOICE)
    (entry,) = seen
    assert (entry.status, entry.resumable) == ("complete", True)
    (entry,) = read_restores(copy)
    assert entry.resumable is True


def test_changing_transfers_dir_remembers_old_root(tmp_path):
    from admenot.engine.paths import transfers_dir
    from admenot.engine.settings import load_settings
    copy = store.create_copy(SERIAL, _device(), None, NOW)
    old_root = transfers_dir()
    api, _ = _api(_phone(tmp_path))
    first = tmp_path / "pierwszy"
    assert api.save_settings({"transfers_dir": str(first)})["transfers_dir"] == str(first)
    assert load_settings().transfer_roots == [str(old_root)]
    assert [c["id"] for c in api.transfers()["copies"]] == [copy.read_meta().id]
    # z pustego folderu nic nie zapamiętujemy
    api.save_settings({"transfers_dir": str(tmp_path / "drugi")})
    assert load_settings().transfer_roots == [str(old_root)]
    error = api.save_settings({"transfers_dir": "względny"})["error"]
    assert (error["key"], error["message"]) == ("bad_request", "transfers_dir")


def test_failing_to_remember_old_root_keeps_the_old_folder(tmp_path, monkeypatch):
    from admenot.engine.paths import transfers_dir
    copy = store.create_copy(SERIAL, _device(), None, NOW)
    old_root = transfers_dir()
    api, _ = _api(_phone(tmp_path))

    def locked(changes):
        raise OSError("settings.json zablokowany")

    monkeypatch.setattr(store, "save_internal", locked)
    assert "error" in api.save_settings({"transfers_dir": str(tmp_path / "nowy")})
    assert transfers_dir() == old_root  # folder kopii się nie zmienił, więc kopia nie zniknęła z Historii
    assert [c["id"] for c in api.transfers()["copies"]] == [copy.read_meta().id]


def test_changing_transfers_dir_remembers_unplugged_old_root(tmp_path):
    from admenot.engine.settings import load_settings
    api, _ = _api(_phone(tmp_path))
    usb = tmp_path / "pendrive" / "kopie"
    usb.mkdir(parents=True)
    api.save_settings({"transfers_dir": str(usb)})
    copy = store.create_copy(SERIAL, _device(), None, NOW)
    copy_id = copy.read_meta().id
    (tmp_path / "pendrive").rename(tmp_path / "odlaczony")  # pendrive odłączony
    api.save_settings({"transfers_dir": str(tmp_path / "nowy")})
    assert load_settings().transfer_roots == [str(usb)]
    assert api.transfers()["copies"] == []
    (tmp_path / "odlaczony").rename(tmp_path / "pendrive")  # podłączony znowu
    assert [c["id"] for c in api.transfers()["copies"]] == [copy_id]


def test_bridge_uses_transfer_keep_days(tmp_path):
    api, _ = _api(_phone(tmp_path))
    api.save_settings({"transfer_keep_days": 30})
    copy = store.create_copy(SERIAL, _device(), None, NOW)
    view = api.extend_transfer(copy.read_meta().id)["copy"]
    assert view["expires"] == (NOW + timedelta(days=37)).isoformat(timespec="seconds")


# --- zlecenie ZS dla kopii (Etap 4–5, zadanie 3) --------------------------------------------------

def _transfer_orders():
    from admenot.engine.journal.db import Journal
    from admenot.engine.paths import journal_path
    with Journal(journal_path()) as journal:
        return journal.transfer_orders()


def test_backup_done_opens_order(tmp_path):
    api, rec, _ = _inventoried(tmp_path)
    api.start_backup(SELECTION)
    done = rec.of("transfer:done")[0]
    found = _transfer_orders()
    assert len(found) == 1
    order, record = found[0]
    assert order.kind == "transfer" and order.client_name == "Anna K."
    assert done["copy"]["order"] == order.number
    assert record.copy_id == done["copy"]["id"]


def test_stopped_backup_opens_no_order(tmp_path):
    api, rec, release = _held_backup(tmp_path)
    job_id = api._jobs.current().id
    api.stop(job_id)
    release.set()
    assert rec.wait_for("transfer:done")["result"]["status"] == "stopped"
    assert api._jobs.wait(5)
    assert _transfer_orders() == []


def test_delete_copy_marks_journal(tmp_path):
    api, rec, _ = _inventoried(tmp_path)
    api.start_backup(SELECTION)
    copy_id = rec.of("transfer:done")[0]["copy"]["id"]
    assert api.delete_transfer(copy_id) == {"deleted": copy_id}
    (order, record), = _transfer_orders()
    assert record.copy_deleted_at == NOW and order.status == "expired"


def test_extend_updates_journal_expiry(tmp_path):
    api, rec, _ = _inventoried(tmp_path)
    api.start_backup(SELECTION)
    copy_id = rec.of("transfer:done")[0]["copy"]["id"]
    view = api.extend_transfer(copy_id)["copy"]
    (_, record), = _transfer_orders()
    assert record.copy_expires.isoformat(timespec="seconds") == view["expires"]


def test_purge_marks_journal(tmp_path):
    api, rec, _ = _inventoried(tmp_path)
    api.start_backup(SELECTION)
    copy_id = rec.of("transfer:done")[0]["copy"]["id"]
    meta = store.resolve(copy_id).read_meta()
    meta.expires = NOW - timedelta(days=1)
    store.resolve(copy_id).write_meta(meta)
    api._purge_transfers()
    (_, record), = _transfer_orders()
    assert record.copy_deleted_at == NOW


def test_backup_survives_journal_failure_when_opening_order(tmp_path, monkeypatch):
    from admenot.engine.transfer import orders as orders_mod

    def boom(*a, **k):
        raise RuntimeError("journal down")

    monkeypatch.setattr(orders_mod, "open_for_copy", boom)
    api, rec, _ = _inventoried(tmp_path)
    api.start_backup(SELECTION)
    done = rec.of("transfer:done")[0]
    assert done["result"]["status"] == "complete" and done["copy"]["order"] is None


# --- Etap 4: aplikacje w wgrywaniu i wynik w dzienniku ---------------------------------------------

APPS_CHOICE = {**CHOICE, "apps": ["com.whatsapp"]}


def _add_app(copy_id: str, package: str, label: str, verdict: str, version: int = 5) -> None:
    import hashlib

    from admenot.engine.actions.backup import COMPLETE

    copy = store.CopyDir(store.transfers_dir() / copy_id)
    d = copy.apps_dir / package / str(version)
    d.mkdir(parents=True)
    data = package.encode()
    (d / "base.apk").write_bytes(data)
    (d / COMPLETE).write_text(json.dumps({"package": package, "version_code": version,
                                          "files": {"base.apk": hashlib.sha256(data).hexdigest()}}),
                              encoding="utf-8")
    rows = json.loads(copy.verdicts_path.read_text(encoding="utf-8")) if copy.verdicts_path.is_file() else []
    rows.append({"package": package, "version_code": version, "verdict": verdict, "label": label})
    copy.verdicts_path.write_text(json.dumps(rows), encoding="utf-8")


def _order(api, number: str):
    with api._journal() as journal:
        order = journal.order_by_number(number)
        return order, journal.transfer(order.id)


def test_restore_plan_lists_apps_with_skip(tmp_path):
    api, rec, host, copy_id = _copied(tmp_path)
    _add_app(copy_id, "com.bad", "Zły", "suspicious")
    host.phone(NEW).storage.installed.add("com.whatsapp")
    event = _planned(api, rec, copy_id)
    items = {i["package"]: i for i in event["apps"]["items"]}
    assert items["com.whatsapp"]["skip"] == "installed"
    assert items["com.bad"]["default_on"] is False and items["com.bad"]["skip"] is None
    assert items["com.bad"]["name"] == "Zły" and items["com.bad"]["verdict"] == "suspicious"
    assert event["apps"]["block"] is None
    assert event["apps"]["bytes"] == items["com.bad"]["bytes"] > 0  # tylko instalowalne
    assert event["order"] is not None and event["order"].startswith("ZS/")


def test_restore_runs_apps_last_and_saves_result(tmp_path, no_tap_wait):
    api, rec, host, copy_id = _tel_copied(tmp_path)
    _planned(api, rec, copy_id)
    assert "job_id" in api.start_restore({**TEL_CHOICE, "apps": ["com.whatsapp"]})
    names = [n for n in rec.names() if n in ("transfer:restore_progress", "transfer:tel_progress",
                                             "transfer:apps_progress")]
    assert names.index("transfer:restore_progress") < names.index("transfer:tel_progress") \
        < names.index("transfer:apps_progress")
    done = rec.of("transfer:restore_done")[0]
    assert done["apps"]["installed"] == 1 and done["order"].startswith("ZS/")
    assert done["whatsapp"] is None  # grupa WhatsApp nie miała plików w kopii
    assert "com.whatsapp" in host.phone(NEW).storage.installed
    order, record = _order(api, done["order"])
    assert record.result["apps"]["installed"] == 1 and record.result["files"]["status"] == "complete"
    assert record.result["tel"]["status"] == "complete" and record.result["status"] == "done"
    assert record.result["finished_at"] and order.status == "done"
    assert record.target_serial == NEW


def test_restore_without_apps_has_null_apps(tmp_path):
    api, rec, _host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    api.start_restore(CHOICE)
    done = rec.of("transfer:restore_done")[0]
    assert done["apps"] is None
    assert done["whatsapp"] is None
    _, record = _order(api, done["order"])
    assert record.result["apps"] is None


def test_result_saved_after_files_when_tel_crashes(tmp_path, no_tap_wait, monkeypatch):
    api, rec, _host, copy_id = _tel_copied(tmp_path)
    _planned(api, rec, copy_id)

    def boom(*a, **kw):
        raise RuntimeError("tel down")

    monkeypatch.setattr(type(api), "_run_tel", boom)
    api.start_restore({**TEL_CHOICE, "apps": ["com.whatsapp"]})
    done = rec.of("transfer:restore_done")[0]
    assert done["tel_error"] == "transfer_failed"
    order, record = _order(api, done["order"])
    assert record.result["files"]["files_done"] == 5 and record.result["tel_error"] == "transfer_failed"
    assert record.result["apps"]["installed"] == 1  # aplikacje nie zależą od telefonii
    assert order.status == "failed" and record.result["status"] == "failed"


def test_files_saved_when_job_raises_after_files(tmp_path, monkeypatch):
    api, rec, _host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)

    def boom(*a, **kw):
        raise RuntimeError("apps down")

    monkeypatch.setattr("admenot.app.api.run_install", boom)
    api.start_restore(APPS_CHOICE)
    done = rec.of("transfer:restore_done")[0]  # aplikacje degradują jak telefonia: zdarzenie końca idzie
    assert done["apps"] is None and done["apps_error"] == "transfer_failed" and done["result"]["files_done"] == 5
    with api._journal() as journal:
        ((order, record),) = journal.transfer_orders()[:1]
    assert record.result["files"]["files_done"] == 5 and order.status == "failed"
    assert record.result["status"] == "failed" and record.result["apps_error"] == "transfer_failed"
    # aplikacje bez wyniku: wgrywanie do wznowienia (Banner), a ponowny plan go nie zamyka
    (entry,) = api.transfers()["copies"][0]["restores"]
    assert entry["resumable"] is True
    assert _planned(api, rec, copy_id)["resumable"] is True


def _xiaomi_copied(tmp_path, monkeypatch):
    from admenot.engine.transfer import apps as A

    monkeypatch.setattr(A, "_XIAOMI", A._XIAOMI | {"samsung", "oppo"})
    api, rec, host, copy_id = _copied(tmp_path)
    new = host.phone(NEW).storage
    new.props["persist.security.adbinstall"] = "0"
    return api, rec, host, copy_id, new


def test_install_remaining_after_unblock(tmp_path, monkeypatch):
    api, rec, _host, copy_id, new = _xiaomi_copied(tmp_path, monkeypatch)
    event = _planned(api, rec, copy_id)
    assert event["apps"]["block"] == "xiaomi"
    assert api.install_check() == {"blocked": True}
    api.start_restore(APPS_CHOICE)
    done = rec.of("transfer:restore_done")[0]
    assert done["apps"]["blocked"] is True and done["apps"]["skipped"] == {"user_restricted": 1}
    number = done["order"]
    new.props["persist.security.adbinstall"] = "1"
    assert api.install_check() == {"blocked": False}
    assert "job_id" in api.install_remaining_apps(number)
    again = rec.of("transfer:apps_done")[-1]
    assert again["order"] == number and again["apps"]["installed"] == 1
    _, record = _order(api, number)
    assert record.result["apps"]["installed"] == 1 and record.result["files"]["status"] == "complete"
    assert "com.whatsapp" in new.installed


def test_install_remaining_records_apps_event_with_counts_only(tmp_path, monkeypatch):
    api, rec, _host, copy_id, new = _xiaomi_copied(tmp_path, monkeypatch)
    api.set_telemetry(True, True)
    _planned(api, rec, copy_id)
    api.start_restore(APPS_CHOICE)
    restore = [json.loads(x) for x in telemetry_path().read_text("utf-8").splitlines()]
    first = next(e for e in restore if e["type"] == "transfer_restore")
    assert first["apps_blocked"] is True and first["apps"]["skipped"] == 1 and first["apps_codes"] == {}
    number = rec.of("transfer:restore_done")[0]["order"]
    new.props["persist.security.adbinstall"] = "1"
    api.install_remaining_apps(number)
    events = [json.loads(x) for x in telemetry_path().read_text("utf-8").splitlines()]
    event = next(e for e in events if e["type"] == "transfer_apps")
    assert event["apps"]["installed"] == 1 and event["installer"] in ("play", "none")
    assert "whatsapp" not in json.dumps(event) and NEW not in json.dumps(event)


def test_install_remaining_needs_phone(tmp_path, monkeypatch):
    api, rec, host, copy_id, _new = _xiaomi_copied(tmp_path, monkeypatch)
    _planned(api, rec, copy_id)
    api.start_restore(APPS_CHOICE)
    number = rec.of("transfer:restore_done")[0]["order"]
    host.connected.discard(NEW)
    assert api.install_remaining_apps(number)["error"]["key"] == "transfer_no_phone"
    assert api.install_remaining_apps("ZS/none")["error"]["key"] == "bad_request"


def test_install_check_reads_prop_only(tmp_path, monkeypatch):
    api, rec, _host, copy_id, _new = _xiaomi_copied(tmp_path, monkeypatch)
    _planned(api, rec, copy_id)
    seen = len(rec.of("adb:command"))
    api.install_check()
    fresh = rec.of("adb:command")[seen:]
    assert fresh and all("getprop persist.security.adbinstall" in c["command"] for c in fresh)


def test_install_check_without_plan(tmp_path):
    api, _rec = _api(_phone(tmp_path))
    assert api.install_check() == {"blocked": None}


def test_set_whatsapp_restored_roundtrip(tmp_path):
    api, rec, _host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    api.start_restore(CHOICE)
    number = rec.of("transfer:restore_done")[0]["order"]
    assert api.set_whatsapp_restored(number, True) == {"order": number, "whatsapp_restored": True}
    assert _order(api, number)[1].whatsapp_restored is True
    assert api.set_whatsapp_restored(number, False)["whatsapp_restored"] is False
    assert api.set_whatsapp_restored(number, "yes")["error"]["key"] == "bad_request"
    assert api.set_whatsapp_restored("ZS/none", True)["error"]["key"] == "bad_request"


def test_transfers_lists_orders_and_running_copies(tmp_path):
    api, rec, _host, copy_id = _copied(tmp_path)
    (waiting,) = api.transfers()["orders"]
    assert waiting["state"] == "copy_ready" and waiting["target"] is None
    assert waiting["copy"]["id"] == copy_id and waiting["client"] == "Anna K."
    _planned(api, rec, copy_id)
    api.start_restore(CHOICE)
    (done,) = api.transfers()["orders"]
    assert done["state"] == "restored" and done["notes"] == 0 and done["target"] is not None
    assert done["whatsapp_restored"] is False and done["counts"]
    # kopia przerwana: bez zlecenia, trafia do `copies`
    store.create_copy("OLD2", _device(), "Jan", NOW)
    listed = api.transfers()
    assert len(listed["orders"]) == 1
    assert any(c["status"] == "in_progress" for c in listed["copies"])
    assert copy_id in {c["id"] for c in listed["copies"]}  # stary kształt zostaje do przejścia UI


def test_transfer_order_view_states(tmp_path):
    from admenot.app.present import transfer_order_view

    api, rec, _host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    api.start_restore(CHOICE)
    with api._journal() as journal:
        ((order, record),) = journal.transfer_orders()
        journal.save_transfer_result(order.id, {**record.result, "apps": {"failed": {"no_space": 2}}})
        record = journal.transfer(order.id)
        view = transfer_order_view(order, record, None, NOW)
        assert (view["state"], view["notes"]) == ("restored_notes", 2)
        journal.set_order_status(order.id, "failed")
        assert transfer_order_view(journal.order(order.id), record, None, NOW)["state"] == "failed"
        journal.set_order_status(order.id, "expired")
        assert transfer_order_view(journal.order(order.id), record, None, NOW)["state"] == "expired"


def test_whatsapp_view_rules(tmp_path):
    from admenot.app.api import _whatsapp_view
    from admenot.engine.transfer.apps import AppCandidate, AppsPlan, AppsResult
    from admenot.engine.transfer.restore import RestoreResult, UploadChoice

    copy = store.create_copy("OLD", _device(), None, NOW)
    base = RestoreResult("complete", NEW, 1, 0, 0, 0, 0, 0, 0, 0, 1, 1, False, "done",
                         groups={"whatsapp": {"done": 1, "exists": 0, "skipped": 0, "failed": 0}})
    chosen = UploadChoice(frozenset({"whatsapp"}), frozenset())

    def apps(status):
        return AppsResult(1, 0, 0, {}, {}, {}, False, False,
                          [{"package": "com.whatsapp", "label": "WhatsApp", "status": status, "reason": None}], True)

    assert _whatsapp_view(chosen, base, None, None, copy, NEW) == {"files": True, "app": "missing"}
    assert _whatsapp_view(chosen, base, apps("installed"), None, copy, NEW) == {"files": True, "app": "installed"}
    assert _whatsapp_view(chosen, base, apps("exists"), None, copy, NEW) == {"files": True, "app": "pre_installed"}
    plan = AppsPlan([AppCandidate("com.whatsapp", "WhatsApp", 1, 1, "clean", True, "installed", ())], None)
    assert _whatsapp_view(chosen, base, None, plan, copy, NEW) == {"files": True, "app": "pre_installed"}
    assert _whatsapp_view(UploadChoice(frozenset({"photos"}), frozenset()), base, None, None, copy, NEW) is None


def test_interrupted_running_order_is_failed_in_view(tmp_path):
    from admenot.app.present import transfer_order_view

    api, rec, _host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    api.start_restore(CHOICE)
    with api._journal() as journal:
        ((order, record),) = journal.transfer_orders()
        journal.set_order_status(order.id, "running")  # program zabity w trakcie
        order = journal.order(order.id)
        assert transfer_order_view(order, record, None, NOW)["state"] == "failed"
        assert transfer_order_view(order, record, None, NOW, running=True)["state"] == "restored"
    assert api.transfers()["orders"][0]["state"] == "failed"
    assert record.result["files"]["files_done"] == 5  # dane protokołu zostają


def test_stopped_files_do_not_run_apps(tmp_path):
    api, rec, host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    _on_event(rec, lambda n, d: api.stop(api._jobs.current().id) if n == "transfer:restore_progress" else None)
    api.start_restore(APPS_CHOICE)
    done = rec.of("transfer:restore_done")[0]
    assert done["result"]["status"] == "stopped" and done["apps"] is None
    assert not rec.of("transfer:apps_progress") and "com.whatsapp" not in host.phone(NEW).storage.installed
    order, record = _order(api, done["order"])
    assert order.status == "failed" and record.result["apps"] is None
    (entry,) = api.transfers()["copies"][0]["restores"]
    assert entry["resumable"] is True


def test_resume_keeps_earlier_results_and_order_goes_running_then_done(tmp_path, no_tap_wait):
    api, rec, _host, copy_id = _tel_copied(tmp_path)
    _planned(api, rec, copy_id)
    seen = []
    first = {"stop": True}

    def hook(name, detail):
        if name == "transfer:restore_progress" and first["stop"]:
            api.stop(api._jobs.current().id)
            first["stop"] = False

    _on_event(rec, hook)
    api.start_restore({**TEL_CHOICE, "apps": ["com.whatsapp"]})
    number = rec.of("transfer:restore_done")[0]["order"]
    order, record = _order(api, number)
    assert order.status == "failed" and record.result["files"]["status"] == "stopped"
    _planned(api, rec, copy_id)
    _on_event(rec, lambda n, d: seen.append(_order(api, number)[0].status) if n == "transfer:restore_progress" else None)
    api.start_restore({**TEL_CHOICE, "apps": ["com.whatsapp"]})
    assert "running" in seen
    order, record = _order(api, number)
    assert order.status == "done" and record.result["status"] == "done"
    assert record.result["files"]["status"] == "complete" and record.result["tel"]["status"] == "complete"
    assert record.result["apps"]["installed"] == 1
    assert api.transfers()["copies"][0]["restores"][0]["resumable"] is False


def test_install_remaining_without_apps_is_refused(tmp_path):
    api, rec, _host, copy_id = _copied(tmp_path)
    _planned(api, rec, copy_id)
    api.start_restore(CHOICE)
    number = rec.of("transfer:restore_done")[0]["order"]
    assert api.install_remaining_apps(number)["error"]["key"] == "bad_request"
    assert _order(api, number)[1].result["apps"] is None


def test_apps_left_makes_restore_resumable(tmp_path):
    from admenot.engine.transfer.restore_state import apps_left

    assert apps_left({"apps_left": 2, "choice": {"apps": ["a"]}}) == 2
    assert apps_left({"apps_left": 2, "choice": {"apps": []}}) == 0
    assert apps_left({"choice": {"apps": ["a"]}}) == 0
