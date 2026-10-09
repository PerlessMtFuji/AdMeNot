import json
import os
import threading
import time
from datetime import datetime, timedelta

import pytest

from admenot.app import crash
from admenot.engine.paths import crashes_dir, logs_dir
from admenot.engine.settings import save_settings
from admenot.net import client

NOW = datetime(2026, 10, 9, 14, 3, 12)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("USERNAME", "jkowal")
    save_settings({"lang": "pl"})
    crash.reset_session()
    yield
    crash.reset_session()


def boom(message="'com.example'"):
    try:
        raise KeyError(message)
    except KeyError as exc:
        return exc


def load(crash_id):
    return json.loads((crashes_dir() / f"{crash_id}.json").read_text("utf-8"))


def test_capture_writes_report_with_context():
    crash.note_serials(["R58T00TEST"])
    crash.note_device("R58T00TEST", "OPPO", "CPH2483", "14")
    crash_id = crash.capture(boom("R58T00TEST gone"), context={"call": "plan_order", "job": "exec"},
                             now=lambda: NOW)
    data = load(crash_id)
    assert crash_id.startswith("20261009-140312-")
    assert data["format"] == 1 and data["kind"] == "error" and data["count"] == 1
    assert data["lang"] == "pl" and data["os"].startswith(("Windows", "Linux", "Darwin"))
    assert data["context"] == {"call": "plan_order", "job": "exec", "screen": None,
                               "device": {"manufacturer": "OPPO", "model": "CPH2483", "android": "14"}}
    assert data["error"]["type"] == "KeyError"
    assert "<serial>" in data["error"]["message"] and "R58T00TEST" not in json.dumps(data)
    assert data["error"]["where"].startswith("test_app_crash.py:") and "in boom" in data["error"]["where"]
    assert data["sent"] is None and data["adb_tail"] is None


def test_duplicate_in_session_increments_count():
    first = crash.capture(boom(), now=lambda: NOW)
    second = crash.capture(boom(), now=lambda: NOW + timedelta(seconds=5))
    assert first == second and load(first)["count"] == 2
    assert len(list(crashes_dir().glob("*.json"))) == 1


def test_limits_trace_and_message():
    crash_id = crash.capture(type_="X", message="m" * 5000, trace="t" * 40000, now=lambda: NOW)
    data = load(crash_id)
    assert len(data["error"]["message"]) == 1000
    assert len(data["error"]["trace"]) == 16384 and data["error"]["trace"].endswith("t")


def test_adb_tail_from_session_log():
    crash.note_serials(["R58T00TEST"])
    log = logs_dir() / "2026-10-09.log"
    log.parent.mkdir(parents=True)
    lines = [f"2026-10-09T14:0{i % 10}:00\tR58T00TEST\tok\t0.1s\tshell:cmd{i}\n" for i in range(60)]
    log.write_text("".join(lines), "utf-8")
    data = load(crash.capture(boom(), now=lambda: NOW))
    assert len(data["adb_tail"]) == 50 and data["adb_tail"][-1].endswith("shell:cmd59")
    assert all("R58T00TEST" not in line for line in data["adb_tail"])


def test_at_most_twenty_files():
    for i in range(22):
        crash.capture(type_=f"E{i}", message="x", now=lambda i=i: NOW + timedelta(seconds=i))
    names = sorted(p.name for p in crashes_dir().glob("*.json"))
    assert len(names) == 20 and names[0].startswith("20261009-140314-")


def test_capture_never_raises_when_directory_is_unwritable(monkeypatch):
    monkeypatch.setattr(crash, "crashes_dir", lambda: crashes_dir() / "nul\0bad")
    assert crash.capture(boom(), now=lambda: NOW) is None


def test_corrupt_file_is_skipped_and_pruned():
    crashes_dir().mkdir(parents=True)
    (crashes_dir() / "20261001-000000-zzzz.json").write_text("{nie json", "utf-8")
    (crashes_dir() / "20261001-000001-yyyy.json").write_text('{"format": 7}', "utf-8")
    good = crash.capture(boom(), now=lambda: NOW)
    assert [r["id"] for r in crash.list_reports()] == [good]
    crash.prune(now=lambda: NOW)
    assert sorted(p.stem for p in crashes_dir().glob("*.json")) == [good]


