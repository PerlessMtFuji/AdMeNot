"""Odczyt kopii telefonii (kontakty, SMS, MMS, połączenia) do rekordów gotowych do zapisu na nowym telefonie.

Źródła to pliki z `phone/` w kopii: XML w formacie SMS Backup & Restore (SMS, MMS, połączenia),
zrzuty `content query` kontaktów w `phone/raw/` albo plik vCard 2.1/3.0 (eksport z telefonu lub
z aplikacji producenta). Rekordy nie niosą identyfikatorów ze starego telefonu poza `source_id`
kontaktu — nowy telefon nadaje własne.

Eksporty z emoji zawierają odwołania do znaków zastępczych (`&#55357;&#56832;`), których expat nie
przyjmuje — `_EntityJoiner` skleja je w jeden znak, zanim bajty trafią do parsera.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import quopri
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from . import telephony as tel
from .mms import _ms, attachment_name
from .store import CopyDir, CopyMeta
from .winpath import sanitize_component

_CHUNK = 1 << 16
_REF = re.compile(rb"&#(x[0-9A-Fa-f]+|[0-9]+);")
_REF_END = re.compile(rb"&#(?:x[0-9A-Fa-f]+|[0-9]+);\Z")
_WINDOW = 40  # dłuższe niż para odwołań (`&#x0D83D;&#x0DE00;`)
_REPLACEMENT = "�"


# --------------------------------------------------------------------------------------
# Rekordy
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class SmsRecord:
    address: str
    date: int  # ms
    date_sent: int
    type: int
    read: int
    status: int
    subject: str | None
    body: str


@dataclass(frozen=True)
class CallRecord:
    number: str
    date: int  # ms
    duration: int
    type: int
    presentation: int
    name: str | None


@dataclass(frozen=True)
class MmsPart:
    content_type: str
    name: str | None
    text: str | None
    file: Path | None


@dataclass(frozen=True)
class MmsRecord:
    date: int  # ms
    date_sent: int
    msg_box: int
    read: int
    subject: str | None
    addrs: tuple[tuple[str, int], ...]  # (adres, typ 137/151/130/129)
    parts: tuple[MmsPart, ...]


@dataclass(frozen=True)
class DataRow:
    mimetype: str
    values: tuple[tuple[str, str], ...]  # data1…data10, is_primary


@dataclass(frozen=True)
class ContactRecord:
    source_id: str
    display: str | None
    starred: bool
    accounts: tuple[tuple[str, str], ...]  # (account_type, account_name); () = brak informacji
    rows: tuple[DataRow, ...]


@dataclass(frozen=True)
class TelSources:
    contacts: Literal["raw", "vcf"] | None
    sms: Path | None
    mms: Path | None
    calls: Path | None


# --------------------------------------------------------------------------------------
# Odwołania do znaków zastępczych
# --------------------------------------------------------------------------------------
def _ref_value(token: bytes) -> int:
    return int(token[1:], 16) if token[:1] == b"x" else int(token)


def join_surrogate_refs(buf: bytes) -> bytes:
    """Para odwołań `&#hi;&#lo;` -> jedno odwołanie do znaku; pojedyncze znaki zastępcze -> U+FFFD.

    Reszta bufora (w tym zwykłe `&amp;`) pozostaje nietknięta."""
    out: list[bytes] = []
    pos = 0
    matches = list(_REF.finditer(buf))
    i = 0
    while i < len(matches):
        m = matches[i]
        try:
            v = _ref_value(m.group(1))
        except ValueError:
            i += 1
            continue
        if not 0xD800 <= v <= 0xDFFF:
            i += 1
            continue
        out.append(buf[pos:m.start()])
        nxt = matches[i + 1] if i + 1 < len(matches) else None
        if (v <= 0xDBFF and nxt is not None and nxt.start() == m.end()
                and 0xDC00 <= _ref_value(nxt.group(1)) <= 0xDFFF):
            cp = 0x10000 + ((v - 0xD800) << 10) + (_ref_value(nxt.group(1)) - 0xDC00)
            out.append(f"&#{cp};".encode("ascii"))
            pos = nxt.end()
            i += 2
        else:
            out.append(f"&#{ord(_REPLACEMENT)};".encode("ascii"))
            pos = m.end()
            i += 1
    out.append(buf[pos:])
    return b"".join(out)


class _EntityJoiner:
    """Plik tylko do odczytu, który strumieniowo skleja odwołania do znaków zastępczych."""

    def __init__(self, fh: BinaryIO) -> None:
        self._fh = fh
        self._carry = b""
        self._out = b""
        self._eof = False

    def _fill(self) -> None:
        chunk = self._fh.read(_CHUNK)
        buf = self._carry + chunk
        if not chunk:
            self._eof = True
            self._out += join_surrogate_refs(buf)
            self._carry = b""
            return
        cut = buf.find(b"&", max(0, len(buf) - _WINDOW))
        if cut == -1:
            cut = len(buf)
        else:  # nie rozcinamy ciągu przylegających odwołań (para może zaczynać się przed oknem)
            while (m := _REF_END.search(buf[:cut])) is not None:
                cut = m.start()
        self._out += join_surrogate_refs(buf[:cut])
        self._carry = buf[cut:]

    def read(self, n: int = -1) -> bytes:
        while not self._eof and (n < 0 or len(self._out) < n):
            self._fill()
        if n < 0:
            data, self._out = self._out, b""
        else:
            data, self._out = self._out[:n], self._out[n:]
        return data


def _elements(path: Path, tag: str) -> Iterator[ET.Element]:
    """Kolejne elementy `tag` z pliku XML; po przetworzeniu elementu wolno go zwolnić."""
    with path.open("rb") as fh:
        root: ET.Element | None = None
        for event, el in ET.iterparse(_EntityJoiner(fh), events=("start", "end")):  # type: ignore[arg-type]
            if event == "start":
                if root is None:
                    root = el
                continue
            if el.tag == tag:
                yield el
                el.clear()
                if root is not None:
                    root.clear()


def _attr(el: ET.Element, key: str) -> str | None:
    v = el.get(key)
    return None if v is None or v == "null" else v


def _int(v: str | None, default: int = 0) -> int:
    try:
        return int(v) if v not in (None, "") else default
    except ValueError:
        return default


# --------------------------------------------------------------------------------------
# SMS / połączenia / MMS
# --------------------------------------------------------------------------------------
def read_sms_xml(path: Path) -> list[SmsRecord]:
    return [SmsRecord(
        address=el.get("address") or "", date=_int(el.get("date")), date_sent=_int(el.get("date_sent")),
        type=_int(el.get("type"), 1), read=_int(el.get("read"), 1), status=_int(el.get("status"), -1),
        subject=_attr(el, "subject"), body=el.get("body") or "") for el in _elements(path, "sms")]


def read_calls_xml(path: Path) -> list[CallRecord]:
    out = []
    for el in _elements(path, "call"):
        name = _attr(el, "contact_name")
        out.append(CallRecord(
            number=el.get("number") or "", date=_int(el.get("date")), duration=_int(el.get("duration")),
            type=_int(el.get("type"), 1), presentation=_int(el.get("presentation"), 1),
            name=None if name in (None, "", "(Unknown)") else name))
    return out


_PART_FILE = re.compile(r"(\d{4}-\d\d-\d\d_\d{6})_(\d+)_(\d+)_(.+)\Z", re.DOTALL)
_STAMP_LEN = len("0000-00-00_000000")
_TAIL_AT = _STAMP_LEN + len("_0_0_")


def _index_parts_dir(parts_dir: Path | None) -> dict[tuple[str, str], list[tuple[int, int, Path]]]:
    """Pliki załączników z `mms_parts/` wg (znacznik czasu, reszta nazwy) — id wiadomości i części
    nie ma w XML-u, więc dopasowujemy po nazwie i rozmiarze."""
    index: dict[tuple[str, str], list[tuple[int, int, Path]]] = {}
    if parts_dir is None or not parts_dir.is_dir():
        return index
    for f in parts_dir.iterdir():
        if m := _PART_FILE.fullmatch(f.name):
            index.setdefault((m.group(1), m.group(4)), []).append((int(m.group(2)), int(m.group(3)), f))
    for lst in index.values():
        lst.sort()
    return index


def _b64_size(data: str) -> int:
    data = re.sub(r"\s", "", data)
    return len(data) * 3 // 4 - data.count("=", max(0, len(data) - 2))


def _decode_b64(data: str) -> bytes:
    try:
        return base64.b64decode(data)
    except (binascii.Error, ValueError):
        return base64.b64decode(re.sub(r"[^A-Za-z0-9+/]", "", data) + "===")


def read_mms_xml(path: Path, parts_dir: Path | None) -> list[MmsRecord]:
    index = _index_parts_dir(parts_dir)
    used: set[Path] = set()
    spill = path.parent / ".mms-parts"
    out: list[MmsRecord] = []
    for n, el in enumerate(_elements(path, "mms")):
        date = _ms(el.get("date"))
        parts: list[MmsPart] = []
        for k, pe in enumerate(el.iter("part")):
            ct = pe.get("ct") or "application/octet-stream"
            data = pe.get("data")
            file: Path | None = None
            if data:
                template = attachment_name(
                    {"_id": "0", "date": date},
                    {"_id": "0", "ct": ct, "fn": _attr(pe, "fn"), "name": _attr(pe, "name"),
                     "cl": _attr(pe, "cl")})
                size = _b64_size(data)
                for cand in index.get((template[:_STAMP_LEN], template[_TAIL_AT:]), []):
                    if cand[2] not in used and cand[2].stat().st_size == size:
                        file = cand[2]
                        used.add(file)
                        break
                if file is None:
                    spill.mkdir(exist_ok=True)
                    stem = sanitize_component(template[_TAIL_AT:])[:80]
                    file = spill / f"{n}_{k}_{stem}"
                    file.write_bytes(_decode_b64(data))
            parts.append(MmsPart(ct, _attr(pe, "name"), _attr(pe, "text"), file))
        addrs = tuple((a.get("address") or "", _int(a.get("type"))) for a in el.iter("addr"))
        out.append(MmsRecord(
            date=_int(date), date_sent=_int(_ms(el.get("date_sent"))), msg_box=_int(el.get("msg_box"), 1),
            read=_int(el.get("read"), 1), subject=_attr(el, "sub") or _attr(el, "subject"),
            addrs=addrs, parts=tuple(parts)))
    return out


# --------------------------------------------------------------------------------------
# vCard 2.1 / 3.0
# --------------------------------------------------------------------------------------
def _row(mimetype: str, **cols: str | None) -> DataRow:
    return DataRow(mimetype, tuple((k, v) for k, v in cols.items() if v is not None))


def _logical_lines(text: str) -> list[str]:
    """Linie po rozwinięciu: zawijanie 3.0/2.1 (spacja/tab) i miękkie łamania `=` w wartościach QP."""
    out: list[str] = []
    qp_open = False
    for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if qp_open:
            out[-1] = out[-1][:-1] + ln
        elif ln[:1] in (" ", "\t") and out:
            out[-1] += ln[1:]
        else:
            out.append(ln)
        head = out[-1].split(":", 1)[0].upper() if out else ""
        qp_open = out[-1].endswith("=") and "QUOTED-PRINTABLE" in head if out else False
    return out


def _split_escaped(value: str, sep: str) -> list[str]:
    parts, cur, i = [], [], 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            cur.append(value[i:i + 2])
            i += 2
            continue
        if ch == sep:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def _unescape(v: str) -> str:
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v, flags=re.DOTALL)


def _decode_text(raw: bytes, charset: str) -> str:
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _parse_line(line: str) -> tuple[str, set[str], list[str]] | None:
    """(nazwa pola, typy/parametry, składniki wartości) albo None dla linii bez pola."""
    if ":" not in line:
        return None
    head, value = line.split(":", 1)
    bits = head.split(";")
    name = bits[0].split(".")[-1].upper()
    flags: set[str] = set()
    charset, qp = "utf-8", False
    for b in bits[1:]:
        key, _, val = b.partition("=")
        key, val = key.strip().upper(), val.strip()
        if not val:  # parametr bez nazwy (vCard 2.1): CELL, QUOTED-PRINTABLE…
            if key == "QUOTED-PRINTABLE":
                qp = True
            else:
                flags.add(key)
        elif key == "ENCODING":
            qp = qp or val.upper() == "QUOTED-PRINTABLE"
        elif key == "CHARSET":
            charset = val
        elif key == "TYPE":
            flags.update(t.strip().strip('"').upper() for t in val.split(","))
    comps = _split_escaped(value, ";")
    if qp:
        comps = [_decode_text(quopri.decodestring(c.encode("ascii", "replace")), charset) for c in comps]
    else:
        comps = [_unescape(c) for c in comps]
    return name, flags, comps


def _phone_type(t: set[str]) -> str:
    if "FAX" in t:
        return "4" if "WORK" in t else "5" if "HOME" in t else "13"
    if "PAGER" in t:
        return "6"
    if "CAR" in t:
        return "9"
    if "CELL" in t:
        return "17" if "WORK" in t else "2"
    if "WORK" in t:
        return "3"
    if "HOME" in t:
        return "1"
    return "7"


def _email_type(t: set[str]) -> str:
    return "1" if "HOME" in t else "2" if "WORK" in t else "4" if "CELL" in t else "3"


def _addr_type(t: set[str]) -> str:
    return "2" if "WORK" in t else "3" if "POSTAL" in t else "1"


def _card_to_record(lines: list[str], index: int) -> ContactRecord | None:
    rows: list[DataRow] = []
    fn: str | None = None
    name_cols: dict[str, str | None] | None = None
    org: dict[str, str | None] = {}
    starred = False
    for line in lines:
        parsed = _parse_line(line)
        if parsed is None:
            continue
        name, flags, c = parsed
        first = c[0].strip() if c else ""
        pri = "1" if "PREF" in flags else "0"
        if name == "FN":
            fn = first or None
        elif name == "N":
            comp = [x.strip() for x in c] + [""] * 5
            name_cols = {"data3": comp[0] or None, "data2": comp[1] or None, "data5": comp[2] or None,
                         "data4": comp[3] or None, "data6": comp[4] or None}
        elif name == "TEL" and first:
            rows.append(_row(tel.M_PHONE, data1=first, data2=_phone_type(flags), is_primary=pri))
        elif name == "EMAIL" and first:
            rows.append(_row(tel.M_EMAIL, data1=first, data2=_email_type(flags), is_primary=pri))
        elif name == "ADR":
            comp = [x.strip() for x in c] + [""] * 7
            street = ", ".join(x for x in (comp[1], comp[2]) if x)
            formatted = ", ".join(x for x in (street, comp[3], comp[4], comp[5], comp[6]) if x)
            if formatted or comp[0]:
                rows.append(_row(tel.M_ADDR, data1=formatted or None, data2=_addr_type(flags),
                                 data4=street or None, data5=comp[0] or None, data7=comp[3] or None,
                                 data8=comp[4] or None, data9=comp[5] or None, data10=comp[6] or None))
        elif name == "ORG" and first:
            org["data1"] = first
            if len(c) > 1 and c[1].strip():
                org["data5"] = c[1].strip()
        elif name == "TITLE" and first:
            org["data4"] = first
        elif name == "NOTE" and c and "".join(c).strip():
            rows.append(_row(tel.M_NOTE, data1=";".join(c).strip()))
        elif name == "URL" and c and "".join(c).strip():
            rows.append(_row(tel.M_WEB, data1=":".join(";".join(c).split("\\:")).strip()))
        elif name == "NICKNAME" and first:
            rows.append(_row(tel.M_NICK, data1=first))
        elif name == "BDAY" and first:
            rows.append(_row(tel.M_EVENT, data1=first, data2="3"))
        elif name in ("X-ANDROID-STARRED", "X-STARRED"):
            starred = first.lower() in ("1", "true")
    display = fn
    if display is None and name_cols:
        order = ("data4", "data2", "data5", "data3", "data6")
        display = " ".join(name_cols[k] for k in order if name_cols.get(k)) or None
    if display or name_cols:
        rows.insert(0, _row(tel.M_NAME, data1=display, **(name_cols or {})))
    if org:
        rows.append(_row(tel.M_ORG, **org))
    if not rows:
        return None
    return ContactRecord(f"vcf:{index}", display, starred, (), tuple(rows))


def read_vcards(path: Path) -> list[ContactRecord]:
    text = codecs.decode(path.read_bytes(), "utf-8-sig", "replace")
    out: list[ContactRecord] = []
    card: list[str] | None = None
    for line in _logical_lines(text):
        tag = line.strip().upper()
        if tag == "BEGIN:VCARD":
            card = []
        elif tag == "END:VCARD":
            if card is not None and (rec := _card_to_record(card, len(out))) is not None:
                out.append(rec)
            card = None
        elif card is not None and line:
            card.append(line)
    return out


# --------------------------------------------------------------------------------------
# Kontakty ze zrzutów `content query`
# --------------------------------------------------------------------------------------
_RAW_FILES = ("contacts.txt", "raw_contacts.txt", "contacts_data.txt")
_KNOWN_MIMES = {tel.M_NAME, tel.M_PHONE, tel.M_EMAIL, tel.M_ADDR, tel.M_ORG, tel.M_NOTE, tel.M_WEB,
                tel.M_NICK, tel.M_EVENT}
_ROW_COLS = ["data1", "data2", "data3", "data4", "data5", "data6", "data7", "data8", "data9", "data10"]


def _read_dump(path: Path, cols: list[str]) -> list[dict[str, str | None]]:
    return tel.parse_content_rows(path.read_text(encoding="utf-8", errors="replace"), cols)


def read_raw_contacts(phone_dir: Path) -> list[ContactRecord]:
    raw = phone_dir / "raw"
    contacts = _read_dump(raw / "contacts.txt", tel.CONTACT_COLS)
    raws = _read_dump(raw / "raw_contacts.txt", tel.RAW_COLS)
    data = _read_dump(raw / "contacts_data.txt", tel.DATA_COLS)
    deleted = {r["_id"] for r in raws if r.get("deleted") == "1"}
    accounts: dict[str, list[tuple[str, str]]] = {}
    for r in raws:
        if r["_id"] in deleted or r.get("contact_id") is None:
            continue
        acc = (r.get("account_type") or "", r.get("account_name") or "")
        lst = accounts.setdefault(r["contact_id"], [])
        if acc not in lst:
            lst.append(acc)
    info: dict[str, tuple[str | None, bool]] = {
        c["_id"]: (c.get("display_name"), c.get("starred") == "1") for c in contacts if c.get("_id")}
    rows: dict[str, list[DataRow]] = {}
    for d in data:
        cid = d.get("contact_id")
        if cid is None or d.get("raw_contact_id") in deleted or d.get("mimetype") not in _KNOWN_MIMES:
            continue
        cols = {k: d.get(k) for k in _ROW_COLS}
        cols["is_primary"] = d.get("is_primary") or "0"
        rows.setdefault(cid, []).append(_row(d["mimetype"], **cols))  # type: ignore[arg-type]
    out = []
    for cid in list(info) + [c for c in rows if c not in info]:
        if cid not in rows:
            continue
        display, starred = info.get(cid, (None, False))
        out.append(ContactRecord(cid, display, starred, tuple(accounts.get(cid, [])), tuple(rows[cid])))
    return out


# --------------------------------------------------------------------------------------
# Źródła w kopii
# --------------------------------------------------------------------------------------
def copy_sources(copy: CopyDir, meta: CopyMeta) -> TelSources:
    """Pliki telefonii w kopii. Kategoria z pliku eksportu nie ma zrzutów `raw/`, a załączników MMS
    w eksporcie SMS nie ma (spec §5.1) — wtedy `mms = None`. `None` = kategorii nie ma w kopii."""
    phone = copy.phone_dir
    sel = meta.selection
    exported = {e.get("kind") for e in (sel.get("exports") or []) if isinstance(e, dict) and sel.get(e.get("kind"))}

    def exists(name: str) -> Path | None:
        p = phone / name
        return p if p.is_file() else None

    raw_ok = all((phone / "raw" / n).is_file() for n in _RAW_FILES)
    contacts: Literal["raw", "vcf"] | None
    if raw_ok and "contacts" not in exported:
        contacts = "raw"
    else:
        contacts = "vcf" if exists("contacts.vcf") else None
    return TelSources(contacts, exists("sms.xml"), None if "sms" in exported else exists("mms.xml"),
                      exists("calls.xml"))
