import pytest
from apphelpers import make_api
from fakephone import make_cli_phone

from admenot.app import crash
from admenot.app.errors import report_error
from admenot.app.events import RecordingEmitter
from admenot.app.jobs import JobRunner
from admenot.net import client


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))
    crash.reset_session()
    yield
    crash.reset_session()


def api():
    def offline():
        raise client.BackendError("offline")

    return make_api(make_cli_phone(), update_fetch=offline)[0]


def test_internal_error_gets_a_crash_id_and_known_errors_do_not():
    payload = report_error(RuntimeError("x"), {"call": "rerender"})
    assert payload["key"] == "internal" and payload["crash"]
    assert crash.list_reports()[0]["id"] == payload["crash"]
    assert "crash" not in report_error(ValueError("bad"))
    assert len(crash.list_reports()) == 1


def test_api_wrapper_passes_method_name(monkeypatch):
    a = api()
    monkeypatch.setattr("admenot.app.api.history_view", lambda *x, **k: 1 / 0)
    err = a.history(None)["error"]
    data = crash.preview(err["crash"], False, None)["body"]
    assert data["context"]["call"] == "history" and data["error"]["type"] == "ZeroDivisionError"


def test_job_error_context_is_the_job_kind():
    rec = RecordingEmitter()
    runner = JobRunner(rec, sync=True)
    runner.start("exec", lambda job: 1 / 0)
    detail = next(d for n, d in rec.events if n == "job:error")
    assert crash.preview(detail["crash"], False, None)["body"]["context"]["job"] == "exec"


def test_ui_errors_are_deduplicated():
    a = api()
    first = a.capture_ui_error("TypeError: x is undefined", "at f (app.js:1:2)", "results")["crash"]
    second = a.capture_ui_error("TypeError: x is undefined", "at f (app.js:1:2)", "results")["crash"]
    assert first == second
    body = a.crash_preview(first)["body"]
    assert body["kind"] == "ui" and body["count"] == 2 and body["context"]["screen"] == "results"
    assert a.capture_ui_error(42)["error"]["key"] == "bad_request"


def test_reports_list_and_startup():
    a = api()
    crash.capture(type_="RuntimeError", message="x", kind="thread")
    view = a.crash_reports()
    assert len(view["reports"]) == 1 and view["startup"] == [view["reports"][0]["id"]]
    assert a.crash_reports()["startup"] == []


def test_send_maps_errors(monkeypatch):
    a = api()
    crash_id = a.capture_ui_error("boom")["crash"]
    responses = iter([client.BackendError("offline"), client.BackendError("http", 429),
                      client.BackendError("http", 503), client.BackendError("http", 400),
                      client.BackendError("invalid"), {"id": "R-7K3Q9M"}])

    def post(path, body):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(client, "post_json", post)
    keys = [a.send_crash(crash_id)["error"]["key"] for _ in range(5)]
    assert keys == ["crash_offline", "crash_offline", "crash_offline", "crash_rejected", "crash_rejected"]
    assert a.send_crash(crash_id, True, "opis") == {"sent_id": "R-7K3Q9M"}
    assert a.crash_reports()["reports"][0]["sent_id"] == "R-7K3Q9M"


def test_unknown_and_bad_arguments():
    a = api()
    assert a.crash_preview("20261009-140312-abcd")["error"]["key"] == "unknown_crash"
    assert a.discard_crash("../x")["error"]["key"] == "unknown_crash"
    crash_id = a.capture_ui_error("boom")["crash"]
    assert a.crash_preview(crash_id, False, 5)["error"]["key"] == "bad_request"
    assert a.discard_crash(crash_id) == {} and a.crash_reports()["reports"] == []


def test_scan_notes_device_and_serials(monkeypatch):
    a = api()
    a.list_devices()
    a.start_scan("R58T00TEST")
    crash_id = a.capture_ui_error("after scan R58T00TEST")["crash"]
    body = a.crash_preview(crash_id)["body"]
    assert body["context"]["device"] == {"manufacturer": "samsung", "model": "SM-A145R", "android": "14"}
    assert "R58T00TEST" not in body["error"]["message"]


def test_crash_test_variable_breaks_the_scan(monkeypatch):
    monkeypatch.setenv(crash.CRASH_TEST, "error")
    a, rec = make_api(make_cli_phone(), update_fetch=lambda: (_ for _ in ()).throw(client.BackendError("offline")))
    a.start_scan("R58T00TEST")
    detail = next(d for n, d in rec.events if n == "job:error")
    assert detail["key"] == "internal" and detail["crash"]
