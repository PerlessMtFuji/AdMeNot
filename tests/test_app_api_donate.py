import pytest
from apphelpers import make_api
from conftest import SERIAL
from fakephone import make_cli_phone

from admenot.app.events import RecordingEmitter
from admenot.engine.settings import load_settings, save_internal

WLIVE = {"com.wlive.forecast": "disable"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))


def _scanned(**kw):
    api, rec = make_api(make_cli_phone(), **kw)
    api.start_scan(SERIAL, "Anna")
    rec.wait_for("apk:done")
    assert api._jobs.wait(5)
    rec.events.clear()
    return api, rec


def test_first_successful_order_brings_the_reminder():
    api, rec = _scanned()
    api.execute(WLIVE, [])
    assert rec.of("exec:done")[0]["donate_reminder"] is True
    s = load_settings()
    assert (s.donate_count, s.donate_shown_at) == (0, "2026-09-26")  # NOW z conftest


def test_reminder_waits_after_a_recent_one():
    save_internal({"donate_shown_at": "2026-09-20"})
    api, rec = _scanned()
    api.execute(WLIVE, [])
    assert rec.of("exec:done")[0]["donate_reminder"] is False
    assert load_settings().donate_count == 1


def test_failed_order_does_not_count():
    api, rec = _scanned(sync=False, admin_timeout=0)
    job = api.execute({"com.clean.pro.boost": "disable"}, [])["job_id"]
    rec.wait_for("exec:question")
    api.answer(job, "skip")
    assert rec.wait_for("exec:done")["donate_reminder"] is False
    assert api._jobs.wait(5)
    assert load_settings().donate_count == 0


def test_stopped_order_does_not_count_and_finished_resume_does():
    api, rec = _scanned()

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
    assert stopper.of("exec:done")[0]["donate_reminder"] is False
    assert load_settings().donate_count == 0

    api._emitter = rec
    api._jobs._emitter = rec
    api.resume(number)
    assert rec.of("exec:done")[-1]["donate_reminder"] is True


def test_donate_page_and_reminder_switch():
    opened = []
    api, _ = make_api(make_cli_phone(), open_url=opened.append)
    assert api.get_settings()["donate_reminders"] is True
    assert api.open_donate() == {"ok": True}
    assert opened == ["https://admenot.e-wlodarski.workers.dev/pl/donate"]
    view = api.set_donate_reminders(False)
    assert view["donate_reminders"] is False and load_settings().donate_off is True
    assert api.set_donate_reminders(True)["donate_reminders"] is True
    assert api.set_donate_reminders("nie")["error"]["key"] == "bad_request"
