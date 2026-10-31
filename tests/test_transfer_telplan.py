from __future__ import annotations

from datetime import datetime
from pathlib import Path

from faketransfer import FakeStoragePhone, write_provider

from admenot.engine.transfer import telephony as tel
from admenot.engine.transfer.store import CopyDir, CopyMeta
from admenot.engine.transfer.telplan import (
    LOCAL_ACCOUNT_TYPES,
    MESSENGER_ACCOUNT_TYPES,
    ContactIndex,
    build_tel_plan,
    call_key,
    call_key_row,
    local_account,
    mms_key,
    mms_key_row,
    parse_accounts,
    record_id,
    select_contacts,
    sms_key,
    sms_key_row,
)
from admenot.engine.transfer.telrecords import (
    CallRecord,
    ContactRecord,
    DataRow,
    MmsRecord,
    SmsRecord,
)

CONTACTS_URI = "content://com.android.contacts/contacts"
RAW_URI = "content://com.android.contacts/raw_contacts"
DATA_URI = "content://com.android.contacts/data"


# --------------------------------------------------------------------------------------
# Rekordy kontaktów
# --------------------------------------------------------------------------------------
def _row(mimetype: str, data1: str, **extra: str) -> DataRow:
    return DataRow(mimetype, (("data1", data1), *extra.items(), ("is_primary", "0")))


def _name(n: str) -> DataRow:
    return _row(tel.M_NAME, n)


def _phone(n: str, primary: str = "0") -> DataRow:
    return DataRow(tel.M_PHONE, (("data1", n), ("data2", "2"), ("is_primary", primary)))


def _contact(sid: str, display: str | None, accounts: tuple[tuple[str, str], ...], *rows: DataRow
             ) -> ContactRecord:
    return ContactRecord(sid, display, False, accounts, tuple(rows))


GOOGLE = ("com.google", "a@x")
WHATSAPP = ("com.whatsapp", "WhatsApp")


def test_messenger_types_cover_the_brief():
    assert {"com.whatsapp", "com.whatsapp.w4b", "org.telegram.messenger", "org.thoughtcrime.securesms",
            "com.viber.voip", "com.facebook.orca", "com.skype.contacts.sync", "jp.naver.line.android",
            "com.imo.android.imoim"} <= MESSENGER_ACCOUNT_TYPES
    assert LOCAL_ACCOUNT_TYPES["vnd.sec.contact.phone"] == ("vnd.sec.contact.phone", "vnd.sec.contact.phone")


def test_account_present_but_not_synced_writes():
    c = _contact("1", "Jan", (GOOGLE,), _name("Jan"), _phone("+48600100200"))
    sel = select_contacts([c], synced=set())  # konto jest w dumpsys, ale surowych kontaktów brak
    assert sel.write == [c] and sel.skipped_synced == {} and sel.skipped_messenger == 0


def test_synced_account_skipped_and_counted():
    a = _contact("1", "Jan", (GOOGLE,), _name("Jan"), _phone("+48600100200"))
    b = _contact("2", "Ewa", (GOOGLE,), _name("Ewa"), _phone("+48600100201"))
    c = _contact("3", "Ola", (("", ""),), _name("Ola"), _phone("+48600100202"))
    sel = select_contacts([a, b, c], synced={GOOGLE})
    assert sel.write == [c]
    assert sel.skipped_synced == {"a@x": 2}


def test_missing_google_account_written():
    c = _contact("1", "Jan", (("com.google", "gone@x"),), _name("Jan"), _phone("+48600100200"))
    sel = select_contacts([c], synced={GOOGLE})
    assert sel.write == [c] and sel.skipped_synced == {}


def test_messenger_only_contact_skipped():
    c = _contact("1", "Jan WA", (WHATSAPP,), _name("Jan WA"), _phone("+48600100200"))
    sel = select_contacts([c], synced=set())
    assert sel.write == [] and sel.skipped_messenger == 1


def test_local_plus_whatsapp_keeps_local_rows_only():
    c = _contact(
        "1", "Jan", (("", ""), WHATSAPP),
        _name("Jan"), _phone("+48 600 100 200", "1"), _row(tel.M_NOTE, "notatka"),
        _name("Jan"), _phone("+48600100200"),  # te same dane z surowego kontaktu WhatsApp
        DataRow("vnd.android.cursor.item/phone_v2", (("data1", "600-100-200"), ("is_primary", "0"))))
    sel = select_contacts([c], synced=set())
    assert sel.skipped_messenger == 0 and len(sel.write) == 1
    out = sel.write[0]
    assert out.accounts == (("", ""),)
    assert [r.mimetype for r in out.rows] == [tel.M_NAME, tel.M_PHONE, tel.M_NOTE]
    assert dict(out.rows[1].values)["data1"] == "+48 600 100 200"


