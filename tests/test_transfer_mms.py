from __future__ import annotations

import base64
import xml.etree.ElementTree as ET

import pytest
from faketransfer import FakeStoragePhone, write_provider
from telephony_fixtures import IMG1, IMG2, MMS, PARTS, install_telephony

from admenot.engine.adb.transport import AdbError
from admenot.engine.transfer import mms as mms_mod
from admenot.engine.transfer.guard import ReadOnlyAdb
from admenot.engine.transfer.mms import attachment_name, export_mms, message_address, mms_stats
from admenot.engine.transfer.telephony import CategoryResult, Stopped, export_telephony

NAMES = {"600100200": "Jan Kowalski"}


@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch):
    monkeypatch.setattr(mms_mod, "RETRY_PAUSE", 0.0)


def _phone(tmp_path):
    phone = FakeStoragePhone(tmp_path / "phone")
    install_telephony(tmp_path / "phone")
    return phone


def _reads(phone):
    return [c.rsplit("/", 1)[1] for c in phone.commands if c.startswith("content read")]


def _export(phone, out, **kw):
    kw.setdefault("should_stop", lambda: False)
    kw.setdefault("workers", 4)
    return export_mms(ReadOnlyAdb(phone), out, NAMES, **kw)


def test_address():
    a = [{"type": "137", "address": "insert-address-token"}, {"type": "151", "address": "+481"},
         {"type": "151", "address": "+482"}, {"type": "130", "address": "+481"}]
    assert message_address("2", a) == "+481~+482"
    assert message_address("1", [{"type": "137", "address": "+48600"},
                                 {"type": "151", "address": "insert-address-token"}]) == "+48600"


def test_attachment_name():
    m = {"_id": "5", "date": "1700000200"}
    assert attachment_name(m, {"_id": "9", "ct": "image/jpeg", "name": "a:b.jpg"}).endswith("_5_9_a_b.jpg")
    assert attachment_name(m, {"_id": "9", "ct": "image/png", "cl": "<obraz>"}).endswith("_5_9_obraz.png")
    assert attachment_name(m, {"_id": "9", "ct": "application/x-weird"}).endswith(".bin")


def test_export_format(tmp_path):
    phone = _phone(tmp_path)
    out = tmp_path / "out"
    res = _export(phone, out)
    assert res == CategoryResult("ok", 3)
    root = ET.parse(out / "mms.xml").getroot()
    assert root.get("count") == "3"
    m1, m2, m3 = root.findall("mms")
    assert m1.get("date") == "1700000200000"  # sekundy -> ms
    assert m1.get("address") == "+48600100200"
    assert m1.get("contact_name") == "Jan Kowalski"
    parts1 = m1.find("parts").findall("part")
    assert [p.get("ct") for p in parts1] == ["application/smil", "image/jpeg", "text/plain"]
    assert base64.b64decode(parts1[1].get("data")) == IMG1
    assert parts1[2].get("text") == "Zdjęcie z wakacji, ok?\nRow: 9 x, text=y"
    assert parts1[2].get("data") is None
    assert m2.get("address") == "+48600100200~+48999888777"
    assert m2.get("msg_box") == "2"
    assert len(m2.find("addrs").findall("addr")) == 3
    assert base64.b64decode(m2.find("parts").findall("part")[1].get("data")) == IMG2
    assert m3.get("sub") == "Temat, ważny"
    assert m3.get("contact_name") == "Jan Kowalski"
    att = sorted(p.name for p in (out / "mms_parts").iterdir())
    assert len(att) == 2
    assert att[0].endswith("_501_602_IMG_0001.jpg") and att[1].endswith("_502_605_obraz.png")
    assert (out / "mms_parts" / att[0]).read_bytes() == IMG1
    assert sorted(_reads(phone)) == ["602", "605"]  # sierota 607 pominięta
    assert not list(out.rglob("*.tmp"))


def test_resume_does_not_refetch(tmp_path):
    phone = _phone(tmp_path)
    out = tmp_path / "out"
    _export(phone, out)
    n = len(_reads(phone))
    assert _export(phone, out) == CategoryResult("ok", 3)
    assert len(_reads(phone)) == n
    assert sum("/addr" in c for c in phone.commands) == 3  # adresy też z pamięci podręcznej


def test_part_failure_then_retry(tmp_path):
    phone = _phone(tmp_path)
    out = tmp_path / "out"
    (tmp_path / "phone" / "mms_parts" / "605").unlink()
    res = _export(phone, out)
    assert res == CategoryResult("failed", 3, "attachments_missing:1")
    root = ET.parse(out / "mms.xml").getroot()
    assert root.findall("mms")[1].find("parts").findall("part")[1].get("data") is None
    before = _reads(phone)
    assert before.count("605") == 3  # 3 próby
    (tmp_path / "phone" / "mms_parts" / "605").write_bytes(IMG2)
    assert _export(phone, out) == CategoryResult("ok", 3)
    assert _reads(phone)[len(before):] == ["605"]


