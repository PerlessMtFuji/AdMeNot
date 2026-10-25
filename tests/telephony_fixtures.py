"""Dane providerów starego telefonu (kontakty, SMS, połączenia, MMS) do testów eksportu."""

from __future__ import annotations

from pathlib import Path

from faketransfer import write_provider

from admenot.engine.transfer import mms as mms_mod
from admenot.engine.transfer import telephony as tel

CONTACTS_URI = "content://com.android.contacts/contacts"
RAW_URI = "content://com.android.contacts/raw_contacts"
DATA_URI = "content://com.android.contacts/data"

CONTACTS = [
    {"_id": "1", "starred": "1", "display_name": "Jan Kowalski"},
    {"_id": "2", "starred": "0", "display_name": "Firma, Sp. z o.o."},
]
RAW = [
    {"_id": "10", "contact_id": "1", "deleted": "0", "account_type": "com.google", "account_name": "a@b"},
    {"_id": "11", "contact_id": "1", "deleted": "0", "account_type": "com.whatsapp", "account_name": "WA"},
    {"_id": "20", "contact_id": "2", "deleted": "0", "account_type": None, "account_name": None},
    {"_id": "30", "contact_id": "3", "deleted": "1", "account_type": None, "account_name": None},
]


def _data(contact, raw, mimetype, data1, data2=None, is_primary="0", **extra):
    row = {c: None for c in tel.DATA_COLS}
    row.update(contact_id=contact, raw_contact_id=raw, mimetype=mimetype, is_primary=is_primary,
               data1=data1, data2=data2, **extra)
    return row


DATA = [
    _data("1", "10", tel.M_NAME, "Jan Kowalski", "Jan", data3="Kowalski"),
    _data("1", "10", tel.M_PHONE, "+48 600 100 200", "2", is_primary="1"),
    _data("1", "11", tel.M_PHONE, "+48600100200", "2"),
    _data("1", "10", tel.M_NOTE, "Notatka, z przecinkiem; i średnikiem\ndruga linia"),
    _data("2", "20", tel.M_EMAIL, "biuro@firma.pl", "2"),
    _data("3", "30", tel.M_PHONE, "+48111222333", "2"),
]

SMS = [
    {"_id": "1", "address": "+48600100200", "date": "1700000000000", "type": "1", "read": "1",
     "status": "-1", "body": "Cześć, co u Ciebie?\nRow: 5 fałszywy wiersz, body=x & <tag> \"cudzysłów\""},
    {"_id": "2", "address": "+48999888777", "date": "1700000100000", "type": "2", "read": "1",
     "status": "-1", "body": "Emoji 👍 i znak sterujący \x07"},
]
CALLS = [
    {"_id": "1", "number": "600100200", "date": "1700000000000", "duration": "65", "type": "2",
     "presentation": "1", "subscription_id": "1", "name": None},
]

# MMS: zdjęcie z „trudnymi” bajtami, wiadomość grupowa, sam tekst, część osierocona
IMG1 = b"\xff\xd8\xff\xe0JFIF\r\n\x00\x01\r\r\n\n" + bytes(range(256)) * 40 + b"\xff\xd9"
IMG2 = b"\x89PNG\r\n\x1a\n" + bytes(range(255, -1, -1)) * 9


def _mms_row(mid, date_s, box, sub=None, m_size="0"):
    row = {c: None for c in mms_mod.MMS_COLS}
    row.update(_id=mid, thread_id="7", date=str(date_s), date_sent="0", msg_box=box, read="1", seen="1",
               locked="0", sub_id="1", text_only="0", m_type="132" if box == "1" else "128", m_size=m_size,
               v="18", pri="129", rr="129", ct_t="application/vnd.wap.multipart.related", sub=sub)
    return row


def _part(pid, mid, seq, ct, text=None, name=None, cl=None):
    row = {c: None for c in mms_mod.PART_COLS}
    row.update(_id=pid, mid=mid, seq=str(seq), ct=ct, chset="106" if text is not None else None, name=name,
               cl=cl, text=text)
    return row


MMS = [
    _mms_row("501", 1_700_000_200, "1", m_size=str(len(IMG1))),
    _mms_row("502", 1_700_000_300, "2", m_size=str(len(IMG2))),
    _mms_row("503", 1_700_000_400, "1", sub="Temat, ważny"),
]
PARTS = [
    _part("601", "501", -1, "application/smil", text="<smil><body><par/></body></smil>"),
    _part("602", "501", 0, "image/jpeg", name="IMG_0001.jpg"),
    _part("603", "501", 0, "text/plain", text="Zdjęcie z wakacji, ok?\nRow: 9 x, text=y"),
    _part("604", "502", 0, "text/plain", text="Do grupy"),
    _part("605", "502", 0, "image/png", cl="<obraz>"),
    _part("606", "503", 0, "text/plain", text="Sam tekst"),
    _part("607", "999", 0, "image/jpeg", name="sierota.jpg"),
]
ADDRS = {
    "501": [{"msg_id": "501", "type": "137", "charset": "106", "address": "+48600100200"},
            {"msg_id": "501", "type": "151", "charset": "106", "address": "insert-address-token"}],
    "502": [{"msg_id": "502", "type": "137", "charset": "106", "address": "insert-address-token"},
            {"msg_id": "502", "type": "151", "charset": "106", "address": "+48600100200"},
            {"msg_id": "502", "type": "151", "charset": "106", "address": "+48999888777"}],
    "503": [{"msg_id": "503", "type": "137", "charset": "106", "address": "600100200"}],
}
BLOBS = {"602": IMG1, "605": IMG2, "607": b"x"}


def install_telephony(root: Path, *, mms: bool = True) -> None:
    """Wypełnia `root/providers` i `root/mms_parts` danymi z tego modułu (SMS bez rozszerzonych kolumn)."""
    write_provider(root, CONTACTS_URI, CONTACTS, tel.CONTACT_COLS)
    write_provider(root, RAW_URI, RAW, tel.RAW_COLS)
    write_provider(root, DATA_URI, DATA, tel.DATA_COLS)
    write_provider(root, "content://sms", SMS, tel.SMS_COLS[1])  # brak sub_id itd. -> fallback projekcji
    write_provider(root, "content://call_log/calls", CALLS, tel.CALL_COLS[0])
    if not mms:
        return
    write_provider(root, mms_mod.MMS_URI, MMS, mms_mod.MMS_COLS)
    write_provider(root, mms_mod.PART_URI, PARTS, mms_mod.PART_COLS)
    for mid, addrs in ADDRS.items():
        write_provider(root, f"content://mms/{mid}/addr", addrs, mms_mod.ADDR_COLS)
    (root / "mms_parts").mkdir(exist_ok=True)
    for pid, blob in BLOBS.items():
        (root / "mms_parts" / pid).write_bytes(blob)
