from __future__ import annotations

import base64
import io
from datetime import datetime
from pathlib import Path

from telephony_fixtures import CALLS, SMS

from admenot.engine.transfer import mms as mms_mod
from admenot.engine.transfer import telephony as tel
from admenot.engine.transfer.store import CopyDir, CopyMeta
from admenot.engine.transfer.telrecords import (
    TelSources,
    copy_sources,
    read_calls_xml,
    read_mms_xml,
    read_raw_contacts,
    read_sms_xml,
    read_vcards,
)


def _meta(selection: dict) -> CopyMeta:
    now = datetime(2026, 10, 31, 12, 0)
    return CopyMeta(id="x/y", serial="S", manufacturer="m", model="m", android="13", imei=None, client=None,
                    created=now, expires=now, status="complete", selection=selection)


def _dump(rows: list[dict], cols: list[str]) -> str:
    """Wyjście `content query`: kolejne wiersze `Row: N col=val, ...`, NULL dla None."""
    return "\n".join(
        f"Row: {i} " + ", ".join(f"{c}={'NULL' if r.get(c) is None else r[c]}" for c in cols)
        for i, r in enumerate(rows)) + "\n"


def test_sms_xml_roundtrip_from_build_sms_xml(tmp_path):
    rows = [
        {"address": "+48600100200", "date": "1700000000000", "date_sent": "1699999999000", "type": "1",
         "read": "1", "status": "-1", "subject": "Temat", "body": "Zażółć gęślą jaźń 👍"},
        {"address": "+48999888777", "date": "1700000100000", "type": "2", "read": "0", "status": "32",
         "body": "a & b < c > d \"e\"\nwiele\nlinii"},
        {"address": "123", "date": "1700000200000", "type": "1", "body": "😀 ok"},
    ]
    path = tmp_path / "sms.xml"
    path.write_text(tel.build_sms_xml(rows, {}), encoding="utf-8")
    out = read_sms_xml(path)
    assert len(out) == 3
    assert out[0].address == "+48600100200" and out[0].date == 1700000000000
    assert out[0].date_sent == 1699999999000 and out[0].subject == "Temat"
    assert out[0].body == "Zażółć gęślą jaźń 👍"
    assert out[1].body == rows[1]["body"] and out[1].type == 2 and out[1].read == 0
    assert out[1].status == 32 and out[1].subject is None
    assert out[2].body == "😀 ok" and out[2].date_sent == 0


def test_sms_xml_surrogate_refs(tmp_path):
    path = tmp_path / "sms.xml"
    path.write_bytes(
        b"<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n<smses count=\"2\">\n"
        b'  <sms address="1" date="5" type="1" body="a &#55357;&#56832; b &amp; c" />\n'
        b'  <sms address="2" date="6" type="1" body="&#xD83D;&#xDE00;&#55357;x" />\n</smses>\n')
    out = read_sms_xml(path)
    assert out[0].body == "a 😀 b & c"
    assert out[1].body == "😀�x"


def test_sms_xml_surrogate_refs_across_chunk_boundaries(tmp_path, monkeypatch):
    from admenot.engine.transfer import telrecords

    monkeypatch.setattr(telrecords, "_CHUNK", 7)
    path = tmp_path / "sms.xml"
    path.write_bytes(b'<smses><sms address="1" date="5" type="1" body="x&#55357;&#56832;y&#55357;&#56832;" />'
                     b"</smses>")
    assert read_sms_xml(path)[0].body == "x😀y😀"


def test_calls_xml_roundtrip(tmp_path):
    path = tmp_path / "calls.xml"
    path.write_text(tel.build_calls_xml(CALLS + [{"number": "+48111", "date": "1700000500000",
                                                  "duration": "0", "type": "3", "name": "Zażółć"}], {}),
                    encoding="utf-8")
    out = read_calls_xml(path)
    assert (out[0].number, out[0].date, out[0].duration, out[0].type, out[0].presentation) == (
        "600100200", 1700000000000, 65, 2, 1)
    assert out[0].name is None
    assert out[1].name == "Zażółć" and out[1].type == 3 and out[1].number == "+48111"