def test_exec_out_used_without_shell_v2(tmp_path):
    phone = _phone(tmp_path)
    used: list[list[str]] = []
    real = phone.run_bytes

    def spy(args, timeout=20.0):
        used.append(args)
        return real(args, timeout=timeout)

    phone.run_bytes = spy
    assert _export(phone, tmp_path / "out", shell_v2=False).status == "ok"
    assert used and all(a[0] == "exec-out" for a in used)
    used.clear()
    _export(phone, tmp_path / "out2", shell_v2=True)
    assert used and all(a[:2] == ["shell", "-T"] for a in used)


def test_cancel_then_resume(tmp_path):
    phone = _phone(tmp_path)
    out = tmp_path / "out"
    with pytest.raises(Stopped):
        _export(phone, out, workers=1, should_stop=lambda: bool(_reads(phone)))
    assert not (out / "mms.xml").exists()
    assert len(_reads(phone)) == 1
    assert len(list((out / "mms_parts").iterdir())) == 1
    assert _export(phone, out) == CategoryResult("ok", 3)
    assert len(_reads(phone)) == 2  # tylko brakujący załącznik


def test_disconnect_during_attachments_is_not_a_category_error(tmp_path):
    phone = _phone(tmp_path)
    real = phone.run_bytes

    def drop(args, timeout=20.0):
        phone.online = False
        return real(args, timeout=timeout)

    phone.run_bytes = drop
    with pytest.raises(AdbError) as err:
        _export(phone, tmp_path / "out", workers=1)
    assert err.value.kind == "offline"
    assert not (tmp_path / "out" / "mms.xml").exists()


def test_column_fallback(tmp_path):
    phone = _phone(tmp_path)
    root = tmp_path / "phone"
    write_provider(root, "content://mms", MMS, mms_mod.MMS_COLS_MIN)
    write_provider(root, "content://mms/part", PARTS, mms_mod.PART_COLS_MIN)
    res = _export(phone, tmp_path / "out")
    assert res == CategoryResult("ok", 3)
    assert len(ET.parse(tmp_path / "out" / "mms.xml").getroot().findall("mms")) == 3


def test_permission_denied_does_not_break_sms(tmp_path):
    phone = _phone(tmp_path)
    phone.deny_uris = {"content://mms"}
    res = export_telephony(ReadOnlyAdb(phone), tmp_path / "out", contacts=False, sms=True, calls=False,
                           mms=True, shell_v2=True, should_stop=lambda: False)
    assert res["sms"].status == "ok"
    assert res["mms"] == CategoryResult("unavailable", 0, "permission_denied")


def test_no_mms(tmp_path):
    phone = _phone(tmp_path)
    write_provider(tmp_path / "phone", "content://mms", [], mms_mod.MMS_COLS)
    assert _export(phone, tmp_path / "out") == CategoryResult("ok", 0)
    assert not (tmp_path / "out" / "mms.xml").exists()


def test_mms_stats(tmp_path):
    phone = _phone(tmp_path)
    # kolumny _id:m_size — telefon zwraca tylko żądaną projekcję
    write_provider(tmp_path / "phone", "content://mms", MMS, ["_id", "m_size"])
    assert mms_stats(ReadOnlyAdb(phone)) == (3, len(IMG1) + len(IMG2))


def test_export_through_orchestrator_lists_mms_key(tmp_path):
    phone = _phone(tmp_path)
    res = export_telephony(ReadOnlyAdb(phone), tmp_path / "out", contacts=True, sms=True, calls=True,
                           mms=True, shell_v2=True, should_stop=lambda: False)
    assert set(res) == {"contacts", "sms", "calls", "mms"}
    assert res["mms"] == CategoryResult("ok", 3)
    assert (tmp_path / "out" / "raw" / "mms_addr.json").is_file()


def test_failed_address_query_is_reported_and_retried(tmp_path):
    phone = _phone(tmp_path)
    out = tmp_path / "out"
    addr = tmp_path / "phone" / "providers" / "content_mms_503_addr.txt"
    saved = addr.read_text("utf-8")
    addr.unlink()
    res = _export(phone, out)
    assert res == CategoryResult("failed", 3, "addresses_missing:1")
    assert "503" not in (out / "raw" / "mms_addr.json").read_text("utf-8")
    addr.write_text(saved, "utf-8", newline="")
    assert _export(phone, out) == CategoryResult("ok", 3)
    assert sum("mms/503/addr" in c for c in phone.commands) == 2
    assert sum("mms/501/addr" in c for c in phone.commands) == 1
