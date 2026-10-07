import pytest
from apphelpers import SlowApk, make_api, names
from conftest import SERIAL
from fakephone import make_cli_phone

from admenot.app.events import RecordingEmitter
from admenot.engine.journal.db import Journal
from admenot.engine.paths import journal_path

DISABLE = "pm disable-user --user 0 com.wlive.forecast"
WLIVE = {"com.wlive.forecast": "disable"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))


def _scanned(phone=None, **kw):
    phone = phone or make_cli_phone()
    api, rec = make_api(phone, **kw)
    api.start_scan(SERIAL, "Anna")
    rec.wait_for("apk:done")
    assert api._jobs.wait(5)  # skan (także w wątku) skończył się razem z job:end
    rec.events.clear()
    return phone, api, rec


def test_preview_needs_a_scan_and_shows_blocked_apps():
    api, _ = make_api(make_cli_phone())
    assert api.preview_plan(WLIVE)["error"]["key"] == "no_scan"
    _, api, _ = _scanned()
    view = api.preview_plan({"com.sec.android.app.launcher": "disable", **WLIVE}, [])
    assert view["runnable"] == 1 and view["apps"][0]["blocked"] is True


def test_execute_disables_and_reports():
    phone, api, rec = _scanned()
    assert api.execute(WLIVE, []) == {"job_id": "job-2"}
    seq = names(rec)
    assert seq[0] == "exec:order" and seq[-3:] == ["exec:verify", "exec:done", "job:end"]
    order = rec.of("exec:order")[0]
    assert order["order"].startswith("ZS/2026/0926/") and order["plan"]["runnable"] == 1
    steps = rec.of("exec:step")
    assert {s["status"] for s in steps} == {"running", "done"}
    assert "wyłączenie aplikacji" in {s["label"] for s in steps}
    done = rec.of("exec:done")[0]
    assert done["apps"][0]["outcome"] == "ok" and done["stopped"] is False
    assert phone.apps["com.wlive.forecast"].enabled is False
    (o,) = api.history()["orders"]
    assert o["client"] == "Anna" and o["number"] == order["order"]


def test_admin_path_with_the_user_tapping_deactivate():
    phone = make_cli_phone()
    phone.on_admin_screen = lambda p: setattr(p.apps["com.clean.pro.boost"], "admin", False)
    phone, api, rec = _scanned(phone)
    api.execute({"com.clean.pro.boost": "remove"}, [])
    assert rec.of("exec:admin_wait")[0]["package"] == "com.clean.pro.boost"
    assert rec.of("exec:admin_done")[0]["status"] == "done"
    assert rec.of("exec:done")[0]["apps"][0]["outcome"] == "ok"
    assert phone.apps["com.clean.pro.boost"].installed is False


def test_admin_timeout_question_skip():
    _phone, api, rec = _scanned(sync=False, admin_timeout=0)
    job = api.execute({"com.clean.pro.boost": "disable"}, [])["job_id"]
    question = rec.wait_for("exec:question")
    assert question["job_id"] == job and question["kind"] == "admin_timeout"
    assert api.answer(job, "skip") == {"ok": True}
    done = rec.wait_for("exec:done")
    assert done["apps"][0]["outcome"] == "failed"
    assert any("administrator" in e for e in done["apps"][0]["errors"])


def test_stop_then_resume():
    phone = make_cli_phone()
    phone, api, rec = _scanned(phone)

    class StopAfterFirstDone(RecordingEmitter):
        def emit(self, name, detail=None):
            super().emit(name, detail)
            if name == "exec:step" and detail["status"] == "done":
                api.stop(api._jobs.current().id)

    stopper = StopAfterFirstDone()
    api._emitter = stopper
    api._jobs._emitter = stopper
    api.execute(WLIVE, [])
    number = stopper.of("exec:order")[0]["order"]
    assert stopper.of("exec:stopped") == [{"order": number}]
    assert stopper.of("exec:done")[0]["stopped"] is True
    assert phone.apps["com.wlive.forecast"].enabled
    assert api.history()["orders"][0]["interrupted"] is True

    api._emitter = rec
    api._jobs._emitter = rec
    api.resume(number)
    assert rec.of("exec:order")[-1] == {"order": number, "plan": None}
    assert rec.of("exec:done")[-1]["apps"][0]["outcome"] == "ok"
    assert phone.apps["com.wlive.forecast"].enabled is False
    assert api.resume(number)["error"]["key"] == "nothing_to_resume"


def test_disconnect_during_execute_then_resume():
    phone, api, rec = _scanned()
    phone.lose_response.add(DISABLE)
    api.execute(WLIVE, [])
    (lost,) = rec.of("exec:disconnected")
    assert "exec:done" not in rec.names()
    phone.lose_response.clear()
    phone.disconnected = False
    api.resume(lost["order"])
    assert rec.of("exec:done")[-1]["apps"][0]["outcome"] == "ok"
    assert phone.calls.count(DISABLE) == 1


