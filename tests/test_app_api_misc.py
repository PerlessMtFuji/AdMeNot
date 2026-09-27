import pytest
from apphelpers import make_api
from conftest import SERIAL
from fakephone import make_cli_phone

from demalware.engine.adb.transport import AdbError


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("DEMALWARE_ASSETS", str(tmp_path / "no-assets"))
    return tmp_path


def _scanned(**kw):
    phone = make_cli_phone()
    api, rec = make_api(phone, **kw)
    api.start_scan(SERIAL)
    rec.wait_for("apk:done")
    assert api._jobs.wait(5)
    rec.events.clear()
    return phone, api, rec


def test_console_runs_commands_and_marks_them(env):
    api, _ = make_api(make_cli_phone())
    assert api.adb_shell("getprop")["error"]["key"] == "no_device"
    _phone, api, rec = _scanned()
    assert api.adb_shell("   ")["error"]["key"] == "bad_request"
    result = api.adb_shell(" getprop ")
    assert result["ok"] is True and "ro.product.model" in result["output"]
    (entry,) = rec.of("adb:command")
    assert entry["tag"] == "console" and entry["command"] == "getprop"
    log = next((env / "data" / "DeMalware" / "logs").glob("*.log")).read_text("utf-8")
    assert "\tconsole:getprop" in log
    failed = api.adb_shell("no-such-command")
    assert failed["ok"] is False and "no response" in failed["output"]


def test_console_is_busy_during_an_order():
    _phone, api, rec = _scanned(sync=False, admin_timeout=0)
    job = api.execute({"com.clean.pro.boost": "disable"}, [])["job_id"]
    rec.wait_for("exec:question")
    assert api.adb_shell("getprop")["error"]["key"] == "busy"
    api.answer(job, "skip")
    rec.wait_for("exec:done")


def test_check_adb_and_pick_folder():
    phone = make_cli_phone()
    phone.host["version"] = "Android Debug Bridge version 1.0.41\nVersion 36.0.0\n"
    api, _ = make_api(phone)
    assert api.check_adb("C:\\adb.exe") == {"ok": True, "version": "Android Debug Bridge version 1.0.41",
                                           "message": ""}
    phone.host["version"] = AdbError("adb_missing", "not found")
    assert api.check_adb(None) == {"ok": False, "version": None, "message": "not found"}
    assert api.pick_folder() == {"path": None}
    api._attach(pick_folder=lambda: "D:\\kopie", close=lambda: None)
    assert api.pick_folder() == {"path": "D:\\kopie"}


def test_closing_during_an_order_asks_the_ui_then_quit_closes():
    _phone, api, rec = _scanned(sync=False, admin_timeout=0)
    closed = []
    api._attach(pick_folder=lambda: None, close=lambda: closed.append(True))
    api.execute({"com.clean.pro.boost": "disable"}, [])
    rec.wait_for("exec:question")
    assert api._on_closing() is False
    assert rec.of("app:close_requested") == [{"kind": "exec"}]
    assert api.quit() == {"ok": True}
    assert closed == [True] and api._jobs.current() is None
    assert rec.wait_for("exec:done")["apps"][0]["outcome"] == "failed"
    assert api._on_closing() is True


def test_closing_without_an_order_closes_at_once():
    _, api, _ = _scanned()
    api.watch_devices(True)
    assert api._on_closing() is True
    assert not api._watcher.running or api._watcher._stop.is_set()


def test_unexpected_errors_are_logged_not_raised(monkeypatch):
    api, _ = make_api(make_cli_phone())
    monkeypatch.setattr("demalware.app.api.history_view",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    error = api.history()["error"]
    assert error["key"] == "internal" and "boom" in error["message"] and error["log"]
