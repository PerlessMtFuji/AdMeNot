import json
import subprocess
import sys
import threading
from datetime import datetime

import pytest

from admenot.app import crash
from admenot.engine.paths import crashes_dir, logs_dir
from admenot.engine.settings import save_settings

STARTED = datetime(2026, 10, 9, 14, 0, 0)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    save_settings({"lang": "pl"})
    crash.reset_session()
    yield
    crash.reset_session()


def marker(fault=""):
    crashes_dir().mkdir(parents=True, exist_ok=True)
    (crashes_dir() / "running.json").write_text(
        json.dumps({"app": "0.9.3", "started": STARTED.isoformat()}), "utf-8")
    (crashes_dir() / "fault.txt").write_text(fault, "utf-8")


def reports():
    return [json.loads(p.read_text("utf-8")) for p in crashes_dir().glob("2*.json")]


def test_clean_session_leaves_nothing():
    assert crash.claim_session()  # start_session wołane tylko po objęciu sesji
    crash.start_session(now=lambda: STARTED)
    assert (crashes_dir() / "running.json").is_file()
    crash.end_session()
    assert not (crashes_dir() / "running.json").exists()
    assert not (crashes_dir() / "fault.txt").exists()
    assert crash.recover() is None and reports() == []


def test_marker_with_fault_dump_becomes_exit_report():
    marker("Windows fatal exception: access violation\n\nThread 0x1 (most recent call first):\n"
           '  File "C:\\x\\y.py", line 3 in f\n')
    crash_id = crash.recover(now=lambda: datetime(2026, 10, 9, 15, 0, 0))
    data = reports()[0]
    assert crash_id and data["kind"] == "exit" and data["error"]["type"] == "fatal"
    assert data["error"]["message"] == "Windows fatal exception: access violation"
    assert "line 3 in f" in data["error"]["trace"]
    assert not (crashes_dir() / "running.json").exists()


COM_BLOCK = ("Windows fatal exception: code 0x8001010d\n\n"
             "Current thread 0x0001c188 (most recent call first):\n"
             '  File "webview\\platforms\\winforms.py", line 808 in create\n\n')


def test_handled_com_exception_alone_is_not_a_crash():
    marker(COM_BLOCK)
    assert crash.recover() is None
    assert reports() == [] and not (crashes_dir() / "running.json").exists()


def test_real_fault_after_com_exception_is_reported_without_it():
    marker(COM_BLOCK + "Windows fatal exception: access violation\n\n"
           "Thread 0x1 (most recent call first):\n"
           '  File "threading.py", line 1342 in run\n')
    crash.recover(now=lambda: datetime(2026, 10, 9, 15, 0, 0))
    data = reports()[0]
    assert data["error"]["message"] == "Windows fatal exception: access violation"
    assert "0x8001010d" not in data["error"]["trace"] and "line 1342 in run" in data["error"]["trace"]


def test_fatal_ntstatus_warning_codes_are_kept():
    marker(COM_BLOCK + "Windows fatal exception: code 0x80000003\n\n"
           "Thread 0x1 (most recent call first):\n")
    crash.recover(now=lambda: datetime(2026, 10, 9, 15, 0, 0))
    assert reports()[0]["error"]["message"] == "Windows fatal exception: code 0x80000003"


def test_marker_with_log_entries_after_start():
    marker()
    log = logs_dir() / "app-2026-10-09.log"
    log.parent.mkdir(parents=True)
    log.write_text("--- 2026-10-09T13:59:00\nOld: before\n\n"
                   "--- 2026-10-09T14:05:00\nTraceback...\nValueError: after\n\n", "utf-8")
    crash.recover(now=lambda: datetime(2026, 10, 9, 15, 0, 0))
    data = reports()[0]
    assert data["error"]["type"] == "exit"
    assert "ValueError: after" in data["log_tail"] and "Old: before" not in data["log_tail"]


def test_bare_marker_is_removed_silently():
    marker()
    assert crash.recover() is None
    assert reports() == [] and not (crashes_dir() / "running.json").exists()


def test_broken_marker_is_removed():
    crashes_dir().mkdir(parents=True)
    (crashes_dir() / "running.json").write_text("{zły", "utf-8")
    assert crash.recover() is None and not (crashes_dir() / "running.json").exists()