def _mms_xml(tmp_path: Path, files: dict[str, str]) -> Path:
    msgs = [{"_id": "501", "date": "1700000200", "date_sent": "0", "msg_box": "1", "read": "1", "sub": "Temat"}]
    parts = {"501": [
        {"_id": "601", "ct": "text/plain", "text": "Zdjęcie ok?", "seq": "0"},
        {"_id": "602", "ct": "image/jpeg", "name": "IMG_0001.jpg", "seq": "0"},
        {"_id": "603", "ct": "image/png", "cl": "<obraz>", "seq": "0"},
    ]}
    addrs = {"501": [{"address": "+48600100200", "type": "137", "charset": "106"},
                     {"address": "insert-address-token", "type": "151", "charset": "106"}]}
    out = io.StringIO()
    mms_mod._write_xml(out, msgs, parts, addrs, {}, str(tmp_path / "src_parts"), files)
    path = tmp_path / "mms.xml"
    path.write_text(out.getvalue(), encoding="utf-8")
    return path


def test_mms_xml_parts_from_dir_and_base64(tmp_path):
    src = tmp_path / "src_parts"
    src.mkdir()
    img1 = b"\xff\xd8\xff\xe0\r\n\x00\x01" + bytes(range(256))
    img2 = b"\x89PNG\r\n\x1a\n" + bytes(range(255, -1, -1))
    msg = {"_id": "501", "date": "1700000200"}
    n1 = mms_mod.attachment_name(msg, {"_id": "602", "name": "IMG_0001.jpg", "ct": "image/jpeg"})
    n2 = mms_mod.attachment_name(msg, {"_id": "603", "cl": "<obraz>", "ct": "image/png"})
    (src / n1).write_bytes(img1)
    (src / n2).write_bytes(img2)
    xml = _mms_xml(tmp_path, {"602": n1, "603": n2})
    parts_dir = tmp_path / "mms_parts"
    parts_dir.mkdir()
    (parts_dir / n1).write_bytes(img1)  # druga część tylko w base64

    out = read_mms_xml(xml, parts_dir)
    assert len(out) == 1
    m = out[0]
    assert m.date == 1700000200000 and m.msg_box == 1 and m.subject == "Temat"
    assert ("+48600100200", 137) in m.addrs and ("insert-address-token", 151) in m.addrs
    text, jpg, png = m.parts
    assert text.text == "Zdjęcie ok?" and text.file is None
    assert jpg.content_type == "image/jpeg" and jpg.file == parts_dir / n1
    assert jpg.file.read_bytes() == img1
    assert png.file is not None and png.file.parent == tmp_path / ".mms-parts"
    assert png.file.read_bytes() == img2
    assert base64.b64encode(img2).decode() in xml.read_text(encoding="utf-8")


def test_mms_xml_without_parts_dir_uses_base64_only(tmp_path):
    src = tmp_path / "src_parts"
    src.mkdir()
    name = mms_mod.attachment_name({"_id": "501", "date": "1700000200"},
                                   {"_id": "602", "name": "IMG_0001.jpg", "ct": "image/jpeg"})
    (src / name).write_bytes(b"abc\r\n")
    xml = _mms_xml(tmp_path, {"602": name})
    out = read_mms_xml(xml, None)
    assert out[0].parts[1].file.read_bytes() == b"abc\r\n"


MIUI_VCF = (
    "BEGIN:VCARD\r\nVERSION:2.1\r\n"
    "N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Kowalski;=C5=81ukasz;;;\r\n"
    "FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=C5=81ukasz=20Kowa=\r\nlski\r\n"
    "TEL;CELL:+48 600 100 200\r\n"
    "TEL;WORK;VOICE;PREF:22 123 45 67\r\n"
    "EMAIL;HOME:lukasz@example.com\r\n"
    "NOTE;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:Za=C5=BC=C3=B3=C5=82=C4=87=0Adruga linia\r\n"
    "X-ANDROID-STARRED:1\r\n"
    "END:VCARD\r\n"
)


