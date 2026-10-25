"""Eksport kontaktów (vCard 3.0), SMS i historii połączeń (XML zgodny z „SMS Backup & Restore”).

Dane czytamy przez `content query` z uprawnieniami użytkownika `shell` (AOSP nadaje mu
READ_CONTACTS / READ_SMS / READ_CALL_LOG). Ograniczenia, o których trzeba wiedzieć:
* MMS eksportuje osobny moduł (mms.py). Czaty RCS (Google Messages „czat”) nie są ani
  w content://sms, ani w content://mms – nie da się ich wyeksportować przez ADB.
* Niektóre nakładki (MIUI/HyperOS) blokują odczyt SMS przez adb, dopóki nie włączysz
  „Debugowanie USB (ustawienia zabezpieczeń)” — kategoria dostaje wtedy status `unavailable`.
* Zdjęcia kontaktów nie są eksportowane (BLOB-y nie przechodzą przez `content query`).

Wyjście `content query` zawiera dane klienta — `SessionLogAdb` nie pokazuje go w konsoli GUI.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from admenot.engine.adb.transport import AdbError, AdbTransport

from .guard import q

# Błędy połączenia nie są błędem kategorii — przechodzą wyżej (kopia czeka na telefon).
_CONNECTION_KINDS = {"offline", "no_device", "unauthorized", "adb_missing"}


class ContentQueryError(Exception):
    """`content query` nie zwrócił wierszy; `denied` = odmowa uprawnień (SecurityException)."""

    def __init__(self, message: str, denied: bool = False) -> None:
        super().__init__(message)
        self.denied = denied


class Stopped(Exception):
    """Eksport przerwany na żądanie użytkownika."""


@dataclass(frozen=True)
class CategoryResult:
    status: Literal["ok", "unavailable", "failed"]
    count: int = 0
    error: str | None = None


def is_denied(text: str) -> bool:
    return "SecurityException" in text or "Permission Denial" in text


def failure_result(exc: Exception) -> CategoryResult:
    """Wynik kategorii po błędzie: odmowa uprawnień = `unavailable`, reszta = `failed`."""
    if isinstance(exc, ContentQueryError) and exc.denied:
        return CategoryResult("unavailable", 0, "permission_denied")
    return CategoryResult("failed", 0, str(exc)[:300])


# --------------------------------------------------------------------------------------
# Parser wyjścia `content query`
# --------------------------------------------------------------------------------------
def parse_content_rows(text: str, columns: list[str]) -> list[dict[str, str | None]]:
    """Parsuje wyjście 'Row: N col=val, col=val' przy ZNANEJ kolejności kolumn (projekcja).

    Wiersze mogą zawierać znaki nowej linii i przecinki – dlatego kolejny wiersz
    rozpoznajemy po dokładnym '\\nRow: {k+1} ', a wartości po ', {następna_kolumna}='.
    Kolumnę z najbardziej „dowolnym” tekstem (body, name, data1) dawaj zawsze na koniec.
    """
    text = text.replace("\r\n", "\n")
    if not text.strip() or text.lstrip().startswith("No result found"):
        return []
    if not text.startswith("Row: 0 "):
        raise ContentQueryError(text.strip()[:600], is_denied(text[:600]))
    rows: list[dict[str, str | None]] = []
    k, pos = 0, 0
    while True:
        head = f"Row: {k} "
        start = pos + len(head)
        nxt = text.find(f"\nRow: {k + 1} ", start)
        end = nxt if nxt != -1 else len(text)
        body = text[start:end]
        if nxt == -1:
            body = body.removesuffix("\n")
        rows.append(_parse_row(body, columns, k))
        if nxt == -1:
            return rows
        pos, k = nxt + 1, k + 1


def _parse_row(body: str, columns: list[str], k: int) -> dict[str, str | None]:
    first = columns[0] + "="
    if not body.startswith(first):
        raise ContentQueryError(f"Nieoczekiwany format wiersza {k}: {body[:200]}")
    p = len(first)
    vals: dict[str, str | None] = {}
    for i, col in enumerate(columns):
        if i + 1 < len(columns):
            sep = f", {columns[i + 1]}="
            j = body.find(sep, p)
            if j == -1:
                raise ContentQueryError(f"Brak kolumny '{columns[i + 1]}' w wierszu {k}")
            v, p = body[p:j], j + len(sep)
        else:
            v = body[p:]
        vals[col] = None if v == "NULL" else v
    return vals


def content_query(adb: AdbTransport, uri: str, columns: list[str], sort: str | None = None,
                  raw_sink: Callable[[str], None] | None = None) -> list[dict[str, str | None]]:
    cmd = f"content query --uri {q(uri)} --projection {q(':'.join(columns))}"
    if sort:
        cmd += f" --sort {q(sort)}"
    try:
        out = adb.shell(cmd, timeout=600)
    except AdbError as exc:
        if exc.kind in _CONNECTION_KINDS:
            raise
        raise ContentQueryError(exc.message[:600] or exc.kind, is_denied(exc.message)) from exc
    if raw_sink:
        raw_sink(out)
    head = out[:400]
    if not head.startswith("Row:") and ("Exception" in head or "Error while accessing provider" in head):
        raise ContentQueryError(out.strip()[:600], is_denied(out[:600]))
    return parse_content_rows(out, columns)


def query_with_fallback(adb: AdbTransport, uri: str, col_sets: list[list[str]], sort: str | None = None,
                        raw_sink: Callable[[str], None] | None = None
                        ) -> tuple[list[str], list[dict[str, str | None]]]:
    """Próbuje kolejne zestawy kolumn (starsze Androidy nie mają części kolumn); odmowa kończy próby."""
    last: ContentQueryError | None = None
    for cols in col_sets:
        try:
            return cols, content_query(adb, uri, cols, sort, raw_sink)
        except ContentQueryError as exc:
            last = exc
            if exc.denied:
                break
    assert last is not None
    raise last


# --------------------------------------------------------------------------------------
# Wspólne
# --------------------------------------------------------------------------------------
_BAD_XML = re.compile("[^\u0009\u000a\u000d -퟿-�\U00010000-\U0010ffff]")


def xml_attr(v: str | None) -> str:
    if v is None:
        return "null"
    v = _BAD_XML.sub("", v)
    return (v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            .replace("\n", "&#10;").replace("\r", "&#13;").replace("\t", "&#9;"))


def readable(ms: str | None) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""


def phone_key(num: str | None) -> str:
    d = re.sub(r"\D", "", num or "")
    return d[-9:] if len(d) >= 7 else ""


def atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def count_rows(adb: AdbTransport, uri: str) -> int:
    """Liczba wierszy providera; `ContentQueryError` (z `denied`) przy odmowie dostępu."""
    return len(content_query(adb, uri, ["_id"]))


# --------------------------------------------------------------------------------------
# Kontakty -> vCard 3.0
# --------------------------------------------------------------------------------------
M_NAME = "vnd.android.cursor.item/name"
M_PHONE = "vnd.android.cursor.item/phone_v2"
M_EMAIL = "vnd.android.cursor.item/email_v2"
M_ADDR = "vnd.android.cursor.item/postal-address_v2"
M_ORG = "vnd.android.cursor.item/organization"
M_NOTE = "vnd.android.cursor.item/note"
M_WEB = "vnd.android.cursor.item/website"
M_NICK = "vnd.android.cursor.item/nickname"
M_EVENT = "vnd.android.cursor.item/contact_event"

DATA_COLS = ["contact_id", "raw_contact_id", "mimetype", "is_primary",
             "data2", "data3", "data4", "data5", "data6", "data7", "data8", "data9", "data10", "data1"]
RAW_COLS = ["_id", "contact_id", "deleted", "account_type", "account_name"]
CONTACT_COLS = ["_id", "starred", "display_name"]

PHONE_TYPES = {"1": "HOME,VOICE", "2": "CELL", "3": "WORK,VOICE", "4": "WORK,FAX", "5": "HOME,FAX",
               "6": "PAGER", "7": "VOICE", "9": "CAR", "10": "WORK", "12": "VOICE", "17": "WORK,CELL"}
EMAIL_TYPES = {"1": "HOME", "2": "WORK", "3": "INTERNET", "4": "CELL"}
ADDR_TYPES = {"1": "HOME", "2": "WORK", "3": "POSTAL"}


def vc_escape(v: str | None) -> str:
    v = v or ""
    return v.replace("\\", "\\\\").replace("\r\n", "\n").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def vc_fold(line: str) -> str:
    """Zawijanie linii do 75 oktetów (RFC 2425/6350) bez rozcinania znaków UTF-8."""
    if len(line.encode("utf-8")) <= 75:
        return line
    out, cur, cur_len, limit = [], "", 0, 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if cur_len + n > limit:
            out.append(cur)
            cur, cur_len, limit = " ", 1, 75
        cur += ch
        cur_len += n
    out.append(cur)
    return "\r\n".join(out)


def build_vcards(contacts: list[dict], raws: list[dict], data: list[dict]) -> tuple[str, int, dict[str, str]]:
    """Zwraca (tekst .vcf, liczba kart, mapa phone_key -> nazwa do wiadomości/połączeń)."""
    deleted_raw = {r["_id"] for r in raws if r.get("deleted") == "1"}
    by_contact: OrderedDict[str, dict] = OrderedDict()
    for c in contacts:
        by_contact[c["_id"]] = {"display": c.get("display_name"), "starred": c.get("starred") == "1", "rows": []}
    for d in data:
        if d["raw_contact_id"] in deleted_raw:
            continue
        cid = d["contact_id"]
        if cid not in by_contact:
            by_contact[cid] = {"display": None, "starred": False, "rows": []}
        by_contact[cid]["rows"].append(d)

    cards, phone_names = [], {}
    for cid, c in by_contact.items():
        lines = _vcard_lines(c)
        if lines is None:
            continue
        name, phones, card = lines
        cards.append(card)
        for p in phones:
            k = phone_key(p)
            if k and k not in phone_names and name:
                phone_names[k] = name
    return "".join(cards), len(cards), phone_names


def _vcard_lines(c: dict) -> tuple[str, list[str], str] | None:
    rows = c["rows"]
    name_row = next((r for r in rows if r["mimetype"] == M_NAME), None)
    phones, emails, out = [], [], []
    seen_ph, seen_em = set(), set()

    for r in rows:
        mt, v = r["mimetype"], (r.get("data1") or "").strip()
        if mt == M_PHONE and v:
            key = re.sub(r"[^\d+]", "", v)
            if key in seen_ph:
                continue
            seen_ph.add(key)
            phones.append(v)
            t = PHONE_TYPES.get(r.get("data2") or "", "VOICE")
            if r.get("is_primary") == "1":
                t += ",PREF"
            out.append(f"TEL;TYPE={t}:{vc_escape(v)}")
        elif mt == M_EMAIL and v:
            if v.lower() in seen_em:
                continue
            seen_em.add(v.lower())
            emails.append(v)
            t = EMAIL_TYPES.get(r.get("data2") or "", "INTERNET")
            out.append(f"EMAIL;TYPE={t}:{vc_escape(v)}")
        elif mt == M_ADDR and (v or r.get("data4") or r.get("data7")):
            comps = [r.get("data5"), None, r.get("data4") or (v if not r.get("data7") else None),
                     r.get("data7"), r.get("data8"), r.get("data9"), r.get("data10")]
            t = ADDR_TYPES.get(r.get("data2") or "", "HOME")
            out.append(f"ADR;TYPE={t}:" + ";".join(vc_escape(x) for x in comps))
        elif mt == M_ORG and (v or r.get("data4")):
            if v:
                out.append(f"ORG:{vc_escape(v)}")
            if r.get("data4"):
                out.append(f"TITLE:{vc_escape(r['data4'])}")
        elif mt == M_NOTE and v:
            out.append(f"NOTE:{vc_escape(v)}")
        elif mt == M_WEB and v:
            out.append(f"URL:{vc_escape(v)}")
        elif mt == M_NICK and v:
            out.append(f"NICKNAME:{vc_escape(v)}")
        elif mt == M_EVENT and v and r.get("data2") == "3":
            out.append(f"BDAY:{vc_escape(v)}")

    display = (name_row.get("data1") if name_row else None) or c.get("display")
    if not display:
        display = phones[0] if phones else (emails[0] if emails else None)
    if not display and not out:
        return None
    if name_row:
        n = [name_row.get("data3"), name_row.get("data2"), name_row.get("data5"),
             name_row.get("data4"), name_row.get("data6")]
    else:
        n = [None, display, None, None, None]
    head = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{vc_escape(display)}", "N:" + ";".join(vc_escape(x) for x in n)]
    if c.get("starred"):
        head.append("X-ANDROID-STARRED:1")
    card = "".join(vc_fold(line) + "\r\n" for line in head + out + ["END:VCARD"])
    return display, phones, card


# --------------------------------------------------------------------------------------
# SMS / połączenia -> XML (format SMS Backup & Restore)
# --------------------------------------------------------------------------------------
SMS_COLS = [
    ["_id", "thread_id", "address", "date", "date_sent", "type", "read", "status", "locked",
     "sub_id", "protocol", "service_center", "subject", "body"],
    ["_id", "address", "date", "type", "read", "status", "body"],
]
CALL_COLS = [
    ["_id", "number", "date", "duration", "type", "presentation", "subscription_id", "name"],
    ["_id", "number", "date", "duration", "type", "name"],
]


def build_sms_xml(rows: list[dict], names: dict[str, str]) -> str:
    now = str(int(time.time() * 1000))
    out = ["<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
           "<!-- Generated by AdMeNot; SMS Backup & Restore (SyncTech) compatible format -->",
           f'<smses count="{len(rows)}" backup_set="{uuid.uuid4()}" backup_date="{now}" type="full">']
    for r in rows:
        g = r.get
        name = names.get(phone_key(g("address")), "(Unknown)")
        attrs = [("protocol", g("protocol") or "0"), ("address", g("address")), ("date", g("date")),
                 ("type", g("type")), ("subject", g("subject")), ("body", g("body")), ("toa", None),
                 ("sc_toa", None), ("service_center", g("service_center")), ("read", g("read") or "1"),
                 ("status", g("status") or "-1"), ("locked", g("locked") or "0"),
                 ("date_sent", g("date_sent") or "0"), ("sub_id", g("sub_id") or "-1"),
                 ("readable_date", readable(g("date"))), ("contact_name", name)]
        out.append("  <sms " + " ".join(f'{k}="{xml_attr(v)}"' for k, v in attrs) + " />")
    out.append("</smses>")
    return "\n".join(out) + "\n"


def build_calls_xml(rows: list[dict], names: dict[str, str]) -> str:
    now = str(int(time.time() * 1000))
    out = ["<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
           "<!-- Generated by AdMeNot; SMS Backup & Restore (SyncTech) compatible format -->",
           f'<calls count="{len(rows)}" backup_set="{uuid.uuid4()}" backup_date="{now}" type="full">']
    for r in rows:
        g = r.get
        name = g("name") or names.get(phone_key(g("number")), "(Unknown)")
        attrs = [("number", g("number") or ""), ("duration", g("duration") or "0"), ("date", g("date")),
                 ("type", g("type")), ("presentation", g("presentation") or "1"),
                 ("subscription_id", g("subscription_id")), ("readable_date", readable(g("date"))),
                 ("contact_name", name)]
        out.append("  <call " + " ".join(f'{k}="{xml_attr(v)}"' for k, v in attrs) + " />")
    out.append("</calls>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------------------
# Orkiestracja
# --------------------------------------------------------------------------------------
def export_telephony(adb: AdbTransport, out_dir: Path, *, contacts: bool, sms: bool, calls: bool,
                     mms: bool, shell_v2: bool, should_stop: Callable[[], bool]
                     ) -> dict[str, CategoryResult]:
    """Eksportuje wybrane kategorie do `out_dir`. Błąd jednej nie przerywa pozostałych.

    Wyjątki, które przechodzą wyżej: `Stopped` (przerwanie) i `AdbError` utraty połączenia
    (telefon odpiął się — kopia ma poczekać i wznowić, a nie zapisać „błąd kategorii”).
    """
    res: dict[str, CategoryResult] = {}
    raw_dir = out_dir / "raw"

    def sink(name: str) -> Callable[[str], None]:
        return lambda txt: atomic_write(raw_dir / name, txt)

    def check() -> None:
        if should_stop():
            raise Stopped()

    names: dict[str, str] = {}
    # Kontakty potrzebne też do nazw w SMS/połączeniach/MMS – czytamy je, gdy wybrano cokolwiek.
    if contacts or sms or calls or mms:
        check()
        try:
            rows_c = content_query(adb, "content://com.android.contacts/contacts", CONTACT_COLS,
                                   raw_sink=sink("contacts.txt") if contacts else None)
            rows_r = content_query(adb, "content://com.android.contacts/raw_contacts", RAW_COLS,
                                   raw_sink=sink("raw_contacts.txt") if contacts else None)
            rows_d = content_query(adb, "content://com.android.contacts/data", DATA_COLS,
                                   raw_sink=sink("contacts_data.txt") if contacts else None)
            vcf, n, names = build_vcards(rows_c, rows_r, rows_d)
            if contacts:
                atomic_write(out_dir / "contacts.vcf", vcf)
                res["contacts"] = CategoryResult("ok", n)
        except ContentQueryError as exc:
            if contacts:
                res["contacts"] = failure_result(exc)

    if sms:
        check()
        try:
            _, rows = query_with_fallback(adb, "content://sms", SMS_COLS, sort="date ASC",
                                          raw_sink=sink("sms.txt"))
            atomic_write(out_dir / "sms.xml", build_sms_xml(rows, names))
            res["sms"] = CategoryResult("ok", len(rows))
        except ContentQueryError as exc:
            res["sms"] = failure_result(exc)

    if mms:
        check()
        from .mms import export_mms  # import lokalny – mms.py importuje z tego modułu
        try:
            res["mms"] = export_mms(adb, out_dir, names, should_stop, shell_v2=shell_v2)
        except ContentQueryError as exc:
            res["mms"] = failure_result(exc)

    if calls:
        check()
        try:
            _, rows = query_with_fallback(adb, "content://call_log/calls", CALL_COLS,
                                          sort="date ASC", raw_sink=sink("calls.txt"))
            atomic_write(out_dir / "calls.xml", build_calls_xml(rows, names))
            res["calls"] = CategoryResult("ok", len(rows))
        except ContentQueryError as exc:
            res["calls"] = failure_result(exc)
    return res
