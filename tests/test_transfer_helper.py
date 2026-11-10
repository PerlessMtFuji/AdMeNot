import hashlib
import json
import re
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


def test_parse_output_appop_ignored_insert_is_denied_not_ok():
    # An insert ignored by appop returns `<uri>/0`; the helper reports DENIED instead of OK, so the
    # record is not marked done and the next path (companion) gets it.
    out = helper.parse_output(["DENIED", "DONE 0 0"])
    assert out.ok == set() and out.failed == {} and out.denied and not out.finished


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


def test_companion_writer_creates_input_folder_before_push():
    # Fresh install: `Android/data/<pkg>` does not exist, so a push to `.../in/` fails with
    # "Is a directory" unless `mkdir -p` ran first.
    order: list[str] = []

    class Adb(FakeAdb):
        def shell(self, command, timeout=20.0):
            order.append(command)
            return super().shell(command, timeout)

    class Pusher(FakePusher):
        def push(self, locals_, remote, should_stop, tick):
            order.append("push " + remote)
            return super().push(locals_, remote, should_stop, tick)

    adb = Adb({"am instrument": "INSTRUMENTATION_STATUS: line=DONE 0 0\n"})
    helper.CompanionWriter(adb, Pusher(), None).write("sms", [("a1", _sms("x"))], lambda: None)
    assert order[:2] == [f"mkdir -p {helper.COMPANION_IN}", f"push {helper.COMPANION_IN}/"]


def test_artifacts_match_sums():
    for name in ("dex", "apk"):
        path, digest = helper.artifact(name)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_sources_not_newer_than_artifacts():
    sums = helper.read_sums(helper.HELPER_BIN)
    assert sums.get("sources") == helper.sources_digest(ROOT / "android" / "helper"), \
        "android/helper changed since the last build: run scripts/build_helper.py"


def _writer_source() -> str:
    return (ROOT / "android" / "helper" / "src" / "pl" / "admenot" / "helper" / "Writer.java").read_text("utf-8")


def _writer_method(name: str) -> str:
    src = _writer_source()
    m = re.search(r"\n    [\w<>, ]+ " + name + r"\([^\n;]*\{\n", src)  # a method declaration, not a call
    assert m, name
    return src[m.start():src.index("\n    }\n", m.start())]


def test_writer_bulk_inserts_sms_and_verifies_what_was_stored():
    """SmsProvider nie ma własnego `bulkInsert` (domyślny: pętla `insert()` bez transakcji), a `insert`
    po jednym był ~4× wolniejszy (OPPO: 66 s zamiast 13–17 s na 500 SMS). SMS idą więc `bulkInsert`,
    a potem helper czyta wiersze z `_id` > największego sprzed paczki i dopasowuje je po
    (address, date, type, body) tylko, gdy nowych wierszy jest inaczej niż wysłanych; nieznalezione
    wstawia po jednym (`null_uri` przy `null`) tylko, gdy dokładnie wyjaśniają lukę. Połączenia zostają przy transakcyjnym `bulkInsert`."""
    flush = _writer_method("flush")
    assert "if (sms) flushSms(ids, vals);" in flush
    assert "else flushBulk(uri, ids, vals);" in flush
    bulk = _writer_method("bulk")
    assert "flushBulk" not in bulk and "flush(uri, ids, vals, sms)" in bulk

    sms = _writer_method("flushSms")
    # 1. maxId przed paczką, 2. bulkInsert, 3. odczyt nowych wierszy, 4. brakujące po jednym
    order = [sms.index(s) for s in ("maxSmsId()", "t.bulkInsert(SMS", "storedSince(maxId)",
                                    'oneByOne(SMS, missIds, missVals, "null_uri")')]
    assert order == sorted(order)
    assert "if (isDenial(e)) throw new Denied();" in sms  # odmowa z bulkInsert jak dotąd
    # appop "ignore": mniej wierszy niż wysłano i nic nowego w tabeli → DENIED
    assert "n < ids.size() && newCount == 0) throw new Denied();" in sms
    assert "smsKey(vals.get(i))" in sms
    # tyle nowych wierszy, ile wysłano (bez wyjątku): OK bez dopasowania kluczy — dostawca, który
    # przepisuje adres albo treść, nie zrobi z dobrych wierszy „brakujących”
    count = sms.index("if (!threw && newCount == ids.size()) {")
    assert count < sms.index("smsKey(vals.get(i))")
    # pojedyncze wstawienia tylko, gdy brakujące wyjaśniają lukę dokładnie; inaczej `ERR id unverified`
    assert "boolean gapExplained = missIds.size() == ids.size() - newCount;" in sms
    # bulkInsert zwrócił liczbę: po jednym najwyżej tyle, ile według niego nie zapisał (n == size przy
    # niewidocznych odczytach nie może zdublować całej paczki)
    assert "boolean notStored = n < 0 || missIds.size() <= ids.size() - n;" in sms
    assert ('if (gapExplained && notStored) oneByOne(SMS, missIds, missVals, "null_uri");\n'
            "        else for (String id : missIds) errId(id, UNVERIFIED);") in sms
    assert 'static final String UNVERIFIED = "unverified";' in _writer_source()

    newest = _writer_method("maxSmsId")
    assert '"_id DESC"' in newest and "return 0;" in newest  # pusta tabela → 0
    since = _writer_method("storedSince")
    assert '"_id > ?"' in since
    for col in ('"address"', '"date"', '"type"', '"body"'):
        assert col in since
    key = _writer_method("smsKey")
    for col in ('"address"', '"date"', '"type"', '"body"'):
        assert col in key

    one = _writer_method("oneByOne")
    assert "errId(ids.get(i), nullCode)" in one and "rejected(u)) throw new Denied()" in one