# --------------------------------------------------------------------------------------
# „Kontakt istnieje”
# --------------------------------------------------------------------------------------
def _index(contacts: list[tuple[str, str]], data: list[tuple[str, str, str]]) -> ContactIndex:
    return ContactIndex.from_rows(
        [{"_id": i, "display_name": n} for i, n in contacts],
        [{"contact_id": cid, "mimetype": m, "data1": v} for cid, m, v in data])


def test_contact_exists_by_name_and_phone():
    idx = _index([("1", "Jan Kowalski")], [("1", tel.M_PHONE, "601234567")])
    c = _contact("9", "  jan KOWALSKI ", (), _phone("+48 601 234 567"))
    assert idx.has(c)


def test_contact_without_phones_matched_by_email():
    idx = _index([("1", "Biuro")], [("1", tel.M_EMAIL, "Biuro@Firma.pl")])
    c = _contact("9", "Biuro", (), _row(tel.M_EMAIL, "biuro@firma.pl"))
    assert idx.has(c)
    assert not idx.has(_contact("9", "Biuro", (), _row(tel.M_EMAIL, "inny@firma.pl")))


def test_same_name_other_phone_not_existing():
    idx = _index([("1", "Jan Kowalski")], [("1", tel.M_PHONE, "601234567")])
    assert not idx.has(_contact("9", "Jan Kowalski", (), _phone("+48 777 000 111")))
    assert not idx.has(_contact("9", "Ktoś Inny", (), _phone("601234567")))


# --------------------------------------------------------------------------------------
# Klucze
# --------------------------------------------------------------------------------------
def test_keys_match_between_record_and_phone_row():
    sms = SmsRecord("+48 601 234 567", 1700, 0, 1, 1, -1, None, "treść")
    row = {"address": "601234567", "date": "1700", "type": "1", "body": "treść"}
    assert sms_key(sms) == sms_key_row(row) == (1700, 1, "601234567", "treść")
    call = CallRecord("+48601234567", 5, 10, 2, 1, None)
    assert call_key(call) == call_key_row({"number": "601234567", "date": "5", "type": "2"}) == (5, 2, "601234567")
    mms = MmsRecord(1_700_000_000_000, 0, 1, 1, None, (("+48600100200", 137), ("insert-address-token", 151)), ())
    row_m = {"date": "1700000000", "msg_box": "1"}
    addrs = [{"address": "600100200"}, {"address": "insert-address-token"}]
    assert mms_key(mms) == mms_key_row(row_m, addrs) == (1_700_000_000_000, 1, ("", "600100200"))
    assert record_id(("a", 1)) == record_id(("a", 1)) != record_id(("a", 2))
    assert len(record_id(("a", 1))) == 40


# --------------------------------------------------------------------------------------
# dumpsys account
# --------------------------------------------------------------------------------------
OPPO_ACCOUNTS = """\
User UserInfo{0:Właściciel:c13}:
  Accounts: 1
    Account {name=konto-1@gmail.com, type=com.google}

  AccountId, Action_Type, timestamp, UID, TableName, Key
  Accounts History
  -1,action_called_account_remove,2010-01-01 01:10:54,10213,accounts,0
  1,action_account_add,2026-09-26 13:07:14,10102,accounts,2

  Active Sessions: 0

  RegisteredServicesCache: 9 services
    ServiceInfo: AuthenticatorDescription {type=com.google.android.gm.pop3}, ComponentInfo{com.google.android.gm/x}, uid 10122
    ServiceInfo: AuthenticatorDescription {type=com.google}, ComponentInfo{com.google.android.gms/y}, uid 10102
  Account visibility:
    konto-1@gmail.com
      com.google.android.apps.maps, 2
"""
XIAOMI_ACCOUNTS = """\
User UserInfo{0:Właściciel:c13}:
  Accounts: 0

  AccountId, Action_Type, timestamp, UID, TableName, Key
  Accounts History
  -1,action_called_account_add,2026-10-27 20:11:24,1000,accounts,1

  Active Sessions: 0

  RegisteredServicesCache: 9 services
    ServiceInfo: AuthenticatorDescription {type=com.google.android.gm.pop3}, ...
"""
SAMSUNG_ACCOUNTS = """\
User UserInfo{0:Owner:c13}:
  Accounts: 2
    Account {name=jan@gmail.com, type=com.google}
    Account {name=Jan, Kowalski, type=com.osp.app.signin}

  Active Sessions: 0
"""


def test_parse_accounts_samsung_and_xiaomi():
    assert parse_accounts(OPPO_ACCOUNTS) == {("com.google", "konto-1@gmail.com")}
    assert parse_accounts(XIAOMI_ACCOUNTS) == set()
    assert parse_accounts(SAMSUNG_ACCOUNTS) == {("com.google", "jan@gmail.com"),
                                                ("com.osp.app.signin", "Jan, Kowalski")}
    assert parse_accounts("") == set()