def test_vcard21_qp_soft_breaks(tmp_path):
    path = tmp_path / "contacts.vcf"
    path.write_bytes(MIUI_VCF.encode("ascii"))
    (c,) = read_vcards(path)
    assert c.display == "Łukasz Kowalski" and c.accounts == ()
    phones = [dict(r.values) for r in c.rows if r.mimetype == tel.M_PHONE]
    assert [p["data1"] for p in phones] == ["+48 600 100 200", "22 123 45 67"]
    assert phones[0]["data2"] == "2" and phones[1]["data2"] == "3" and phones[1]["is_primary"] == "1"
    name = dict(next(r for r in c.rows if r.mimetype == tel.M_NAME).values)
    assert name["data1"] == "Łukasz Kowalski" and name["data2"] == "Łukasz" and name["data3"] == "Kowalski"
    note = dict(next(r for r in c.rows if r.mimetype == tel.M_NOTE).values)
    assert note["data1"] == "Zażółć\ndruga linia"
    assert c.starred


def test_vcard30_folded_and_escaped(tmp_path):
    contacts = [{"_id": "1", "starred": "1", "display_name": "Jan Kowalski"},
                {"_id": "2", "starred": "0", "display_name": "Firma, Sp. z o.o."}]
    raws = [{"_id": "10", "contact_id": "1", "deleted": "0"}, {"_id": "20", "contact_id": "2", "deleted": "0"}]
    long_note = "Notatka, z przecinkiem; i średnikiem\ndruga linia " + "ąęłń" * 40
    data = []
    for cid, raw, mt, d1, d2, extra in [
        ("1", "10", tel.M_NAME, "Jan Kowalski", "Jan", {"data3": "Kowalski"}),
        ("1", "10", tel.M_PHONE, "+48 600 100 200", "2", {"is_primary": "1"}),
        ("1", "10", tel.M_EMAIL, "jan@firma.pl", "2", {}),
        ("1", "10", tel.M_NOTE, long_note, None, {}),
        ("1", "10", tel.M_ADDR, "ul. Długa 1", "1", {"data4": "ul. Długa 1", "data7": "Łódź", "data9": "90-001"}),
        ("2", "20", tel.M_EMAIL, "biuro@firma.pl", "2", {}),
        ("2", "20", tel.M_PHONE, "+48111222333", "3", {}),
    ]:
        row = {c: None for c in tel.DATA_COLS}
        row.update(contact_id=cid, raw_contact_id=raw, mimetype=mt, is_primary="0", data1=d1, data2=d2)
        row.update(extra)
        data.append(row)
    text, n, _ = tel.build_vcards(contacts, raws, data)
    assert n == 2 and "\r\n " in text  # coś naprawdę zawinięte
    path = tmp_path / "c.vcf"
    path.write_text(text, encoding="utf-8", newline="")
    jan, firma = read_vcards(path)
    assert jan.display == "Jan Kowalski" and jan.starred and not firma.starred
    assert firma.display == "Firma, Sp. z o.o."
    jan_rows = {r.mimetype: dict(r.values) for r in jan.rows}
    assert jan_rows[tel.M_PHONE]["data1"] == "+48 600 100 200" and jan_rows[tel.M_PHONE]["is_primary"] == "1"
    assert jan_rows[tel.M_EMAIL]["data1"] == "jan@firma.pl"
    assert jan_rows[tel.M_NOTE]["data1"] == long_note
    assert jan_rows[tel.M_ADDR]["data4"] == "ul. Długa 1" and jan_rows[tel.M_ADDR]["data7"] == "Łódź"
    assert jan_rows[tel.M_ADDR]["data9"] == "90-001"
    assert jan_rows[tel.M_NAME]["data2"] == "Jan" and jan_rows[tel.M_NAME]["data3"] == "Kowalski"
    firma_rows = {r.mimetype: dict(r.values) for r in firma.rows}
    assert firma_rows[tel.M_EMAIL]["data1"] == "biuro@firma.pl"
    assert firma_rows[tel.M_PHONE]["data1"] == "+48111222333"