def test_thread_hook_writes_thread_report(monkeypatch):
    previous = []
    monkeypatch.setattr(threading, "excepthook", lambda args: previous.append(args))
    monkeypatch.setattr(sys, "excepthook", lambda *a: None)
    crash.install_hooks()

    def work():
        raise RuntimeError("w wątku")

    t = threading.Thread(target=work, name="admenot-test")
    t.start()
    t.join()
    data = reports()[0]
    assert data["kind"] == "thread" and data["context"]["call"] == "thread:admenot-test"
    assert previous  # poprzedni hak dalej wołany


def _other_process_claims(tmp_path):
    code = ("import sys; from admenot.app import crash; "
            "sys.stdout.write(str(crash.claim_session()))")
    env = {**__import__("os").environ, "LOCALAPPDATA": str(tmp_path / "data")}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                         check=True, timeout=60)
    return out.stdout.strip()


def test_claim_is_exclusive_across_processes(tmp_path):
    assert crash.claim_session() is True
    assert _other_process_claims(tmp_path) == "False"
    crash.end_session()
    assert _other_process_claims(tmp_path) == "True"
    assert crash.claim_session() is True


def test_end_session_without_claim_keeps_foreign_marker():
    marker("coś")
    crash.end_session()
    assert (crashes_dir() / "running.json").is_file()
    assert (crashes_dir() / "fault.txt").is_file()


def test_traceback_containing_dashes_is_not_split():
    marker()
    log = logs_dir() / "app-2026-10-09.log"
    log.parent.mkdir(parents=True)
    log.write_text("--- 2026-10-09T14:05:00\nTraceback\nValueError: a --- b\n\n", "utf-8")
    crash.recover(now=lambda: datetime(2026, 10, 9, 15, 0, 0))
    assert "ValueError: a --- b" in reports()[0]["log_tail"]


def test_crashed_session_serials_and_device_reach_exit_report():
    assert crash.claim_session()
    crash.start_session(now=lambda: STARTED)
    crash.note_serials(["R58T00TEST"])
    crash.note_device("R58T00TEST", "OPPO", "CPH2483", "14")
    saved = json.loads((crashes_dir() / "running.json").read_text("utf-8"))
    assert saved["serials"] == ["R58T00TEST"] and saved["device"]["model"] == "CPH2483"
    assert saved["started"] == STARTED.isoformat()
    # symulacja awarii: proces znika bez end_session, nowy proces startuje z czystą sesją
    crash.reset_session()
    (crashes_dir() / "fault.txt").write_text(
        "Windows fatal exception: access violation (R58T00TEST)\n  File \"x.py\", line 3 in f\n", "utf-8")
    log = logs_dir() / "app-2026-10-09.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("--- 2026-10-09T14:05:00\nAdbError: device R58T00TEST offline\n\n", "utf-8")
    crash.recover(now=lambda: datetime(2026, 10, 9, 15, 0, 0))
    data = reports()[0]
    assert "R58T00TEST" not in json.dumps(data)
    assert "<serial>" in data["error"]["message"] and "<serial>" in data["log_tail"]
    assert data["context"]["device"] == {"manufacturer": "OPPO", "model": "CPH2483", "android": "14"}
    # nowa sesja nie dziedziczy telefonu ani numerów po awarii
    later = crash.capture(type_="Other", message="R58T00TEST", now=lambda: datetime(2026, 10, 9, 15, 1, 0))
    other = json.loads((crashes_dir() / f"{later}.json").read_text("utf-8"))
    assert other["context"]["device"] is None and other["error"]["message"] == "R58T00TEST"


def test_note_serials_without_session_does_not_write_marker():
    crash.note_serials(["R58T00TEST"])
    assert not (crashes_dir() / "running.json").exists()


def test_bad_serials_in_marker_are_ignored():
    crashes_dir().mkdir(parents=True, exist_ok=True)
    (crashes_dir() / "running.json").write_text(json.dumps(
        {"app": "0.9.3", "started": STARTED.isoformat(), "serials": "R58T00TEST", "device": [1]}), "utf-8")
    (crashes_dir() / "fault.txt").write_text("fatal", "utf-8")
    assert crash.recover(now=lambda: datetime(2026, 10, 9, 15, 0, 0))
    assert reports()[0]["context"]["device"] is None