def test_execute_during_apk_analysis_abandons_it():
    slow = SlowApk()
    phone = make_cli_phone()
    api, rec = make_api(phone, sync=False, apk=slow)
    api.start_scan(SERIAL)
    rec.wait_for("apk:progress")
    result = api.execute(WLIVE, [])
    assert "job_id" in result
    rec.wait_for("exec:done")
    slow.release.set()
    rec.wait_for("apk:stopped")
    assert "apk:done" not in rec.names()
    assert phone.apps["com.wlive.forecast"].enabled is False


def test_nothing_runnable_is_an_error():
    _, api, rec = _scanned()
    api.execute({"com.sec.android.app.launcher": "disable"}, [])
    assert rec.of("job:error")[0]["key"] == "nothing_to_do"


def test_undo_whole_order_and_single_action():
    phone, api, rec = _scanned()
    api.execute(WLIVE, [])
    number = rec.of("exec:order")[0]["order"]
    actions = api.history()["orders"][0]["actions"]
    enabled = next(a for a in actions if a["kind"] == "enabled")
    api.undo(number, enabled["id"], None)
    assert rec.of("undo:done")[-1]["status"] == "partially_undone"
    assert phone.apps["com.wlive.forecast"].enabled
    api.undo(number, None, None)
    done = rec.of("undo:done")[-1]
    assert done["status"] == "undone" and done["status_label"] == "cofnięte"
    assert done["admin_not_restored"] is False and done["errors"] == []
    assert {s["status"] for s in rec.of("undo:step")} == {"running", "undone"}
    assert api.undo("ZS/1999/0101/01")["error"]["key"] == "unknown_order"


def test_history_and_undo_with_another_phone_connected():
    phone, api, rec = _scanned()
    api.execute(WLIVE, [])
    number = rec.of("exec:order")[0]["order"]
    phone.host["devices -l"] = "List of devices attached\nOTHER1 device usb:1-2 model:X\n"
    fresh, _ = make_api(phone)
    history = fresh.history()
    assert history["serial"] == SERIAL and history["serials"] == [SERIAL]
    error = fresh.undo(number)["error"]
    assert error["key"] == "wrong_device" and error["serial"] == SERIAL
    assert error["device"] == fresh.history()["devices"][0]["name"] != SERIAL  # nazwa jak w historii
    assert phone.apps["com.wlive.forecast"].enabled is False
    assert fresh.history("NOPE")["orders"] == []


def test_execute_stores_the_snapshot_from_the_scan():
    _, api, rec = _scanned()
    api.execute(WLIVE, [])
    number = rec.of("exec:order")[0]["order"]
    with Journal(journal_path()) as j:
        order = j.order_by_number(number)
        snap = j.scan(order.id)
        assert snap["device"]["serial"] == SERIAL and snap["phone"]["confidence"] == "none"
        assert snap["app_count"] == len(api._report.results)
        assert j.verification(order.id) == {}


def test_finished_repair_clears_the_apk_cache_when_enabled():
    from admenot.engine.apk.fetch import default_cache_dir
    _, api, rec = _scanned()
    api.save_settings({"apk_cache_clear_after_repair": True})
    entry = default_cache_dir() / "com.old" / "id"
    entry.mkdir(parents=True)
    (entry / "base.apk").write_bytes(b"x")
    api.execute(WLIVE, [])
    assert rec.of("exec:done") and not entry.exists()


def test_stopped_repair_keeps_the_apk_cache():
    from admenot.engine.apk.fetch import default_cache_dir
    _, api, _ = _scanned()
    api.save_settings({"apk_cache_clear_after_repair": True})
    entry = default_cache_dir() / "com.old" / "id"
    entry.mkdir(parents=True)
    (entry / "base.apk").write_bytes(b"x")

    class StopAfterFirstDone(RecordingEmitter):  # jak w test_stop_then_resume
        def emit(self, name, detail=None):
            super().emit(name, detail)
            if name == "exec:step" and detail["status"] == "done":
                api.stop(api._jobs.current().id)

    stopper = StopAfterFirstDone()
    api._emitter = stopper
    api._jobs._emitter = stopper
    api.execute(WLIVE, [])
    assert stopper.of("exec:done")[0]["stopped"] is True
    assert entry.exists()


def test_failing_cache_clear_does_not_fail_a_finished_repair(monkeypatch):
    from admenot.engine import workflow

    def boom(cache_dir):
        raise OSError("locked")

    monkeypatch.setattr(workflow, "clear_cache", boom)
    _, api, rec = _scanned()
    api.save_settings({"apk_cache_clear_after_repair": True})
    api.execute(WLIVE, [])
    assert rec.of("exec:done") and rec.of("job:error") == []
