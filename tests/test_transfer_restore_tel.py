"""Silnik telefonii: drogi `app_process` → aplikacja pomocnicza → plik, kopia bezpieczeństwa, widoczność.

Kopia powstaje przez prawdziwe `run_backup` ze starego telefonu-atrapy (3 kontakty, 5 SMS, 1 MMS ze
zdjęciem, 4 połączenia), plan przez `build_tel_plan`, a zapis idzie przez prawdziwego strażnika
`TelephonyWriteAdb` do nowego telefonu-atrapy z telefonią w pamięci.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path

import pytest
from faketransfer import FakeStoragePhone, write_provider

from admenot.engine.device.info import DeviceInfo
from admenot.engine.paths import device_dir_name
from admenot.engine.transfer import helper, phonesetup, store
from admenot.engine.transfer import mms as mms_mod
from admenot.engine.transfer import restore_tel as rt
from admenot.engine.transfer import telephony as tel
from admenot.engine.transfer.backup import Selection, run_backup
from admenot.engine.transfer.guard import ReadOnlyAdb
from admenot.engine.transfer.inventory import Inventory
from admenot.engine.transfer.phonesetup import device_changes, telephony_adb
from admenot.engine.transfer.restore_state import RestoreState, restore_state_path
from admenot.engine.transfer.restore_tel import AP, CO, FILE, TelResult, run_tel_restore
from admenot.engine.transfer.telfile import ManualStep, contacts_vcf, messages_xml
from admenot.engine.transfer.telplan import build_tel_plan
from admenot.engine.transfer.telrecords import read_mms_xml, read_sms_xml, read_vcards

NOW = datetime(2026, 11, 1, 12, 0, 0)
PREV = "com.google.android.apps.messaging"
PKG = helper.PACKAGE
CONTACTS_URI = "content://com.android.contacts/contacts"
RAW_URI = "content://com.android.contacts/raw_contacts"
DATA_URI = "content://com.android.contacts/data"
IMG = b"\xff\xd8\xff\xe0JFIF\r\n\x00" + bytes(range(256)) * 8 + b"\xff\xd9"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setattr(phonesetup, "_sleep", lambda s: None)


def _device(serial: str) -> DeviceInfo:
    return DeviceInfo(serial=serial, brand="oppo", manufacturer="OPPO", model="CPH2271", device="x",
                      market_name=None, android_release="12", sdk=31, security_patch=None, uptime_s=1.0,
                      local_now=NOW)


# --------------------------------------------------------------------------------------
# Stary telefon i kopia
# --------------------------------------------------------------------------------------
def _data(cid: str, mimetype: str, data1: str, data2: str | None = None, **extra: str) -> dict:
    row = {c: None for c in tel.DATA_COLS}
    row.update(contact_id=cid, raw_contact_id=f"{cid}0", mimetype=mimetype, is_primary="0", data1=data1,
               data2=data2, **extra)
    return row


A, B = "+48600100200", "+48999888777"


def _old_phone(tmp_path: Path) -> FakeStoragePhone:
    root = tmp_path / "old"
    (root / "sdcard").mkdir(parents=True)
    write_provider(root, CONTACTS_URI, [
        {"_id": "1", "starred": "1", "display_name": "Jan Kowalski"},
        {"_id": "2", "starred": "0", "display_name": "Żaneta Łęcka"},
        {"_id": "3", "starred": "0", "display_name": "Biuro"},
    ], tel.CONTACT_COLS)
    write_provider(root, RAW_URI, [
        {"_id": f"{i}0", "contact_id": str(i), "deleted": "0", "account_type": None, "account_name": None}
        for i in (1, 2, 3)], tel.RAW_COLS)
    write_provider(root, DATA_URI, [
        _data("1", tel.M_NAME, "Jan Kowalski", "Jan", data3="Kowalski"),
        _data("1", tel.M_PHONE, "+48 600 100 200", "2"),
        _data("2", tel.M_NAME, "Żaneta Łęcka", "Żaneta", data3="Łęcka"),
        _data("2", tel.M_PHONE, B, "2"),
        _data("3", tel.M_NAME, "Biuro", "Biuro"),
        _data("3", tel.M_EMAIL, "biuro@firma.pl", "2"),
    ], tel.DATA_COLS)
    write_provider(root, "content://sms", [
        {"_id": str(i), "address": A if i < 3 else B, "date": str(1_700_000_000_000 + i * 1000),
         "type": "1" if i % 2 else "2", "read": "1", "status": "-1",
         "body": f"Wiadomość {i}: zażółć 👍 & <x>\ndruga linia"} for i in range(5)], tel.SMS_COLS[1])
    write_provider(root, "content://call_log/calls", [
        {"_id": str(i), "number": A if i < 2 else B, "date": str(1_700_000_500_000 + i * 1000),
         "duration": str(10 + i), "type": "2", "presentation": "1", "subscription_id": "1", "name": None}
        for i in range(4)], tel.CALL_COLS[0])
    mms_row = {c: None for c in mms_mod.MMS_COLS}
    mms_row.update(_id="501", thread_id="7", date="1700000200", date_sent="0", msg_box="1", read="1",
                   seen="1", locked="0", sub_id="1", text_only="0", m_type="132", m_size=str(len(IMG)),
                   v="18", ct_t="application/vnd.wap.multipart.related", sub=None)
    write_provider(root, mms_mod.MMS_URI, [mms_row], mms_mod.MMS_COLS)

    def part(pid: str, ct: str, text: str | None = None, name: str | None = None) -> dict:
        row = {c: None for c in mms_mod.PART_COLS}
        row.update(_id=pid, mid="501", seq="0", ct=ct, chset="106" if text else None, name=name, text=text)
        return row

    write_provider(root, mms_mod.PART_URI, [part("602", "image/jpeg", name="IMG_1.jpg"),
                                            part("603", "text/plain", text="Zdjęcie z wakacji")],
                   mms_mod.PART_COLS)
    write_provider(root, "content://mms/501/addr", [
        {"msg_id": "501", "type": "137", "charset": "106", "address": A},
        {"msg_id": "501", "type": "151", "charset": "106", "address": "insert-address-token"}],
        mms_mod.ADDR_COLS)
    (root / "mms_parts").mkdir()
    (root / "mms_parts" / "602").write_bytes(IMG)
    return FakeStoragePhone(root, serial="OLD")


def _copy(tmp_path: Path) -> store.CopyDir:
    old = _old_phone(tmp_path)
    copy = store.create_copy("OLD", _device("OLD"), None, NOW)
    inv = Inventory(contacts=3, sms=5, mms=1, mms_bytes=len(IMG), calls=4, files=[], others={}, apps=[],
                    skipped_apps=[], whatsapp_backup=None, storage=None, unreadable=0)
    sel = Selection(contacts=True, sms=True, mms=True, calls=True, categories=frozenset(), others=frozenset(),
                    apps=frozenset())
    res = run_backup(old, old, _device("OLD"), copy, inv, sel, on_progress=lambda p: None,
                     should_stop=lambda: False, wait_device=old.reconnect, free_bytes=lambda p: 10 ** 12)
    assert {k: (v.status, v.count) for k, v in res.telephony.items()} == {
        "contacts": ("ok", 3), "sms": ("ok", 5), "mms": ("ok", 1), "calls": ("ok", 4)}
    return copy


# --------------------------------------------------------------------------------------
# Nowy telefon i przebieg
# --------------------------------------------------------------------------------------
def _new(tmp_path: Path, **kw) -> FakeStoragePhone:
    (tmp_path / "new" / "sdcard" / "Download").mkdir(parents=True)
    phone = FakeStoragePhone(tmp_path / "new", serial="NEW")
    phone.telephony = True
    phone.role_holders = [PREV]
    for k, v in kw.items():
        setattr(phone, k, v)
    return phone


ALL = frozenset({"contacts", "sms", "calls"})


class Run:
    def __init__(self, phone: FakeStoragePhone, copy: store.CopyDir) -> None:
        self.phone, self.copy = phone, copy
        self.taps: list[str | None] = []
        self.progress: list[rt.TelProgress] = []
        self.waits = 0

    def wait_device(self) -> None:
        self.waits += 1
        self.phone.fail_after_records = None
        self.phone.reconnect()

    def __call__(self, kinds: frozenset[str] = ALL, *, should_stop=lambda: False, skip_tap=lambda: False,
                 on_tap=None, wait_device=None, after_plan=None) -> TelResult:
        plan = build_tel_plan(self.phone, self.copy, self.copy.read_meta(), {"contacts", "sms", "mms", "calls"})
        if after_plan is not None:
            after_plan(plan)
        state = RestoreState(restore_state_path(self.copy, "NEW"))
        try:
            def tap(req: str | None) -> None:
                self.taps.append(req)
                if on_tap is not None:
                    on_tap(req)

            return run_tel_restore(
                telephony_adb(self.phone, state), ReadOnlyAdb(self.phone), self.phone, _device("NEW"),
                self.copy, plan, kinds, state, on_progress=self.progress.append, should_stop=should_stop,
                wait_device=wait_device or self.wait_device, on_tap=tap, skip_tap=skip_tap)
        finally:
            state.close()


def _counts(phone: FakeStoragePhone) -> dict[str, int]:
    return {k: len(phone.providers[k]) for k in ("contacts", "sms", "mms", "calls")}


def _state(copy: store.CopyDir) -> RestoreState:
    return RestoreState(restore_state_path(copy, "NEW"))


EXPECTED = {"contacts": 3, "sms": 5, "mms": 1, "calls": 4}


# --------------------------------------------------------------------------------------
# Testy
# --------------------------------------------------------------------------------------
def test_all_via_app_process(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path)
    run = Run(phone, copy)
    r = run()
    assert _counts(phone) == EXPECTED
    assert {k: v.written for k, v in r.kinds.items()} == EXPECTED
    assert {k: v.path for k, v in r.kinds.items()} == dict.fromkeys(EXPECTED, AP)
    assert not any(v.failed or v.manual or v.visible_warning for v in r.kinds.values())
    assert phone.appop == "default" and phone.tmp_files == set()
    assert phone.role_holders == [PREV] and PKG not in phone.installed
    assert r.cleanup.ok and r.status == "complete" and r.manual == [] and not r.stopped
    assert r.safety == dict.fromkeys(EXPECTED, True)
    # treść na telefonie dokładnie jak w kopii (polskie znaki, emoji, wiele linii, &<>)
    assert sorted(x["body"] for x in phone.providers["sms"]) == sorted(
        f"Wiadomość {i}: zażółć 👍 & <x>\ndruga linia" for i in range(5))
    assert {x["display_name"] for x in phone.providers["contacts"]} == {"Jan Kowalski", "Żaneta Łęcka", "Biuro"}
    st = _state(copy)
    try:
        assert not device_changes(st).pending
        assert st.get_meta("serial") == "NEW" and st.get_meta("status") == "complete"
        assert set(st.tel_status("sms").values()) == {"done"} and len(st.tel_status("sms")) == 5
    finally:
        st.close()
    assert {p.kind for p in run.progress} == {*EXPECTED, "safety"}
    assert run.progress[-1] == rt.TelProgress("calls", 4, 4, AP)


def test_second_run_writes_nothing(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path)
    run = Run(phone, copy)
    run()
    before = _counts(phone)
    r = run()
    assert _counts(phone) == before == EXPECTED
    assert {k: v.written for k, v in r.kinds.items()} == dict.fromkeys(EXPECTED, 0)
    assert {k: v.existed for k, v in r.kinds.items()} == EXPECTED
    assert r.status == "complete"


def test_disconnect_mid_batch_no_duplicates(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path, fail_after_records=2)
    run = Run(phone, copy)
    r = run()
    assert run.waits == 1
    assert _counts(phone) == EXPECTED  # dwa kontakty zapisane przed urwaniem nie są powtórzone
    assert sorted(x["display_name"] for x in phone.providers["contacts"]) == ["Biuro", "Jan Kowalski",
                                                                               "Żaneta Łęcka"]
    assert r.kinds["contacts"].written == 3 and r.status == "complete"


def test_disconnect_in_sms_batch_rereads_keys(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path, fail_after_records=3 + 2)  # 3 kontakty, potem 2 z 5 SMS
    run = Run(phone, copy)
    r = run()
    assert run.waits == 1 and _counts(phone) == EXPECTED
    assert len({(x["date"], x["body"]) for x in phone.providers["sms"]}) == 5
    assert r.kinds["sms"].written == 5 and r.status == "complete"


def test_sms_denied_goes_companion_with_role_then_restores(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path, helper_denied={"sms", "mms"})
    r = Run(phone, copy)()
    assert _counts(phone) == EXPECTED
    assert r.kinds["sms"].path == CO and r.kinds["mms"].path == CO
    assert r.kinds["contacts"].path == AP and r.kinds["calls"].path == AP
    assert phone.role_holders == [PREV] and PKG not in phone.installed
    assert phone.appop == "default" and phone.tmp_files == set()
    assert r.cleanup.ok and r.status == "complete"


def test_role_tap_waits_after_other_kinds(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path, helper_denied={"sms", "mms"}, role_needs_tap=True)
    seen: list[dict[str, int]] = []

    def on_tap(req):
        if req == "sms_role_grant":
            seen.append(_counts(phone))
            phone.tap_role(PKG)

    run = Run(phone, copy)
    r = run(on_tap=on_tap)
    assert seen == [{"contacts": 3, "sms": 0, "mms": 0, "calls": 4}]
    assert run.taps == ["sms_role_grant", None]
    assert _counts(phone) == EXPECTED and r.kinds["sms"].path == CO
    assert phone.role_holders == [PREV] and r.status == "complete"


def test_skip_tap_goes_to_file(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path, helper_denied={"sms", "mms"}, role_needs_tap=True)
    r = Run(phone, copy)(skip_tap=lambda: True)
    assert phone.providers["sms"] == [] and phone.providers["mms"] == []
    assert [m.kind for m in r.manual] == ["sms"]
    step = r.manual[0]
    assert step.remote.startswith("/sdcard/Download/admenot-wiadomosci-") and step.remote.endswith(".xml")
    local = phone.local(step.remote)
    assert len(read_sms_xml(local)) == 5 and len(read_mms_xml(local, None)) == 1
    assert r.kinds["sms"].path == FILE and r.kinds["sms"].manual == 5 and r.kinds["mms"].manual == 1
    assert r.status == "incomplete" and r.cleanup.ok
    assert phone.role_holders == [PREV] and PKG not in phone.installed
    st = _state(copy)
    try:
        assert set(st.tel_status("sms").values()) == {"manual"}
    finally:
        st.close()


def test_install_blocked_goes_to_file(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path, helper_denied={"contacts"}, install_blocked=True)
    r = Run(phone, copy)()
    assert phone.providers["contacts"] == []
    assert [m.kind for m in r.manual] == ["contacts"]
    remote = r.manual[0].remote
    assert remote.startswith("/sdcard/Download/admenot-kontakty-") and remote.endswith(".vcf")
    assert {c.display for c in read_vcards(phone.local(remote))} == {"Jan Kowalski", "Żaneta Łęcka", "Biuro"}
    assert not any("scan_file" in c or "text/x-vcard" in c for c in phone.commands)  # tylko plik, bez okna importu
    assert r.kinds["contacts"].path == FILE and r.kinds["sms"].path == AP
    assert _counts(phone) == {**EXPECTED, "contacts": 0}
    assert r.status == "incomplete" and r.cleanup.ok


def test_manual_step_reported_again_on_resume(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path, helper_denied={"contacts"}, install_blocked=True)
    run = Run(phone, copy)
    first = run()
    again = run()
    assert again.manual == first.manual and again.kinds["contacts"].manual == 3
    assert again.kinds["contacts"].path == FILE and again.status == "incomplete"


def test_safety_backup_written_once(tmp_path, monkeypatch):
    copy, phone = _copy(tmp_path), _new(tmp_path)
    calls: list[dict] = []
    real = rt.export_telephony

    def counting(adb, out_dir, **kw):
        calls.append({"out": out_dir, **{k: kw[k] for k in ("contacts", "sms", "calls", "mms")}})
        return real(adb, out_dir, **kw)

    monkeypatch.setattr(rt, "export_telephony", counting)
    run = Run(phone, copy)
    run()
    run()
    safety = copy.path / "restore" / f"{device_dir_name('NEW')}-safety"
    assert calls == [{"out": safety, "contacts": True, "sms": True, "calls": True, "mms": True}]
    assert (safety / "sms.xml").is_file() and (safety / "calls.xml").is_file()
    assert (safety / "contacts.vcf").is_file()
    st = _state(copy)
    try:
        assert st.get_meta("safety_done") == dict.fromkeys(EXPECTED, True)
    finally:
        st.close()


def test_safety_backup_announces_its_stage(tmp_path):
    """Eksport telefonii nowego telefonu trwa minuty: przed nim idzie osobny etap `safety`, tylko gdy eksport rusza."""
    copy, phone = _copy(tmp_path), _new(tmp_path)
    run = Run(phone, copy)
    run()
    kinds = [p.kind for p in run.progress]
    assert kinds[0] == "safety" and kinds.count("safety") == 1
    assert run.progress[0] == rt.TelProgress("safety", 0, 0, "none")
    before = len(run.progress)
    run()  # kopia bezpieczeństwa już jest: żadnego nowego etapu
    assert all(p.kind != "safety" for p in run.progress[before:])


def test_safety_backup_before_first_write(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path)
    Run(phone, copy)()
    first_write = next(i for i, c in enumerate(phone.commands) if "app_process" in c)
    first_change = next(i for i, c in enumerate(phone.commands) if c.startswith(("appops set", "mkdir -p /data")))
    last_read = max(i for i, c in enumerate(phone.commands[:first_write]) if c.startswith("content query"))
    assert last_read < first_change < first_write


def test_contacts_denied_read_still_written_without_safety(tmp_path):
    copy = _copy(tmp_path)
    phone = _new(tmp_path)
    phone.deny_uris.add(CONTACTS_URI)
    r = Run(phone, copy)()
    assert r.safety["contacts"] is False and r.safety["sms"] is True
    assert len(phone.providers["contacts"]) == 3 and r.kinds["contacts"].written == 3
    assert r.status == "complete"


def test_visible_warning_when_no_thread(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path, no_threads=True)
    r = Run(phone, copy)()
    assert r.kinds["sms"].visible_warning is True and r.kinds["mms"].visible_warning is True
    assert r.kinds["calls"].visible_warning is False and r.kinds["contacts"].visible_warning is False
    assert _counts(phone) == EXPECTED


def test_visible_warning_when_fewer_threads_than_addresses(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path)
    phone._thread = lambda addresses: "1"  # type: ignore[method-assign]  # wszystko w jednym wątku
    r = Run(phone, copy)()
    assert r.kinds["sms"].visible_warning is True  # 2 rozmówców, 1 wątek
    assert r.kinds["mms"].visible_warning is False


def test_stop_mid_run_cleans_up(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path)
    stop = {"now": False}

    def should_stop() -> bool:
        if phone.providers["contacts"]:
            stop["now"] = True
        return stop["now"]

    r = Run(phone, copy)(should_stop=should_stop)
    assert r.stopped and r.status == "incomplete"
    assert len(phone.providers["contacts"]) == 3 and phone.providers["sms"] == []
    assert phone.appop == "default" and phone.tmp_files == set() and r.cleanup.ok
    st = _state(copy)
    try:
        assert not device_changes(st).pending
        assert st.get_meta("status") == "stopped" and st.tel_status("sms") == {}
    finally:
        st.close()


def test_stopped_tel_run_is_resumable_in_copy_view(tmp_path):
    """Przerwana telefonia (bez plików w kolejce) daje Banner wznowienia; skończona — już nie."""
    from admenot.engine.transfer.restore_state import read_restores

    copy, phone = _copy(tmp_path), _new(tmp_path)
    r = Run(phone, copy)(should_stop=lambda: bool(phone.providers["contacts"]))
    assert r.stopped
    (entry,) = read_restores(copy)
    assert (entry.serial, entry.status, entry.resumable) == ("NEW", "stopped", True)
    assert Run(phone, copy)().status == "complete"
    (entry,) = read_restores(copy)
    assert (entry.status, entry.resumable) == ("complete", False)


def test_stop_keeps_pending_when_role_not_restored(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path, helper_denied={"sms", "mms"}, role_restore_needs_tap=True)
    stop = {"now": False}

    def on_tap(req):
        if req == "sms_role_restore":
            stop["now"] = True  # serwisant zamyka program, zamiast stuknąć

    r = Run(phone, copy)(should_stop=lambda: stop["now"], on_tap=on_tap)
    assert _counts(phone) == EXPECTED
    assert not r.cleanup.role_ok and not r.cleanup.ok and r.status == "incomplete"
    assert PKG in phone.installed and phone.role_holders == [PKG]  # nie odinstalowano posiadacza roli
    st = _state(copy)
    try:
        ch = device_changes(st)
        assert ch.role_prev == (PREV,) and ch.companion
    finally:
        st.close()


def test_export_sms_source_ignores_stale_mms(tmp_path):
    copy = _copy(tmp_path)
    meta = copy.read_meta()
    sel = {**meta.selection, "exports": [{"kind": "sms", "remote": "/sdcard/Backup/sms.xml", "size": 1,
                                          "mtime": 1}]}
    copy.write_meta(dataclasses.replace(meta, selection=sel))
    assert (copy.phone_dir / "mms.xml").is_file()  # nieaktualny mms.xml z providera
    phone = _new(tmp_path)
    r = Run(phone, copy)()
    assert len(phone.providers["sms"]) == 5 and phone.providers["mms"] == []
    assert "mms" not in r.kinds and "mms" not in r.safety


def test_helper_error_moves_to_next_route_then_file(tmp_path):
    """R15: `ERR` po 3 próbach `app_process` -> aplikacja pomocnicza (rola SMS) -> po 3 próbach plik."""
    copy, phone = _copy(tmp_path), _new(tmp_path)
    # części MMS znikają z wejścia pomocnika: obie drogi odpowiadają `ERR <id> missing_part`
    real = phone._read_input

    def broken(remote):
        kind, records = real(remote)
        if kind == "mms":
            for p in phone.local(remote).parent.iterdir():
                if p.name != helper.INPUT_NAME:
                    p.unlink()
        return kind, records

    phone._read_input = broken  # type: ignore[method-assign]
    r = Run(phone, copy)()
    assert sum(1 for c in phone.commands if "app_process" in c) == 3 + 3  # 3 próby MMS + pozostałe kategorie
    assert sum(1 for c in phone.commands if c.startswith("am instrument")) == 3
    assert phone.providers["mms"] == []
    assert r.kinds["mms"].failed == 0 and r.kinds["mms"].manual == 1 and r.kinds["mms"].path == FILE
    (mms,) = read_mms_xml(phone.local(r.manual[0].remote), None)  # plik z kopii ma załącznik
    assert any(p.file is not None and p.file.read_bytes() == IMG for p in mms.parts)
    assert phone.role_holders == [PREV] and PKG not in phone.installed and r.cleanup.ok
    assert r.status == "incomplete"
    st = _state(copy)
    try:
        assert set(st.tel_status("mms").values()) == {"manual"}
    finally:
        st.close()


def test_err_on_app_process_written_by_companion_once(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path)
    real = phone._write

    def write(kind, records, account, remote):
        if kind == "sms" and remote.startswith(helper.HELPER_DIR):
            bad = [x for x in records if x["body"].startswith("Wiadomość 3")]
            lines = real(kind, [x for x in records if x not in bad], account, remote)[:-1]
            lines += [f"ERR {x['id']} insert_failed" for x in bad]
            return [*lines, f"DONE {len(lines) - len(bad)} {len(bad)}"]
        return real(kind, records, account, remote)

    phone._write = write  # type: ignore[method-assign]
    r = Run(phone, copy)()
    assert sum(1 for c in phone.commands if c.startswith("am instrument")) == 1
    assert _counts(phone) == EXPECTED
    assert sum(1 for x in phone.providers["sms"] if x["body"].startswith("Wiadomość 3")) == 1
    assert r.kinds["sms"].written == 5 and r.kinds["sms"].path == CO and r.kinds["sms"].failed == 0
    assert phone.role_holders == [PREV] and r.status == "complete"


def test_no_route_left_counts_failed_with_last_code(tmp_path, monkeypatch):
    copy, phone = _copy(tmp_path), _new(tmp_path)
    monkeypatch.setitem(rt.CHAIN, "calls", (AP,))
    real = phone._write

    def write(kind, records, account, remote):
        if kind == "calls":
            return [*(f"ERR {x['id']} insert_failed" for x in records), f"DONE 0 {len(records)}"]
        return real(kind, records, account, remote)

    phone._write = write  # type: ignore[method-assign]
    r = Run(phone, copy)()
    assert r.kinds["calls"].failed == 4 and r.status == "incomplete"
    st = _state(copy)
    try:
        assert set(st.tel_status("calls").values()) == {"error"}
        assert {row[0] for row in st.db.execute("SELECT error FROM tel WHERE kind='calls'")} == {"insert_failed"}
    finally:
        st.close()


def test_missing_part_file_does_not_crash(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path)

    def lose_attachment(plan):
        for part in plan.mms[0].parts:
            if part.file is not None:
                part.file.unlink()

    r = Run(phone, copy)(after_plan=lose_attachment)
    assert phone.providers["mms"] == [] and len(phone.providers["sms"]) == 5
    assert r.kinds["mms"].manual == 1 and r.kinds["mms"].path == FILE
    (mms,) = read_mms_xml(phone.local(r.manual[0].remote), None)
    assert [p.content_type for p in mms.parts] == ["text/plain"]  # bez zgubionego zdjęcia
    assert r.cleanup.ok
    st = _state(copy)
    try:
        rows = dict(st.db.execute("SELECT status, error FROM tel WHERE kind='mms'"))
        assert rows == {"manual": None}
    finally:
        st.close()


def test_mms_addr_read_error_sends_mms_to_file_not_phone(tmp_path):
    """Odczyt adresów jednej MMS na nowym telefonie padł: klucze MMS nieznane, więc nic nie idzie na
    telefon na ślepo (możliwy duplikat) — MMS trafiają do pliku do ręcznego importu."""
    copy, phone = _copy(tmp_path), _new(tmp_path)
    phone.providers["mms"].append({"_id": "900", "thread_id": "1", "date": "1600000000", "msg_box": "1"})
    phone.mms_addrs["900"] = [{"type": "137", "address": "+48500500500"}]
    phone.deny_uris.add("content://mms/900/addr")
    r = Run(phone, copy)()
    assert len(phone.providers["mms"]) == 1  # tylko ta, która już była
    assert r.kinds["mms"].path == FILE and r.kinds["mms"].manual == 1 and r.kinds["mms"].written == 0
    assert len(phone.providers["sms"]) == 5  # SMS-y idą normalnie
    (step,) = r.manual  # plik wiadomości (SMS i MMS) do ręcznego importu
    assert len(read_mms_xml(phone.local(step.remote), None)) == 1


def test_unreadable_after_disconnect_goes_to_file(tmp_path):
    """R17: urwana paczka SMS na telefonie, którego nie da się odczytać -> nic nie wraca na telefon."""
    copy = _copy(tmp_path)
    phone = _new(tmp_path, fail_after_records=3 + 2)
    phone.deny_uris.add("content://sms")
    run = Run(phone, copy)
    r = run()
    assert run.waits == 1
    assert len(phone.providers["sms"]) == 2  # zapisane przed urwaniem, bez powtórki
    assert r.kinds["sms"].manual == 5 and r.kinds["sms"].path == FILE
    assert len(phone.providers["mms"]) == 1 and len(phone.providers["calls"]) == 4
    step = next(m for m in r.manual if m.kind == "sms")
    assert len(read_sms_xml(phone.local(step.remote))) == 5
    assert r.cleanup.ok and r.status == "incomplete"


def _import_contacts(phone: FakeStoragePhone) -> None:
    """Klient zaimportował plik `.vcf`: kontakty są na telefonie."""
    for cid, name, mime, value in (("1", "Jan Kowalski", tel.M_PHONE, A), ("2", "Żaneta Łęcka", tel.M_PHONE, B),
                                   ("3", "Biuro", tel.M_EMAIL, "biuro@firma.pl")):
        phone.providers["contacts"].append({"_id": cid, "starred": "0", "display_name": name})
        phone.providers["raw_contacts"].append({"_id": cid, "contact_id": cid, "deleted": "0",
                                                "account_type": None, "account_name": None})
        phone.providers["data"].append({**{c: None for c in tel.DATA_COLS}, "contact_id": cid,
                                        "raw_contact_id": cid, "mimetype": mime, "data1": value})


def test_manual_step_dropped_after_import(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path, helper_denied={"contacts"}, install_blocked=True)
    run = Run(phone, copy)
    assert [m.kind for m in run().manual] == ["contacts"]
    _import_contacts(phone)
    again = run()
    assert again.manual == [] and again.kinds["contacts"].manual == 0
    assert again.kinds["contacts"].existed == 3 and again.status == "complete"
    st = _state(copy)
    try:
        assert st.get_meta("tel_manual") == []
    finally:
        st.close()


def test_contacts_file_written_before_role_tap(tmp_path):
    copy, phone = _copy(tmp_path), _new(tmp_path, helper_denied={"contacts", "sms", "mms"},
                                        companion_denied={"contacts"}, role_needs_tap=True)
    seen: list[tuple[bool, bool]] = []

    def on_tap(req):
        if req == "sms_role_grant":
            vcf = list((phone.root / "sdcard" / "Download").glob("admenot-kontakty-*.vcf"))
            seen.append((bool(vcf), any("text/x-vcard" in s for s in phone.started)))
            phone.tap_role(PKG)

    r = Run(phone, copy)(on_tap=on_tap)
    assert seen == [(True, False)]  # plik kontaktów leży, zanim program czeka na stuknięcie; żadne okno nie jest otwierane
    assert r.kinds["contacts"].path == FILE and r.kinds["sms"].path == CO
    assert [m.kind for m in r.manual] == ["contacts"] and r.cleanup.ok


def test_chunks_of_at_most_500(tmp_path, monkeypatch):
    copy, phone = _copy(tmp_path), _new(tmp_path)
    assert rt.BATCH == 500
    monkeypatch.setattr(rt, "BATCH", 2)
    run = Run(phone, copy)
    r = run()
    assert _counts(phone) == EXPECTED and r.status == "complete"
    writes = [c for c in phone.commands if "app_process" in c]
    assert len(writes) == 2 + 3 + 1 + 2  # kontakty 3, SMS 5, MMS 1, połączenia 4 — po 2
    assert [(p.done, p.total) for p in run.progress if p.kind == "sms"] == [(0, 5), (2, 5), (4, 5), (5, 5)]


# --------------------------------------------------------------------------------------
# Pliki drogi 3
# --------------------------------------------------------------------------------------
def test_messages_xml_roundtrip(tmp_path):
    copy = _copy(tmp_path)
    plan = build_tel_plan(_new(tmp_path), copy, copy.read_meta(), {"sms", "mms"})
    path = tmp_path / "out.xml"
    path.write_text(messages_xml(plan.sms, plan.mms), encoding="utf-8")
    assert read_sms_xml(path) == plan.sms
    (got,) = read_mms_xml(path, None)
    (want,) = plan.mms
    assert (got.date, got.msg_box, got.addrs, got.read) == (want.date, want.msg_box, want.addrs, want.read)
    img = next(p for p in got.parts if p.content_type == "image/jpeg")
    assert img.file is not None and img.file.read_bytes() == IMG
    assert [p.text for p in got.parts if p.content_type == "text/plain"] == ["Zdjęcie z wakacji"]


def test_contacts_vcf_roundtrip(tmp_path):
    copy = _copy(tmp_path)
    plan = build_tel_plan(_new(tmp_path), copy, copy.read_meta(), {"contacts"})
    path = tmp_path / "k.vcf"
    path.write_text(contacts_vcf(plan.contacts.write), encoding="utf-8", newline="")
    got = read_vcards(path)
    assert [(c.display, c.starred) for c in got] == [("Jan Kowalski", True), ("Żaneta Łęcka", False),
                                                     ("Biuro", False)]


def test_messages_xml_skips_missing_part_file(tmp_path):
    copy = _copy(tmp_path)
    plan = build_tel_plan(_new(tmp_path), copy, copy.read_meta(), {"sms", "mms"})
    for part in plan.mms[0].parts:
        if part.file is not None:
            part.file.unlink()
    path = tmp_path / "out.xml"
    path.write_text(messages_xml([], plan.mms), encoding="utf-8")
    (got,) = read_mms_xml(path, None)
    assert [p.text for p in got.parts] == ["Zdjęcie z wakacji"]


def test_manual_step_shape():
    assert ManualStep("sms", "/sdcard/Download/x.xml").kind == "sms"