def test_raw_contacts_keep_accounts(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    contacts = [{"_id": "1", "starred": "1", "display_name": "Jan Kowalski"},
                {"_id": "3", "starred": "0", "display_name": "Usunięty"}]
    raws = [
        {"_id": "10", "contact_id": "1", "deleted": "0", "account_type": None, "account_name": None},
        {"_id": "11", "contact_id": "1", "deleted": "0", "account_type": "com.google", "account_name": "a@b"},
        {"_id": "30", "contact_id": "3", "deleted": "1", "account_type": None, "account_name": None},
    ]

    def d(contact, rawid, mt, data1, data2=None):
        row = {c: None for c in tel.DATA_COLS}
        row.update(contact_id=contact, raw_contact_id=rawid, mimetype=mt, is_primary="0", data1=data1,
                   data2=data2)
        return row

    data = [d("1", "10", tel.M_PHONE, "+48600100200", "2"), d("1", "11", tel.M_EMAIL, "a@b.pl", "1"),
            d("3", "30", tel.M_PHONE, "+48111222333", "2")]
    (raw / "contacts.txt").write_text(_dump(contacts, tel.CONTACT_COLS), encoding="utf-8")
    (raw / "raw_contacts.txt").write_text(_dump(raws, tel.RAW_COLS), encoding="utf-8")
    (raw / "contacts_data.txt").write_text(_dump(data, tel.DATA_COLS), encoding="utf-8")
    (c,) = read_raw_contacts(tmp_path)
    assert c.source_id == "1" and c.display == "Jan Kowalski" and c.starred
    assert set(c.accounts) == {("", ""), ("com.google", "a@b")} and len(c.accounts) == 2
    assert [r.mimetype for r in c.rows] == [tel.M_PHONE, tel.M_EMAIL]
    assert dict(c.rows[0].values) == {"data1": "+48600100200", "data2": "2", "is_primary": "0"}


def _touch_phone(copy: CopyDir, *names: str) -> None:
    copy.phone_dir.mkdir(parents=True, exist_ok=True)
    for n in names:
        p = copy.phone_dir / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")


RAW_FILES = ("raw/contacts.txt", "raw/raw_contacts.txt", "raw/contacts_data.txt")


def test_sources_from_phone_dumps(tmp_path):
    copy = CopyDir(tmp_path)
    _touch_phone(copy, "contacts.vcf", "sms.xml", "mms.xml", "calls.xml", *RAW_FILES)
    src = copy_sources(copy, _meta({"contacts": True, "sms": True, "mms": True, "calls": True, "exports": []}))
    assert src == TelSources("raw", copy.phone_dir / "sms.xml", copy.phone_dir / "mms.xml",
                             copy.phone_dir / "calls.xml")
    _touch_phone(CopyDir(tmp_path / "empty"))
    assert copy_sources(CopyDir(tmp_path / "empty"), _meta({})) == TelSources(None, None, None, None)


def test_sources_without_raw_dumps_use_vcf(tmp_path):
    copy = CopyDir(tmp_path)
    _touch_phone(copy, "contacts.vcf")
    assert copy_sources(copy, _meta({"contacts": True})).contacts == "vcf"


def test_sources_export_sms_drops_mms(tmp_path):
    copy = CopyDir(tmp_path)
    _touch_phone(copy, "sms.xml", "mms.xml", "calls.xml")
    exports = [{"kind": "sms", "remote": "/sdcard/sms.xml", "size": 1, "mtime": 1}]
    src = copy_sources(copy, _meta({"sms": True, "mms": True, "calls": True, "exports": exports}))
    assert src.sms == copy.phone_dir / "sms.xml" and src.mms is None
    assert src.calls == copy.phone_dir / "calls.xml"


def test_sources_export_contacts_uses_vcf(tmp_path):
    copy = CopyDir(tmp_path)
    _touch_phone(copy, "contacts.vcf", *RAW_FILES)
    exports = [{"kind": "contacts", "remote": "/sdcard/c.vcf", "size": 1, "mtime": 1}]
    assert copy_sources(copy, _meta({"contacts": True, "exports": exports})).contacts == "vcf"


def test_sms_fixture_rows_still_parse(tmp_path):
    path = tmp_path / "sms.xml"
    path.write_text(tel.build_sms_xml(SMS, {}), encoding="utf-8")
    assert [s.body for s in read_sms_xml(path)] == [tel._BAD_XML.sub("", r["body"]) for r in SMS]
