"""Plan telefonii: co z kopii nowy telefon jeszcze potrzebuje.

Czyta to, co jest już na nowym telefonie (kontakty, SMS, MMS, połączenia), stosuje klucze duplikatów
i wybiera konta kontaktów do pominięcia. Niczego nie zapisuje na telefonie — tylko `content query`
i `dumpsys account`. Odmowa odczytu kategorii (`readable[kind] = False`) niczego nie odfiltrowuje:
duplikatom przy wznowieniu zapobiega i tak stan per rekord. Wyjątek: MMS bez odczytanych kluczy
(także po błędzie odczytu adresów którejś wiadomości) nie trafiają na telefon, tylko do pliku
(`restore_tel`).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..adb.transport import AdbError, AdbTransport
from . import telephony as tel
from .mms import _ms
from .store import CopyDir, CopyMeta
from .telrecords import (
    CallRecord,
    ContactRecord,
    DataRow,
    MmsRecord,
    SmsRecord,
    TelSources,
    copy_sources,
    read_calls_xml,
    read_mms_xml,
    read_raw_contacts,
    read_sms_xml,
    read_vcards,
)

CONTACTS_URI = "content://com.android.contacts/contacts"
RAW_URI = "content://com.android.contacts/raw_contacts"
DATA_URI = "content://com.android.contacts/data"
MMS_HEADER_COLS = [["_id", "date", "msg_box"]]
MMS_ADDR_COLS = ["type", "address"]

MESSENGER_ACCOUNT_TYPES: frozenset[str] = frozenset({
    "com.whatsapp", "com.whatsapp.w4b", "org.telegram.messenger", "org.thoughtcrime.securesms",
    "com.viber.voip", "com.facebook.orca", "com.skype.contacts.sync", "jp.naver.line.android",
    "com.imo.android.imoim",
})

# typ konta lokalnego producenta -> (typ, nazwa), pod którym telefon trzyma kontakty „w pamięci telefonu”.
# OPPO (Google Contacts) zapisuje je bez konta (null/null) — to wynik `None`, wpisu nie trzeba.
LOCAL_ACCOUNT_TYPES: dict[str, tuple[str, str]] = {
    "vnd.sec.contact.phone": ("vnd.sec.contact.phone", "vnd.sec.contact.phone"),
}


# --------------------------------------------------------------------------------------
# Klucze duplikatów (spec §5.4)
# --------------------------------------------------------------------------------------
def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def sms_key(r: SmsRecord) -> tuple:
    return (r.date, r.type, tel.phone_key(r.address), r.body)


def sms_key_row(row: dict) -> tuple:
    return (_int(row.get("date")), _int(row.get("type")), tel.phone_key(row.get("address")),
            row.get("body") or "")


def call_key(r: CallRecord) -> tuple:
    return (r.date, r.type, tel.phone_key(r.number))


def call_key_row(row: dict) -> tuple:
    return (_int(row.get("date")), _int(row.get("type")), tel.phone_key(row.get("number")))


def mms_key(r: MmsRecord) -> tuple:
    return (r.date, r.msg_box, tuple(sorted(tel.phone_key(a) for a, _ in r.addrs)))


def mms_key_row(row: dict, addrs: list[dict]) -> tuple:
    """Klucz wiadomości MMS z telefonu: nagłówek (`date` w sekundach lub ms) i jej wiersze `addr`."""
    return (_int(_ms(row.get("date"))), _int(row.get("msg_box")),
            tuple(sorted(tel.phone_key(a.get("address")) for a in addrs)))


def record_id(key: tuple) -> str:
    return hashlib.sha1(repr(key).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# Kontakty
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ContactSelection:
    write: list[ContactRecord]
    skipped_synced: dict[str, int]  # nazwa konta -> liczba pominiętych kontaktów (tylko do UI)
    skipped_messenger: int


def _row_identity(r: DataRow) -> tuple:
    vals = dict(r.values)
    if r.mimetype == tel.M_PHONE:
        d1 = vals.get("data1") or ""
        return (r.mimetype, tel.phone_key(d1) or re.sub(r"\s", "", d1))
    return (r.mimetype, tuple((k, v) for k, v in r.values if k != "is_primary"))


def _reduce_rows(rows: tuple[DataRow, ...]) -> tuple[DataRow, ...]:
    """Wiersze surowego kontaktu komunikatora dublują dane kontaktu lokalnego — zostaje pierwszy z każdych."""
    seen: set[tuple] = set()
    out = []
    for r in rows:
        ident = _row_identity(r)
        if ident not in seen:
            seen.add(ident)
            out.append(r)
    return tuple(out)


def select_contacts(contacts: list[ContactRecord], synced: set[tuple[str, str]]) -> ContactSelection:
    write: list[ContactRecord] = []
    skipped: dict[str, int] = {}
    messenger = 0
    for c in contacts:
        own = tuple(a for a in c.accounts if a[0] not in MESSENGER_ACCOUNT_TYPES)
        if c.accounts and not own:
            messenger += 1
            continue
        if own and all(a in synced for a in own):
            skipped[own[0][1]] = skipped.get(own[0][1], 0) + 1
            continue
        write.append(ContactRecord(c.source_id, c.display, c.starred, own, _reduce_rows(c.rows)))
    return ContactSelection(write, skipped, messenger)


def _norm_name(v: str | None) -> str:
    return (v or "").strip().casefold()


class ContactIndex:
    """Kontakty obecne na telefonie: nazwa -> numery (`phone_key`) i e-maile."""

    def __init__(self) -> None:
        self._by_name: dict[str, list[tuple[set[str], set[str]]]] = {}

    @classmethod
    def from_rows(cls, contacts: list[dict], data: list[dict]) -> ContactIndex:
        phones: dict[str, set[str]] = {}
        emails: dict[str, set[str]] = {}
        for d in data:
            cid, mime, v = d.get("contact_id"), d.get("mimetype"), d.get("data1")
            if cid is None or not v:
                continue
            if mime == tel.M_PHONE:
                if k := tel.phone_key(v):
                    phones.setdefault(cid, set()).add(k)
            elif mime == tel.M_EMAIL:
                emails.setdefault(cid, set()).add(v.strip().casefold())
        idx = cls()
        for c in contacts:
            cid = c.get("_id")
            name = _norm_name(c.get("display_name"))
            if cid is None or not name:
                continue
            idx._by_name.setdefault(name, []).append((phones.get(cid, set()), emails.get(cid, set())))
        return idx

    def has(self, c: ContactRecord) -> bool:
        name = _norm_name(c.display)
        if not name:
            return False
        my_phones = {k for r in c.rows if r.mimetype == tel.M_PHONE
                     if (k := tel.phone_key(dict(r.values).get("data1")))}
        my_emails = {v.strip().casefold() for r in c.rows if r.mimetype == tel.M_EMAIL
                     if (v := dict(r.values).get("data1"))}
        for ph, em in self._by_name.get(name, []):
            if my_phones:
                if my_phones & ph:
                    return True
            elif my_emails & em:
                return True
        return False


_ACCOUNTS_HEAD = re.compile(r"^\s*Accounts:\s*\d+\s*$")
_ACCOUNT = re.compile(r"^\s*Account \{name=(.*), type=([^,{}]*)\}\s*$")


def parse_accounts(dumpsys: str) -> set[tuple[str, str]]:
    """Konta z sekcji `Accounts: N` wyjścia `dumpsys account` (lista `RegisteredServicesCache` to
    uwierzytelniacze zainstalowanych aplikacji, nie konta)."""
    out: set[tuple[str, str]] = set()
    inside = False
    for line in dumpsys.replace("\r\n", "\n").split("\n"):
        if _ACCOUNTS_HEAD.match(line):
            inside = True
            continue
        if not inside:
            continue
        if m := _ACCOUNT.match(line):
            out.add((m.group(2), m.group(1)))
        else:
            inside = False
    return out


def local_account(raw_rows_new_phone: list[dict]) -> tuple[str, str] | None:
    """Konto lokalne producenta, jeśli nowy telefon ma już takie surowe kontakty; inaczej `None`
    (kontakt bez konta)."""
    for r in raw_rows_new_phone:
        if r.get("deleted") == "1":
            continue
        if (found := LOCAL_ACCOUNT_TYPES.get(r.get("account_type") or "")) is not None:
            return found
    return None


# --------------------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------------------
@dataclass
class TelPlan:
    sources: TelSources
    contacts: ContactSelection | None
    sms: list[SmsRecord]
    mms: list[MmsRecord]
    calls: list[CallRecord]
    existing: dict[str, int]
    phone_has_contacts: bool
    readable: dict[str, bool]
    local_account: tuple[str, str] | None
    # ile wpisów kategorii telefon ma teraz (tylko odczytane kategorie): mniej niż stan wgrywania
    # pamięta jako zapisane = telefon wyczyszczono po poprzedniej próbie
    on_phone: dict[str, int] = field(default_factory=dict)


def _synced_accounts(adb: AdbTransport, raws: list[dict]) -> set[tuple[str, str]]:
    try:
        text = adb.shell("dumpsys account", timeout=30)
    except AdbError as exc:
        if exc.kind in tel._CONNECTION_KINDS:
            raise
        return set()
    present = {(r.get("account_type") or "", r.get("account_name") or "")
               for r in raws if r.get("deleted") != "1"}
    return parse_accounts(text) & present


def _plan_contacts(adb: AdbTransport, copy: CopyDir, src: TelSources
                   ) -> tuple[ContactSelection, int, int, bool, tuple[str, str] | None]:
    """(wybór, liczba pominiętych jako obecne, ile kontaktów ma telefon, czy dało się odczytać, konto lokalne)."""
    records = (read_raw_contacts(copy.phone_dir) if src.contacts == "raw"
               else read_vcards(copy.phone_dir / "contacts.vcf"))
    try:
        rows_c = tel.content_query(adb, CONTACTS_URI, tel.CONTACT_COLS)
        rows_r = tel.content_query(adb, RAW_URI, tel.RAW_COLS)
        rows_d = tel.content_query(adb, DATA_URI, tel.DATA_COLS)
    except tel.ContentQueryError:
        return select_contacts(records, set()), 0, 0, False, None
    deleted = {r["_id"] for r in rows_r if r.get("deleted") == "1"}
    live_d = [d for d in rows_d if d.get("raw_contact_id") not in deleted]
    sel = select_contacts(records, _synced_accounts(adb, rows_r))
    index = ContactIndex.from_rows(rows_c, live_d)
    fresh = [c for c in sel.write if not index.has(c)]
    present = len(sel.write) - len(fresh)
    sel = ContactSelection(fresh, sel.skipped_synced, sel.skipped_messenger)
    return sel, present, len(rows_c), True, local_account(rows_r)


def _keys_from_phone(adb: AdbTransport, uri: str, col_sets: list[list[str]], key_row: Any) -> set[tuple] | None:
    try:
        _, rows = tel.query_with_fallback(adb, uri, col_sets)
    except tel.ContentQueryError:
        return None
    return {key_row(r) for r in rows}


def _mms_keys_from_phone(adb: AdbTransport, need_addrs: bool) -> set[tuple] | None:
    """Klucze MMS z telefonu; `None` = nie dało się ich odczytać — także gdy padł odczyt adresów
    którejkolwiek wiadomości (klucz bez adresów nigdy by się nie zgodził i MMS poszłyby drugi raz)."""
    try:
        _, rows = tel.query_with_fallback(adb, "content://mms", MMS_HEADER_COLS)
    except tel.ContentQueryError:
        return None
    if not need_addrs:
        return set()
    keys = set()
    for r in rows:
        try:
            addrs = tel.content_query(adb, f"content://mms/{r['_id']}/addr", MMS_ADDR_COLS)
        except tel.ContentQueryError:
            return None
        keys.add(mms_key_row(r, addrs))
    return keys


def phone_has(adb: AdbTransport, kind: str) -> Callable[[Any], bool] | None:
    """Predykat „ten rekord kopii już jest na telefonie” z nowego odczytu kategorii `kind` (te same
    klucze co plan; po urwanym zapisie wiersze zapisane przed urwaniem nie mają linii `OK`).
    `None` = telefon odmówił odczytu. `AdbError` rozłączenia przechodzi wyżej."""
    if kind == "contacts":
        try:
            rows_c = tel.content_query(adb, CONTACTS_URI, tel.CONTACT_COLS)
            rows_r = tel.content_query(adb, RAW_URI, tel.RAW_COLS)
            rows_d = tel.content_query(adb, DATA_URI, tel.DATA_COLS)
        except tel.ContentQueryError:
            return None
        deleted = {r["_id"] for r in rows_r if r.get("deleted") == "1"}
        return ContactIndex.from_rows(rows_c, [d for d in rows_d if d.get("raw_contact_id") not in deleted]).has
    if kind == "mms":
        have = _mms_keys_from_phone(adb, True)
        key: Callable[[Any], tuple] = mms_key
    elif kind == "sms":
        have, key = _keys_from_phone(adb, "content://sms", tel.SMS_COLS, sms_key_row), sms_key
    elif kind == "calls":
        have, key = _keys_from_phone(adb, "content://call_log/calls", tel.CALL_COLS, call_key_row), call_key
    else:
        raise ValueError(f"unknown kind {kind!r}")
    if have is None:
        return None
    return lambda r: key(r) in have


def build_tel_plan(adb: AdbTransport, copy: CopyDir, meta: CopyMeta, kinds: set[str]) -> TelPlan:
    src = copy_sources(copy, meta)
    readable: dict[str, bool] = {}
    existing: dict[str, int] = {}
    on_phone: dict[str, int] = {}
    selection: ContactSelection | None = None
    has_contacts = False
    local: tuple[str, str] | None = None
    sms: list[SmsRecord] = []
    mms: list[MmsRecord] = []
    calls: list[CallRecord] = []

    if "contacts" in kinds and src.contacts is not None:
        selection, skipped, count, readable["contacts"], local = _plan_contacts(adb, copy, src)
        has_contacts = bool(count)
        if readable["contacts"]:
            existing["contacts"] = skipped
            on_phone["contacts"] = count
    if "sms" in kinds and src.sms is not None:
        sms = read_sms_xml(src.sms)
        have = _keys_from_phone(adb, "content://sms", tel.SMS_COLS, sms_key_row)
        readable["sms"] = have is not None
        if have is not None:
            on_phone["sms"] = len(have)
        if have:
            kept = [r for r in sms if sms_key(r) not in have]
            existing["sms"] = len(sms) - len(kept)
            sms = kept
    if "calls" in kinds and src.calls is not None:
        calls = read_calls_xml(src.calls)
        have = _keys_from_phone(adb, "content://call_log/calls", tel.CALL_COLS, call_key_row)
        readable["calls"] = have is not None
        if have is not None:
            on_phone["calls"] = len(have)
        if have:
            kept = [r for r in calls if call_key(r) not in have]
            existing["calls"] = len(calls) - len(kept)
            calls = kept
    if "mms" in kinds and src.mms is not None:
        # MMS z eksportu SB&R (ten sam plik co SMS) mają załączniki w base64, bez `mms_parts`
        mms = read_mms_xml(src.mms, None if src.mms == src.sms else copy.phone_dir / "mms_parts")
        have = _mms_keys_from_phone(adb, bool(mms))
        readable["mms"] = have is not None
        if have is not None:
            on_phone["mms"] = len(have)
        if have:
            kept = [r for r in mms if mms_key(r) not in have]
            existing["mms"] = len(mms) - len(kept)
            mms = kept
    return TelPlan(src, selection, sms, mms, calls, existing, has_contacts, readable, local, on_phone)