def test_local_account_only_when_such_raw_contacts_exist():
    sam = {"account_type": "vnd.sec.contact.phone", "account_name": "vnd.sec.contact.phone", "deleted": "0"}
    assert local_account([sam]) == ("vnd.sec.contact.phone", "vnd.sec.contact.phone")
    assert local_account([{**sam, "deleted": "1"}]) is None
    assert local_account([{"account_type": None, "account_name": None, "deleted": "0"},
                          {"account_type": "com.google", "account_name": "a@x", "deleted": "0"}]) is None
    assert local_account([]) is None


# --------------------------------------------------------------------------------------
# build_tel_plan na atrapie nowego telefonu
# --------------------------------------------------------------------------------------
def _meta() -> CopyMeta:
    now = datetime(2026, 10, 31, 12, 0)
    return CopyMeta(id="x/y", serial="S", manufacturer="m", model="m", android="13", imei=None, client=None,
                    created=now, expires=now, status="complete", selection={"exports": []})


def _dump(rows: list[dict], cols: list[str]) -> str:
    return "\n".join(
        f"Row: {i} " + ", ".join(f"{c}={'NULL' if r.get(c) is None else r[c]}" for c in cols)
        for i, r in enumerate(rows)) + "\n"


class PhoneWithAccounts(FakeStoragePhone):
    dumpsys = ""

    def _shell(self, command: str) -> bytes:
        if command.startswith("dumpsys account"):
            return self.dumpsys.encode("utf-8")
        return super()._shell(command)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def _copy(tmp_path: Path, *, contacts: bool = False, sms: bool = False, calls: bool = False,
          mms: bool = False) -> CopyDir:
    copy = CopyDir(tmp_path / "copy")
    ph = copy.phone_dir
    ph.mkdir(parents=True)
    if contacts:
        _write(ph / "raw/contacts.txt", _dump(
            [{"_id": "1", "starred": "0", "display_name": "Jan Kowalski"},
             {"_id": "2", "starred": "0", "display_name": "Ewa Nowak"}], tel.CONTACT_COLS))
        _write(ph / "raw/raw_contacts.txt", _dump(
            [{"_id": "10", "contact_id": "1", "deleted": "0", "account_type": "com.google", "account_name": "a@x"},
             {"_id": "20", "contact_id": "2", "deleted": "0", "account_type": None, "account_name": None}],
            tel.RAW_COLS))
        data = [
            {"contact_id": "1", "raw_contact_id": "10", "mimetype": tel.M_NAME, "data1": "Jan Kowalski"},
            {"contact_id": "1", "raw_contact_id": "10", "mimetype": tel.M_PHONE, "data1": "+48 601 234 567"},
            {"contact_id": "2", "raw_contact_id": "20", "mimetype": tel.M_NAME, "data1": "Ewa Nowak"},
            {"contact_id": "2", "raw_contact_id": "20", "mimetype": tel.M_PHONE, "data1": "+48 700 800 900"},
        ]
        _write(ph / "raw/contacts_data.txt", _dump(
            [{**{c: None for c in tel.DATA_COLS}, "is_primary": "0", **d} for d in data], tel.DATA_COLS))
    if sms:
        _write(ph / "sms.xml", tel.build_sms_xml(
            [{"address": "+48601234567", "date": str(1700000000000 + i), "type": "1", "read": "1",
              "status": "-1", "body": f"wiadomość {i}"} for i in range(3)], {}))
    if calls:
        _write(ph / "calls.xml", tel.build_calls_xml(
            [{"number": "+48601234567", "date": str(1700000000000 + i), "duration": "5", "type": "2",
              "presentation": "1", "name": None} for i in range(2)], {}))
    if mms:
        def one(date: str, other: str) -> str:
            return (f'<mms date="{date}" date_sent="0" msg_box="1" read="1">'
                    f'<parts/><addrs><addr address="{other}" type="137"/>'
                    f'<addr address="insert-address-token" type="151"/></addrs></mms>')
        _write(ph / "mms.xml", "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n<smses count=\"2\">"
               + one("1700000100000", "+48601234567") + one("1700000200000", "+48700800900") + "</smses>")
    return copy


def _new_phone(tmp_path: Path) -> PhoneWithAccounts:
    return PhoneWithAccounts(tmp_path / "new")