def test_old_files_pruned_after_thirty_days():
    old = crash.capture(type_="Old", message="x", now=lambda: NOW - timedelta(days=31))
    new = crash.capture(type_="New", message="x", now=lambda: NOW)
    crash.prune(now=lambda: NOW)
    assert [r["id"] for r in crash.list_reports()] == [new] and old != new


def test_preview_is_exactly_what_send_posts():
    crash_id = crash.capture(boom(), now=lambda: NOW)
    posted = []
    preview = crash.preview(crash_id, include_adb=False, comment="  skan, jan@example.com  ")
    sent = crash.send(crash_id, False, "  skan, jan@example.com  ",
                      post=lambda path, body: posted.append((path, body)) or {"id": "R-7K3Q9M"},
                      now=lambda: NOW)
    assert sent == "R-7K3Q9M" and posted == [("/api/v1/reports", preview["body"])]
    body = preview["body"]
    assert body["comment"] == "skan, <email>" and body["adb_tail"] is None
    assert set(body) == {"format", "kind", "app", "os", "lang", "count", "created", "context", "error",
                         "log_tail", "adb_tail", "comment"}
    assert load(crash_id)["sent"] == {"id": "R-7K3Q9M", "at": "2026-10-09T14:03:12"}


def test_include_adb_and_empty_comment():
    log = logs_dir() / "2026-10-09.log"
    log.parent.mkdir(parents=True)
    log.write_text("2026-10-09T14:00:00\tS123\tok\t0.1s\tshell:pm list packages\n", "utf-8")
    crash_id = crash.capture(boom(), now=lambda: NOW)
    view = crash.preview(crash_id, include_adb=True, comment="")
    assert view["has_adb"] is True and view["body"]["adb_tail"] == ["14:00:00\tok\t0.1s\tshell:pm list packages"]
    assert view["body"]["comment"] is None
    assert len(crash.preview(crash_id, False, "x" * 2000)["body"]["comment"]) == 1000


def test_second_send_returns_same_id_without_request():
    crash_id = crash.capture(boom(), now=lambda: NOW)
    crash.send(crash_id, False, None, post=lambda p, b: {"id": "R-7K3Q9M"}, now=lambda: NOW)

    def fail(path, body):
        raise AssertionError("drugi POST")

    assert crash.send(crash_id, False, None, post=fail) == "R-7K3Q9M"
    assert crash.list_reports()[0]["sent_id"] == "R-7K3Q9M"


def test_send_failure_keeps_report_unsent():
    crash_id = crash.capture(boom(), now=lambda: NOW)

    def offline(path, body):
        raise client.BackendError("offline")

    with pytest.raises(client.BackendError):
        crash.send(crash_id, False, None, post=offline)
    assert load(crash_id)["sent"] is None


def test_bad_server_id_is_invalid():
    crash_id = crash.capture(boom(), now=lambda: NOW)
    with pytest.raises(client.BackendError) as caught:
        crash.send(crash_id, False, None, post=lambda p, b: {"id": "<script>"})
    assert caught.value.kind == "invalid"


@pytest.mark.parametrize("bad", ["../settings", "20261009-140312-ABCD", "nope"])
def test_unknown_or_malformed_id(bad):
    with pytest.raises(crash.UnknownCrash):
        crash.preview(bad, False, None)
    with pytest.raises(crash.UnknownCrash):
        crash.discard(bad)


def test_discard_removes_file():
    crash_id = crash.capture(boom(), now=lambda: NOW)
    crash.discard(crash_id)
    assert crash.list_reports() == []


def test_startup_reports_once_and_only_unsent_exit_or_thread():
    err = crash.capture(boom(), now=lambda: NOW)
    thread = crash.capture(type_="RuntimeError", message="x", kind="thread", now=lambda: NOW)
    assert crash.startup_reports() == [thread]
    assert crash.startup_reports() == []
    assert err in {r["id"] for r in crash.list_reports()}


def test_running_marker_survives_capture_and_prune():
    crashes_dir().mkdir(parents=True)
    marker = crashes_dir() / "running.json"
    marker.write_text(json.dumps({"app": "0.9.3", "started": "2026-10-09T14:00:00"}), "utf-8")
    crash.capture(boom(), now=lambda: NOW)
    crash.prune(now=lambda: NOW)
    assert marker.exists()


