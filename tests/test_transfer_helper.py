import hashlib
import json
from pathlib import Path

import pytest

from admenot.engine.transfer import helper
from admenot.engine.transfer.puller import PullResult
from admenot.engine.transfer.telrecords import (
    CallRecord,
    ContactRecord,
    DataRow,
    MmsPart,
    MmsRecord,
    SmsRecord,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeAdb:
    serial = "X"

    def __init__(self, outputs: dict[str, str] | None = None) -> None:
        self.commands: list[str] = []
        self.outputs = outputs or {}

    def shell(self, command: str, timeout: float = 20.0) -> str:
        self.commands.append(command)
        for prefix, out in self.outputs.items():
            if command.startswith(prefix):
                return out
        return ""


class FakePusher:
    def __init__(self) -> None:
        self.pushes: list[tuple[list[Path], str]] = []

    def push(self, locals_, remote, should_stop, tick) -> PullResult:
        self.pushes.append(([Path(p) for p in locals_], remote))
        return PullResult(0, [], False)


def _sms(body: str) -> SmsRecord:
    return SmsRecord("+48000000001", 1000, 990, 1, 1, -1, None, body)


def test_encode_jsonl_header_and_ids(tmp_path):
    recs = [("a1", _sms("zażółć 😀\nłódź")), ("b2", _sms("drugi"))]
    path = helper.encode("sms", recs, tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"kind": "sms", "v": 1}
    assert [json.loads(x)["id"] for x in lines[1:]] == ["a1", "b2"]
    assert json.loads(lines[1])["body"] == "zażółć 😀\nłódź"


def test_encode_mms_copies_parts(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    img = src / "foto.jpg"
    img.write_bytes(b"\xff\xd8jpeg")
    rec = MmsRecord(5000, 4000, 1, 0, "temat", (("+48000000002", 137),),
                    (MmsPart("image/jpeg", "foto.jpg", None, img), MmsPart("text/plain", None, "tekst", None)))
    out = tmp_path / "out"
    path = helper.encode("mms", [("m1", rec)], out)
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[1])
    name = row["parts"][0]["file"]
    assert "/" not in name and (out / name).read_bytes() == b"\xff\xd8jpeg"
    assert row["parts"][1] == {"ct": "text/plain", "name": None, "text": "tekst", "file": None}
    assert row["addrs"] == [["+48000000002", 137]]


def test_encode_contacts_and_calls(tmp_path):
    c = ContactRecord("7", "Łukasz", True, (), (DataRow("vnd.android.cursor.item/name", (("data1", "Łukasz"),)),))
    row = json.loads(helper.encode("contacts", [("c1", c)], tmp_path).read_text("utf-8").splitlines()[1])
    assert row == {"id": "c1", "starred": 1,
                   "rows": [{"mimetype": "vnd.android.cursor.item/name", "values": {"data1": "Łukasz"}}]}
    call = CallRecord("+48000000003", 2000, 30, 2, 1, None)
    row = json.loads(helper.encode("calls", [("k1", call)], tmp_path / "c").read_text("utf-8").splitlines()[1])
    assert row["number"] == "+48000000003" and row["duration"] == 30 and "subscription_id" not in row


def test_parse_output_ok_err_done():
    out = helper.parse_output(["OK a", "OK b", "ERR c insert_null", "DONE 2 1"])
    assert out == helper.WriteOutcome({"a", "b"}, {"c": "insert_null"}, False, True)


def test_parse_output_mms_rolled_back_is_failed_not_ok():
    # The helper deletes its own partial pdu and reports ERR: the record stays unwritten (retry later).
    out = helper.parse_output(["OK m1", "ERR m2 FileNotFoundException", "OK m3", "DONE 2 1"])
    assert out.ok == {"m1", "m3"} and out.failed == {"m2": "FileNotFoundException"} and out.finished


def test_parse_output_denied_stops():
    out = helper.parse_output(["OK a", "DENIED", "OK b", "ERR c x"])
    assert out.ok == {"a"} and out.failed == {} and out.denied and not out.finished


def test_parse_instrumentation_status_lines():
    lines = ["INSTRUMENTATION_STATUS: line=OK a", "INSTRUMENTATION_STATUS_CODE: 1",
             "INSTRUMENTATION_STATUS: line=DONE 1 0", "INSTRUMENTATION_CODE: -1"]
    assert helper.parse_output(lines) == helper.WriteOutcome({"a"}, {}, False, True)


def _fake_bin(tmp_path: Path, dex: bytes) -> Path:
    d = tmp_path / "bin"
    d.mkdir()
    (d / "admenot-helper.dex").write_bytes(dex)
    (d / helper.SUMS).write_text(f"{hashlib.sha256(b'real').hexdigest()}  admenot-helper.dex\n",
                                 encoding="utf-8")
    return d


def test_artifact_hash_mismatch_raises(tmp_path):
    d = _fake_bin(tmp_path, b"tampered")
    with pytest.raises(helper.HelperBroken):
        helper.artifact("dex", d)


def test_artifact_ok(tmp_path):
    d = _fake_bin(tmp_path, b"real")
    path, digest = helper.artifact("dex", d)
    assert path == d / "admenot-helper.dex" and digest == hashlib.sha256(b"real").hexdigest()


def test_app_process_writer_flow(tmp_path, monkeypatch):
    d = _fake_bin(tmp_path, b"real")
    monkeypatch.setattr(helper, "HELPER_BIN", d)
    adb = FakeAdb({"sha256sum": f"{hashlib.sha256(b'real').hexdigest()}  /x\n",
                   "CLASSPATH=": "OK a1\nDONE 1 0\n"})
    pusher = FakePusher()
    lines = []
    w = helper.AppProcessWriter(adb, pusher, ("vnd.sec.contact.phone", "my phone"))
    out = w.write("sms", [("a1", _sms("x"))], lambda: lines.append(1))
    assert out.ok == {"a1"} and out.finished and len(lines) == 2
    run = next(c for c in adb.commands if c.startswith("CLASSPATH="))
    assert run == ("CLASSPATH=/data/local/tmp/admenot/admenot-helper.dex app_process / "
                   "pl.admenot.helper.Main write /data/local/tmp/admenot/in/input.jsonl "
                   "--account vnd.sec.contact.phone 'my phone'")
    assert adb.commands[-1] == "rm -rf /data/local/tmp/admenot/in"
    assert pusher.pushes[0][1] == "/data/local/tmp/admenot/admenot-helper.dex"
    w.write("sms", [("a1", _sms("x"))], lambda: None)
    assert sum(1 for _, r in pusher.pushes if r.endswith(".dex")) == 1  # dex tylko raz


def test_app_process_writer_bad_remote_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "HELPER_BIN", _fake_bin(tmp_path, b"real"))
    adb = FakeAdb({"sha256sum": "0000  /x\n"})
    with pytest.raises(helper.HelperBroken):
        helper.AppProcessWriter(adb, FakePusher(), None).write("sms", [("a", _sms("x"))], lambda: None)


def test_companion_writer_flow():
    adb = FakeAdb({"am instrument": "INSTRUMENTATION_STATUS: line=OK a1\n"
                                    "INSTRUMENTATION_STATUS: line=DONE 1 0\nINSTRUMENTATION_CODE: -1\n"})
    pusher = FakePusher()
    out = helper.CompanionWriter(adb, pusher, None).write("sms", [("a1", _sms("x"))], lambda: None)
    assert out.ok == {"a1"} and out.finished
    assert pusher.pushes[0][1] == helper.COMPANION_IN + "/"
    assert adb.commands[-1] == ("am instrument -w -r -e cmd write -e input "
                                f"{helper.COMPANION_IN}/input.jsonl pl.admenot.helper/.Runner")


def test_artifacts_match_sums():
    for name in ("dex", "apk"):
        path, digest = helper.artifact(name)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_sources_not_newer_than_artifacts():
    sums = helper.read_sums(helper.HELPER_BIN)
    assert sums.get("sources") == helper.sources_digest(ROOT / "android" / "helper"), \
        "android/helper changed since the last build: run scripts/build_helper.py"