def test_plan_filters_existing_sms_calls_mms(tmp_path):
    copy = _copy(tmp_path, sms=True, calls=True, mms=True)
    phone = _new_phone(tmp_path)
    cols = tel.SMS_COLS[0]
    write_provider(phone.root, "content://call_log/calls", [
        {"_id": "1", "number": "601234567", "date": "1700000000000", "duration": "9", "type": "2",
         "presentation": "1", "subscription_id": "1", "name": None}], tel.CALL_COLS[0])
    write_provider(phone.root, "content://mms", [{"_id": "5", "date": "1700000100", "msg_box": "1"}],
                   ["_id", "date", "msg_box"])
    write_provider(phone.root, "content://mms/5/addr", [
        {"type": "137", "address": "601234567"}, {"type": "151", "address": "insert-address-token"}],
        ["type", "address"])
    write_provider(phone.root, "content://sms", [
        {**{c: "0" for c in cols}, "_id": "1", "address": "601234567", "date": "1700000000001",
         "type": "1", "subject": None, "body": "wiadomość 1"}], cols)

    plan = build_tel_plan(phone, copy, _meta(), {"sms", "calls", "mms"})
    assert plan.existing == {"sms": 1, "calls": 1, "mms": 1}
    assert [r.body for r in plan.sms] == ["wiadomość 0", "wiadomość 2"]
    assert [r.date for r in plan.calls] == [1700000000001]
    assert [r.date for r in plan.mms] == [1700000200000]
    assert plan.readable == {"sms": True, "calls": True, "mms": True}
    assert plan.contacts is None and plan.local_account is None


def test_plan_unreadable_new_phone_filters_nothing(tmp_path):
    copy = _copy(tmp_path, sms=True)
    phone = _new_phone(tmp_path)
    phone.deny_uris.add("content://sms")
    plan = build_tel_plan(phone, copy, _meta(), {"sms"})
    assert plan.readable == {"sms": False} and len(plan.sms) == 3 and plan.existing.get("sms", 0) == 0


def test_plan_contacts_denied_writes_all(tmp_path):
    copy = _copy(tmp_path, contacts=True)
    phone = _new_phone(tmp_path)
    phone.deny_uris.add(CONTACTS_URI)
    phone.dumpsys = OPPO_ACCOUNTS.replace("konto-1@gmail.com", "a@x")
    plan = build_tel_plan(phone, copy, _meta(), {"contacts"})
    assert plan.readable["contacts"] is False
    assert plan.contacts is not None and len(plan.contacts.write) == 2
    assert plan.contacts.skipped_synced == {} and plan.phone_has_contacts is False


def _write_new_contacts(phone: FakeStoragePhone, raws: list[dict], contacts: list[dict], data: list[dict]) -> None:
    write_provider(phone.root, CONTACTS_URI, contacts, tel.CONTACT_COLS)
    write_provider(phone.root, RAW_URI, raws, tel.RAW_COLS)
    write_provider(phone.root, DATA_URI,
                   [{**{c: None for c in tel.DATA_COLS}, "is_primary": "0", **d} for d in data], tel.DATA_COLS)


def test_plan_account_synced_skips_and_existing_counts(tmp_path):
    copy = _copy(tmp_path, contacts=True)
    phone = _new_phone(tmp_path)
    phone.dumpsys = OPPO_ACCOUNTS.replace("konto-1@gmail.com", "a@x")
    _write_new_contacts(
        phone,
        [{"_id": "1", "contact_id": "7", "deleted": "0", "account_type": "com.google", "account_name": "a@x"},
         {"_id": "2", "contact_id": "8", "deleted": "0", "account_type": "vnd.sec.contact.phone",
          "account_name": "vnd.sec.contact.phone"}],
        [{"_id": "7", "starred": "0", "display_name": "Ktoś"}, {"_id": "8", "starred": "0", "display_name": "Ewa Nowak"}],
        [{"contact_id": "8", "raw_contact_id": "2", "mimetype": tel.M_PHONE, "data1": "700800900"}])
    plan = build_tel_plan(phone, copy, _meta(), {"contacts"})
    assert plan.readable["contacts"] is True and plan.phone_has_contacts is True
    assert plan.contacts.skipped_synced == {"a@x": 1}  # Jan z konta zsynchronizowanego
    assert plan.contacts.write == []  # Ewa już jest (nazwa + numer)
    assert plan.existing["contacts"] == 1
    assert plan.local_account == ("vnd.sec.contact.phone", "vnd.sec.contact.phone")


def test_plan_account_present_without_raw_contacts_writes(tmp_path):
    copy = _copy(tmp_path, contacts=True)
    phone = _new_phone(tmp_path)
    phone.dumpsys = OPPO_ACCOUNTS.replace("konto-1@gmail.com", "a@x")
    _write_new_contacts(phone, [], [], [])
    plan = build_tel_plan(phone, copy, _meta(), {"contacts"})
    assert plan.readable["contacts"] is True and plan.phone_has_contacts is False
    assert len(plan.contacts.write) == 2 and plan.contacts.skipped_synced == {}