def test_prune_removes_leftover_tmp_files():
    crashes_dir().mkdir(parents=True)
    leftover = crashes_dir() / "20261009-140312-abcd.1234.tmp"
    leftover.write_text("x", "utf-8")
    old = time.time() - 120  # starsze niż 60 s — świeże mogą być zapisem w toku
    os.utime(leftover, (old, old))
    crash.prune(now=lambda: NOW)
    assert list(crashes_dir().glob("*.tmp")) == []


def test_concurrent_sends_post_once():
    crash_id = crash.capture(boom(), now=lambda: NOW)
    calls = []

    def slow(path, body):
        calls.append(1)
        time.sleep(0.2)
        return {"id": "R-7K3Q9M"}

    results = []
    threads = [threading.Thread(target=lambda: results.append(crash.send(crash_id, False, None, post=slow)))
               for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(calls) == 1 and results == ["R-7K3Q9M", "R-7K3Q9M"]


def _encoded(body):
    return len(json.dumps(body).encode("utf-8"))  # dokładnie jak client.post_json


def test_body_with_cjk_fits_server_limit_and_keeps_trace_end():
    trace = "漢" * 16000 + "END-OF-TRACE"
    crash_id = crash.capture(type_="X", message="字" * 1000, trace=trace, log_tail="語" * 8192,
                             now=lambda: NOW)
    body = crash.preview(crash_id, include_adb=False, comment="評" * 1000)["body"]
    assert _encoded(body) <= 60000
    assert body["error"]["trace"].endswith("END-OF-TRACE")
    assert load(crash_id)["error"]["trace"].startswith("漢")  # plik bez zmian
    posted = []
    crash.send(crash_id, False, "評" * 1000,
               post=lambda p, b: posted.append(b) or {"id": "R-7K3Q9M"}, now=lambda: NOW)
    assert posted == [body]


def test_body_small_report_is_untouched():
    crash_id = crash.capture(type_="X", message="m", trace="t" * 100, log_tail="l" * 100, now=lambda: NOW)
    body = crash.preview(crash_id, False, None)["body"]
    assert body["error"]["trace"] == "t" * 100 and body["log_tail"] == "l" * 100


def test_adb_tail_redacts_serial_from_its_own_row_without_session():
    log = logs_dir() / "2026-10-09.log"
    log.parent.mkdir(parents=True)
    log.write_text("2026-10-09T14:00:00\tR58T00TEST\tok\t0.1s\thost:-s R58T00TEST get-state\n"
                   "2026-10-09T14:00:01\tNone\tok\t0.1s\thost:devices None\n", "utf-8")
    data = load(crash.capture(boom(), now=lambda: NOW))
    assert all("R58T00TEST" not in line for line in data["adb_tail"])
    assert "<serial>" in data["adb_tail"][0]
    assert data["adb_tail"][1].endswith("host:devices None")  # „None” to nie numer seryjny


def offline(path, body):
    raise client.BackendError("offline")


@pytest.mark.parametrize("error", [client.BackendError("offline"), client.BackendError("http", 429),
                                   client.BackendError("http", 503)])
def test_unreachable_server_queues_report_with_users_choices(error):
    crash_id = crash.capture(boom(), now=lambda: NOW)

    def fail(path, body):
        raise error

    with pytest.raises(client.BackendError):
        crash.send(crash_id, True, "  skan, jan@example.com ", post=fail)
    assert load(crash_id)["queued"] == {"include_adb": True, "comment": "skan, <email>"}
    assert load(crash_id)["sent"] is None


def test_queued_report_is_sent_in_background_with_saved_choices():
    crash_id = crash.capture(boom(), now=lambda: NOW)
    with pytest.raises(client.BackendError):
        crash.send(crash_id, True, "opis", post=offline)
    assert crash.send_queued(post=offline) is True  # dalej brak sieci — czeka
    posted = []
    assert crash.send_queued(post=lambda p, b: posted.append(b) or {"id": "R-7K3Q9M"},
                             now=lambda: NOW) is False
    assert len(posted) == 1 and posted[0]["comment"] == "opis"
    data = load(crash_id)
    assert data["sent"]["id"] == "R-7K3Q9M" and "queued" not in data
    assert crash.send_queued(post=offline) is False  # nic już nie czeka


def test_rejected_report_leaves_the_queue():
    crash_id = crash.capture(boom(), now=lambda: NOW)
    with pytest.raises(client.BackendError):
        crash.send(crash_id, False, None, post=offline)

    def rejected(path, body):
        raise client.BackendError("http", 400)

    assert crash.send_queued(post=rejected) is False
    assert "queued" not in load(crash_id) and load(crash_id)["sent"] is None


def test_report_deleted_during_background_send_stays_deleted():
    crash_id = crash.capture(boom(), now=lambda: NOW)
    with pytest.raises(client.BackendError):
        crash.send(crash_id, False, None, post=offline)
    deleter = []

    def accepted_while_user_deletes(path, body):
        t = threading.Thread(target=lambda: deleter.append(crash.discard(crash_id)))
        t.start()
        t.join(0.2)  # usuwanie czeka na koniec wysyłki
        return {"id": "R-7K3Q9M"}

    assert crash.send_queued(post=accepted_while_user_deletes) is False
    for _ in range(100):
        if deleter:
            break
        time.sleep(0.01)
    assert not (crashes_dir() / f"{crash_id}.json").exists()
    assert crash.send_queued(post=offline) is False


def test_background_rejection_returns_crash_report_to_banner():
    thread = crash.capture(type_="RuntimeError", message="x", kind="thread", now=lambda: NOW)
    crash.startup_reports()
    with pytest.raises(client.BackendError):
        crash.send(thread, False, None, post=offline)

    def rejected(path, body):
        raise client.BackendError("http", 400)

    crash.send_queued(post=rejected)
    assert crash.startup_reports() == [thread]


def test_queued_crash_report_is_not_offered_again_in_banner():
    thread = crash.capture(type_="RuntimeError", message="x", kind="thread", now=lambda: NOW)
    assert crash.startup_reports() == [thread]
    with pytest.raises(client.BackendError):
        crash.send(thread, False, None, post=offline)
    assert crash.startup_reports() == []
    assert [r["id"] for r in crash.list_reports()] == [thread]


def test_background_queue_retries_until_sent(monkeypatch):
    crash_id = crash.capture(boom(), now=lambda: NOW)
    with pytest.raises(client.BackendError):
        crash.send(crash_id, False, None, post=offline)
    answers = iter([client.BackendError("offline"), {"id": "R-7K3Q9M"}])

    def post(path, body):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(client, "post_json", post)
    monkeypatch.setattr(crash, "QUEUE_FIRST", 0.01)
    monkeypatch.setattr(crash, "QUEUE_RETRY", (0.01,))
    crash.start_queue()
    try:
        for _ in range(300):
            if load(crash_id)["sent"]:
                break
            time.sleep(0.01)
    finally:
        crash.stop_queue()
    assert load(crash_id)["sent"]["id"] == "R-7K3Q9M"


def test_file_with_bad_shape_is_skipped_and_pruned():
    good = crash.capture(boom(), now=lambda: NOW)
    data = load(good)
    del data["created"]
    (crashes_dir() / "20261009-140000-badd.json").write_text(json.dumps(data), "utf-8")
    for key, value in (("count", 0), ("error", {"type": 5}), ("sent", {"id": 7}), ("context", None)):
        broken = {**load(good), key: value}
        (crashes_dir() / f"20261009-13000{len(key) % 10}-{key[:4]:x<4}.json").write_text(
            json.dumps(broken), "utf-8")
    assert [r["id"] for r in crash.list_reports()] == [good]
    crash.prune(now=lambda: NOW)
    assert [p.stem for p in crashes_dir().glob("*.json")] == [good]


def test_context_and_device_fields_capped_at_64():
    crash.note_device("S1234", "M" * 100, "X" * 100, "1" * 100)
    crash_id = crash.capture(boom(), context={"call": "thread:" + "n" * 100, "job": "j" * 100,
                                              "screen": "s" * 100}, now=lambda: NOW)
    ctx = crash.preview(crash_id, False, None)["body"]["context"]
    assert all(len(ctx[k]) == 64 for k in ("call", "job", "screen"))
    assert all(len(v) == 64 for v in ctx["device"].values())


def test_prune_keeps_fresh_tmp_files(tmp_path):
    crashes_dir().mkdir(parents=True)
    fresh = crashes_dir() / "20261009-140312-abcd.5678.tmp"
    fresh.write_text("x", "utf-8")
    crash.prune(now=lambda: NOW)
    assert fresh.exists()  # zapis w toku w innym wątku
