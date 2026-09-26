import json
import threading
from datetime import datetime
from pathlib import Path

import pytest

from demalware.app.errors import AppError, error_payload, log_exception, report_error
from demalware.app.events import RecordingEmitter, WindowEmitter, js_event
from demalware.engine.actions.errors import ActionError
from demalware.engine.adb.transport import AdbError


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def test_js_event_is_safe_for_any_text():
    detail = {"label": '<script>alert("x")</script> &   Źdźbło'}
    script = js_event("scan:done", detail)
    assert script.startswith('window.dispatchEvent(new CustomEvent("demalware:scan:done", {detail: ')
    assert script.endswith("}));")
    assert " " not in script and "\\u2028" in script
    payload = script[len('window.dispatchEvent(new CustomEvent("demalware:scan:done", {detail: '):-4]
    assert json.loads(payload) == detail


def test_window_emitter_calls_run_js_and_survives_a_closed_window():
    class Window:
        def __init__(self):
            self.scripts = []

        def run_js(self, script):
            self.scripts.append(script)

    window = Window()
    WindowEmitter(lambda: window).emit("devices", {"devices": []})
    assert window.scripts == [js_event("devices", {"devices": []})]

    class Closed:
        def run_js(self, script):
            raise RuntimeError("window closed")

    WindowEmitter(lambda: Closed()).emit("x", 1)
    WindowEmitter(lambda: None).emit("x", 1)


def test_recording_emitter_sees_json_like_js_and_waits():
    rec = RecordingEmitter()
    rec.emit("a", {"when": datetime(2026, 9, 26), "items": (1, 2)})
    assert rec.of("a") == [{"when": "2026-09-26 00:00:00", "items": [1, 2]}]
    threading.Timer(0.05, lambda: rec.emit("later", {"ok": True})).start()
    assert rec.wait_for("later", timeout=2) == {"ok": True}
    assert rec.names() == ["a", "later"]
    with pytest.raises(TimeoutError):
        rec.wait_for("never", timeout=0.05)


def test_error_payloads():
    assert error_payload(AppError("wrong_device", "S1", serial="S1")) == {
        "key": "wrong_device", "message": "S1", "serial": "S1"}
    assert error_payload(AdbError("no_device", "gone"))["key"] == "disconnected"
    assert error_payload(AdbError("adb_missing", "x"))["key"] == "adb_missing"
    assert error_payload(AdbError("command_failed", "x"))["key"] == "adb_error"
    assert error_payload(ActionError("offline"))["key"] == "offline"
    assert error_payload(ActionError("security", "denied")) == {"key": "action_error",
                                                                "message": "denied"}
    assert error_payload(ValueError("bad"))["key"] == "bad_request"
    assert error_payload(KeyError("x"))["key"] == "internal"


def test_internal_errors_are_logged(data_dir):
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        payload = report_error(exc)
    path = Path(payload["log"])
    assert payload["key"] == "internal" and path.parent == data_dir / "DeMalware" / "logs"
    text = path.read_text("utf-8")
    assert "RuntimeError: boom" in text and "Traceback" in text
    assert "log" not in report_error(AppError("busy"))
    assert log_exception(ValueError("v")).name.startswith("app-")
