import json
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
