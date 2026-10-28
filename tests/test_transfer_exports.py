from __future__ import annotations

import os

import pytest
from faketransfer import FakeStoragePhone

from admenot.engine.adb.transport import AdbError
from admenot.engine.transfer.exports import (
    HEAD_BYTES,
    MAX_CANDIDATES,
    ExportFile,
    ExportFormatError,
    count_export,
    detect_export,
    find_exports,
)
from admenot.engine.transfer.guard import ReadOnlyAdb
from admenot.engine.transfer.inventory import RemoteFile

VCARD = (
    "BEGIN:VCARD\r\nVERSION:2.1\r\nN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=C5=81ucja\r\n"
    "END:VCARD\r\n"
)
VCF = b"\xef\xbb\xbf" + (VCARD * 2).encode()
SMS_HEAD = (
    "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n"
    "<!--File Created By SMS Backup & Restore-->\n"
    '<smses count="60" backup_set="x">'
)


def test_detect_vcf_variants():
    assert detect_export(VCF, "a.vcf", len(VCF)) == ("contacts", 2)
    assert detect_export(VCF, "a.vcf", len(VCF) + 1000) == ("contacts", None)
    assert detect_export(b"\n\n " + VCF[3:], "A.VCF", 10**6) == ("contacts", None)


def test_detect_xml():
    assert detect_export(SMS_HEAD.encode(), "sms.xml", 10**6) == ("sms", 60)
    assert detect_export(b'<?xml version="1.0"?><calls count="20">', "c.xml", 10**6) == ("calls", 20)
    assert detect_export(b"<smses>", "s.XML", 10**6) == ("sms", None)


def test_detect_xml_truncated_head():
    head = (SMS_HEAD + '\n  <sms body="Zaż').encode()[:-1]  # ucięte w środku bajtów "ż"
    assert detect_export(head, "sms.xml", 10**6) == ("sms", 60)


def test_detect_rejects():
    assert detect_export(b"hello", "a.vcf", 5) is None
    assert detect_export(b"<manifest>", "a.xml", 10) is None
    assert detect_export(VCF, "a.txt", len(VCF)) is None
    assert detect_export(b"", "a.vcf", 0) is None
    assert detect_export(b"", "a.xml", 0) is None
    assert detect_export(b"<smses count='1'>", "a.vcf", 20) is None
    assert detect_export(VCF, "a.xml", len(VCF)) is None


def test_count_export(tmp_path):
    vcf = tmp_path / "a.vcf"
    vcf.write_bytes(b"\xef\xbb\xbf" + (VCARD * 3).encode())
    assert count_export(vcf, "contacts") == 3
    sms = tmp_path / "s.xml"
    sms.write_text('<?xml version="1.0"?><smses count="3"><sms body="a"/><sms body="b"/>'
                   '<mms date="1"/></smses>', encoding="utf-8")
    assert count_export(sms, "sms") == 3
    calls = tmp_path / "c.xml"
    calls.write_text('<calls count="4"><call/><call/><call/><call/></calls>', encoding="utf-8")
    assert count_export(calls, "calls") == 4
    with pytest.raises(ExportFormatError):
        count_export(vcf, "sms")
    with pytest.raises(ExportFormatError):
        count_export(sms, "calls")
    with pytest.raises(ExportFormatError):
        count_export(calls, "contacts")
    bad = tmp_path / "bad.xml"
    bad.write_text('<smses count="3"><sms body="a"/><sms bo', encoding="utf-8")
    with pytest.raises(ExportFormatError):
        count_export(bad, "sms")


def _put(phone: FakeStoragePhone, rel: str, data: bytes, mtime: int) -> RemoteFile:
    path = phone.root / "sdcard" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return RemoteFile(f"/sdcard/{rel}", len(data), mtime, "other:x")


def test_find_exports_newest_first_and_filtered(tmp_path):
    phone = FakeStoragePhone(tmp_path)
    files = [
        _put(phone, "Kopia/a.vcf", VCF, 100),
        _put(phone, "Download/b.vcf", VCF, 300),
        _put(phone, "Download/notes.vcf", b"hello", 400),
        _put(phone, "Backup/sms-1.xml", b'<smses count="5">', 200),
        _put(phone, "Download/x.xml", b"<manifest>", 50),
    ]
    found = find_exports(phone, files, {"contacts", "sms"}, lambda: False)
    assert found == {
        "contacts": [ExportFile("/sdcard/Download/b.vcf", len(VCF), 300, "contacts", 2),
                     ExportFile("/sdcard/Kopia/a.vcf", len(VCF), 100, "contacts", 2)],
        "sms": [ExportFile("/sdcard/Backup/sms-1.xml", 17, 200, "sms", 5)],
    }
    assert phone.commands and all(c.startswith(f"head -c {HEAD_BYTES} ") for c in phone.commands)
    only = find_exports(phone, files, {"contacts"}, lambda: False)
    assert set(only) == {"contacts"}


def test_find_exports_caps_candidates(tmp_path):
    phone = FakeStoragePhone(tmp_path)
    files = [_put(phone, f"D/n{i}.xml", b"<manifest>", 1000 + i) for i in range(60)]
    files.append(_put(phone, "D/old.xml", b'<smses count="1">', 1))
    assert find_exports(phone, files, {"sms"}, lambda: False) == {}
    assert len(phone.commands) == MAX_CANDIDATES


def test_find_exports_stop_and_per_file_error(tmp_path):
    phone = FakeStoragePhone(tmp_path)
    ok = _put(phone, "a.vcf", VCF, 10)
    gone = RemoteFile("/sdcard/gone.vcf", 5, 20, "other:x")
    assert list(find_exports(phone, [gone, ok], {"contacts"}, lambda: False)) == ["contacts"]
    assert find_exports(phone, [ok], {"contacts"}, lambda: True) == {}


def test_find_exports_connection_error_propagates(tmp_path):
    phone = FakeStoragePhone(tmp_path)
    ok = _put(phone, "a.vcf", VCF, 10)
    phone.online = False
    with pytest.raises(AdbError):
        find_exports(phone, [ok], {"contacts"}, lambda: False)


def test_head_cmd_quotes_odd_path(tmp_path):
    phone = FakeStoragePhone(tmp_path)
    f = _put(phone, "Kopia kontaktów/it's.vcf", VCF, 10)
    found = find_exports(ReadOnlyAdb(phone), [f], {"contacts"}, lambda: False)
    assert found["contacts"][0].remote == "/sdcard/Kopia kontaktów/it's.vcf"
