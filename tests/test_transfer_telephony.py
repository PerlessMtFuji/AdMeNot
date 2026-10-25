from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from faketransfer import FakeStoragePhone
from telephony_fixtures import CALLS, CONTACTS, DATA, RAW, SMS, install_telephony

from admenot.engine.adb.sessionlog import SessionLogAdb
from admenot.engine.transfer.guard import ReadOnlyAdb
from admenot.engine.transfer.telephony import (
    CALL_COLS,
    SMS_COLS,
    CategoryResult,
    ContentQueryError,
    Stopped,
    build_calls_xml,
    build_sms_xml,
    build_vcards,
    count_rows,
    export_telephony,
    parse_content_rows,
    vc_fold,
)


def _phone(tmp_path, **kw):
    phone = FakeStoragePhone(tmp_path / "phone")
    install_telephony(tmp_path / "phone", **kw)
    return phone


def _export(phone, out, **kw):
    opts = {"contacts": True, "sms": True, "calls": True, "mms": False, "shell_v2": True,
            "should_stop": lambda: False}
    opts.update(kw)
    return export_telephony(ReadOnlyAdb(phone), out, **opts)


def test_parser_multiline_and_commas():
    cols = ["_id", "address", "body"]
    txt = ("Row: 0 _id=1, address=+48 1, body=Ala, ma kota\nRow: 7 nie nowy wiersz\n"
           "Row: 1 _id=2, address=NULL, body=")
    rows = parse_content_rows(txt + "\n", cols)
    assert len(rows) == 2
    assert rows[0]["body"] == "Ala, ma kota\nRow: 7 nie nowy wiersz"
    assert rows[1]["address"] is None
    assert rows[1]["body"] == ""
    assert parse_content_rows("No result found.\n", cols) == []


def test_parser_rejects_garbage_and_flags_denial():
    with pytest.raises(ContentQueryError) as err:
        parse_content_rows("coś innego\n", ["_id"])
    assert not err.value.denied
    with pytest.raises(ContentQueryError) as err:
        parse_content_rows("java.lang.SecurityException: Permission Denial\n", ["_id"])
    assert err.value.denied


def test_vcard_fold():
    line = "NOTE:" + "ż" * 100
    folded = vc_fold(line)
    for part in folded.split("\r\n"):
        assert len(part.encode()) <= 75
    assert folded.replace("\r\n ", "") == line


def test_vcards_and_xml():
    vcf, n, names = build_vcards(CONTACTS, RAW, DATA)
    assert n == 2  # kontakt 3 ma tylko usunięty raw_contact
    assert vcf.count("TEL;") == 1  # duplikat z WhatsApp scalony
    assert "NOTE:Notatka\\, z przecinkiem\\; i średnikiem\\ndruga linia" in vcf.replace("\r\n ", "")
    assert "FN:Firma\\, Sp. z o.o." in vcf
    assert "X-ANDROID-STARRED:1" in vcf
    assert names["600100200"] == "Jan Kowalski"
    xml = build_sms_xml([{k: r.get(k) for k in SMS_COLS[1]} for r in SMS], names)
    sms = ET.fromstring(xml.split("\n", 1)[1].encode()).findall("sms")
    assert len(sms) == 2
    assert sms[0].get("contact_name") == "Jan Kowalski"
    assert sms[1].get("contact_name") == "(Unknown)"
    assert sms[0].get("body").startswith("Cześć, co u Ciebie?\nRow: 5")
    assert "\x07" not in sms[1].get("body")
    cx = build_calls_xml([{k: r.get(k) for k in CALL_COLS[0]} for r in CALLS], names)
    call = ET.fromstring(cx.split("\n", 1)[1].encode()).find("call")
    assert call.get("contact_name") == "Jan Kowalski"
    assert call.get("duration") == "65"


def test_export_writes_all_files(tmp_path):
    phone = _phone(tmp_path)
    out = tmp_path / "out"
    res = _export(phone, out)
    assert res == {"contacts": CategoryResult("ok", 2), "sms": CategoryResult("ok", 2),
                   "calls": CategoryResult("ok", 1)}
    vcf = (out / "contacts.vcf").read_bytes().decode("utf-8")
    assert vcf.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\n") and "Kowalski" in vcf
    sms = ET.parse(out / "sms.xml").getroot()
    assert sms.get("count") == "2"
    assert sms.findall("sms")[0].get("contact_name") == "Jan Kowalski"
    assert sms.findall("sms")[0].get("date") == "1700000000000"
    assert ET.parse(out / "calls.xml").getroot().find("call").get("contact_name") == "Jan Kowalski"
    assert (out / "raw" / "sms.txt").is_file() and (out / "raw" / "contacts_data.txt").is_file()
    assert not list(out.rglob("*.tmp"))  # zapisy atomowe nie zostawiają plików tymczasowych
    assert all("content query" in c for c in phone.commands)