def test_writer_gives_sms_their_thread_once_per_address():
    """Bez `thread_id` SmsProvider szuka wątku przy każdym wierszu: na OPPO (~24 tys. SMS) połowa czasu
    zapisu (56 s → 31 s na 1500 SMS). Pomocnik pyta raz na numer, tym samym URI co platforma; adresy
    e-mail i nieudane odczyty zostawia dostawcy (bez `thread_id`), a odmowę wykrywa sam zapis."""
    sms = _writer_method("flushSms")
    assert sms.index("withThreads(vals);") < sms.index("maxSmsId()")
    threads = _writer_method("withThreads")
    assert "smsThreads.get(addr)" in threads and "smsThreads.put(addr, tid)" in threads
    assert "addr.indexOf('@') >= 0" in threads and 'v.containsKey("thread_id")' in threads
    assert 'if (tid > 0) v.put("thread_id", tid);' in threads
    one = _writer_method("smsThread")
    assert '"content://mms-sms/threadID"' in one and '"recipient", addr' in one
    assert "catch (Exception ignored)" in one and "return 0;" in one and "Denied" not in one


def test_writer_bulk_calls_keep_the_transactional_fallback():
    flush = _writer_method("flushBulk")
    assert 'oneByOne(uri, ids, vals, "insert_null")' in flush
    assert "if (n < ids.size()) throw new Denied();" in flush


def test_build_without_keystore_leaves_shipped_artifacts(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_helper", ROOT / "scripts" / "build_helper.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    shipped = tmp_path / "helper_bin"
    shipped.mkdir()
    for name in ("admenot-helper.dex", "admenot-helper.apk", "SHA256SUMS"):
        (shipped / name).write_bytes(b"old " + name.encode())

    def fake_dex(javac, bt, jar, work):
        out = work / "classes.dex"
        out.write_bytes(b"new dex")
        return out

    monkeypatch.setattr(mod, "OUT", shipped)
    monkeypatch.setattr(mod, "LOCAL_OUT", tmp_path / "local")
    monkeypatch.setattr(mod, "find_sdk", lambda: tmp_path)
    monkeypatch.setattr(mod, "find_build_tools", lambda sdk: tmp_path / "bt")
    monkeypatch.setattr(mod, "find_android_jar", lambda sdk: tmp_path / "android.jar")
    monkeypatch.setattr(mod, "find_javac", lambda explicit: tmp_path / "javac")
    monkeypatch.setattr(mod, "build_dex", fake_dex)
    monkeypatch.delenv("ADMENOT_HELPER_KEYSTORE", raising=False)
    assert mod.main([]) == 3
    for name in ("admenot-helper.dex", "admenot-helper.apk", "SHA256SUMS"):
        assert (shipped / name).read_bytes() == b"old " + name.encode(), name
    assert (tmp_path / "local" / "admenot-helper.dex").read_bytes() == b"new dex"