def test_only_selected_categories_are_exported(tmp_path):
    phone = _phone(tmp_path)
    out = tmp_path / "out"
    res = _export(phone, out, contacts=False, calls=False)
    assert list(res) == ["sms"]
    assert (out / "sms.xml").is_file() and not (out / "contacts.vcf").exists()
    # kontakty czytane dla nazw, ale ich surowa kopia nie powstaje
    assert ET.parse(out / "sms.xml").getroot().find("sms").get("contact_name") == "Jan Kowalski"
    assert not (out / "raw" / "contacts.txt").exists()


def test_sms_permission_denied_marks_unavailable(tmp_path):
    phone = _phone(tmp_path)
    phone.deny_uris = {"content://sms"}
    out = tmp_path / "out"
    res = _export(phone, out)
    assert res["sms"].status == "unavailable"
    assert res["sms"].error == "permission_denied"
    assert res["contacts"].status == "ok" and (out / "contacts.vcf").is_file()
    assert res["calls"].status == "ok"
    assert not (out / "sms.xml").exists()


def test_sms_body_containing_exception_is_data_not_error(tmp_path):
    from faketransfer import write_provider
    phone = _phone(tmp_path)
    rows = [{**SMS[0], "body": "java.lang.NullPointerException w treści SMS"}]
    write_provider(tmp_path / "phone", "content://sms", rows, SMS_COLS[1])
    res = _export(phone, tmp_path / "out", contacts=False, calls=False)
    assert res["sms"] == CategoryResult("ok", 1)


def test_missing_provider_is_failed_not_unavailable(tmp_path):
    phone = _phone(tmp_path)
    (tmp_path / "phone" / "providers" / "content_call_log_calls.txt").unlink()
    res = _export(phone, tmp_path / "out")
    assert res["calls"] == CategoryResult("failed", 0, "query_failed")  # klucz, nie tekst
    assert res["sms"].status == "ok"


def test_failure_result_is_a_key_and_detail_goes_to_local_log_only(caplog):
    from admenot.engine.transfer.telephony import ContentQueryError, failure_result
    exc = ContentQueryError("Error while accessing provider '/sdcard/Kontakty Jana.vcf'\nRow: 0 body=tajne")
    with caplog.at_level("WARNING"):
        res = failure_result(exc)
    assert res == CategoryResult("failed", 0, "query_failed")
    assert "Error while accessing provider" in caplog.text
    assert "Jana" not in caplog.text and "tajne" not in caplog.text


def test_sms_projection_falls_back_to_fewer_columns(tmp_path):
    phone = _phone(tmp_path)  # sms zapisane tylko z SMS_COLS[1]
    export = _export(phone, tmp_path / "out", contacts=False, calls=False)
    assert export["sms"] == CategoryResult("ok", 2)
    sms_cmds = [c for c in phone.commands if "content://sms" in c]
    assert len(sms_cmds) == 2 and "thread_id" in sms_cmds[0] and "thread_id" not in sms_cmds[1]


def test_count_rows_raises_on_denial(tmp_path):
    phone = _phone(tmp_path)
    adb = ReadOnlyAdb(phone)
    assert count_rows(adb, "content://sms") == 2
    phone.deny_uris = {"content://sms"}
    with pytest.raises(ContentQueryError) as err:
        count_rows(adb, "content://sms")
    assert err.value.denied


def test_stop_request_raises_stopped(tmp_path):
    phone = _phone(tmp_path)
    with pytest.raises(Stopped):
        _export(phone, tmp_path / "out", should_stop=lambda: True)
    assert phone.commands == []


def test_content_output_not_in_console(tmp_path):
    phone = _phone(tmp_path)
    seen: list[dict] = []
    logged = SessionLogAdb(phone, tmp_path / "s.log", on_command=seen.append)
    export_telephony(ReadOnlyAdb(logged), tmp_path / "out", contacts=True, sms=True, calls=True,
                     mms=False, shell_v2=True, should_stop=lambda: False)
    queries = [e for e in seen if e["command"].startswith("content query")]
    assert queries and all(e["output"] == "" for e in queries)
    assert "kowalski" not in (tmp_path / "s.log").read_text("utf-8").lower()


def test_content_read_and_host_forms_hidden_in_console(tmp_path):
    (tmp_path / "phone").mkdir()
    (tmp_path / "phone" / "mms_parts").mkdir()
    (tmp_path / "phone" / "mms_parts" / "7").write_bytes(b"sekret")
    seen: list[dict] = []
    logged = SessionLogAdb(FakeStoragePhone(tmp_path / "phone"), tmp_path / "s.log", on_command=seen.append)
    cmd = "content read --uri content://mms/part/7"
    logged.run(["shell", "-T", cmd])
    logged.run_bytes(["exec-out", cmd])
    logged.shell(cmd)
    assert [e["output"] for e in seen] == ["", "", ""]
    assert "sekret" not in "".join(e["output"] for e in seen)
