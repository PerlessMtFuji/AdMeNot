import json
import re

import pytest
from apphelpers import make_api
from conftest import SERIAL
from fakephone import make_cli_phone

from admenot.engine import welcome
from admenot.engine.paths import telemetry_path

WLIVE = {"com.wlive.forecast": "disable"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))


def events():
    path = telemetry_path()
    return [json.loads(x) for x in path.read_text("utf-8").splitlines()] if path.exists() else []


def scanned(api, rec):
    api.start_scan(SERIAL, "Anna")
    rec.wait_for("apk:done")
    assert api._jobs.wait(5)


def test_settings_view_has_welcome_and_delete_state():
    api, _ = make_api(make_cli_phone())
    view = api.get_settings()
    assert view["welcome_version"] is None and view["welcome_current"] == welcome.WELCOME_VERSION
    assert view["telemetry"] is False and view["telemetry_delete_pending"] is False


def test_accept_welcome_stores_risk_and_consent():
    api, _ = make_api(make_cli_phone())
    view = api.accept_welcome(True, True)
    assert view["welcome_version"] == welcome.WELCOME_VERSION
    assert view["telemetry"] and view["telemetry_packages"]
    assert re.match(r"^[0-9a-f-]{36}$", view["telemetry_id"])


def test_accept_welcome_rejects_non_bool():
    api, _ = make_api(make_cli_phone())
    assert api.accept_welcome("yes", False)["error"]["key"] == "bad_request"
    assert api.set_telemetry(True, None)["error"]["key"] == "bad_request"


def test_accept_welcome_with_newer_settings_is_an_error(tmp_path):
    api, _ = make_api(make_cli_phone())
    path = tmp_path / "data" / "AdMeNot" / "settings.json"
    data = json.loads(path.read_text("utf-8"))
    path.write_text(json.dumps({**data, "schema": 99}), "utf-8")
    assert api.accept_welcome(False, False)["error"]["key"] == "data_too_new"
    assert api.get_settings()["welcome_version"] is None


def test_no_consent_no_events_after_scan_and_repair():
    api, rec = make_api(make_cli_phone())
    scanned(api, rec)
    api.execute(WLIVE, [])
    assert api._jobs.wait(5)
    assert not telemetry_path().exists()


def test_scan_repair_undo_events_with_consent():
    api, rec = make_api(make_cli_phone())
    api.set_telemetry(True, False)
    scanned(api, rec)
    api.execute(WLIVE, [])
    rec.wait_for("exec:done")
    assert api._jobs.wait(5)
    order = rec.wait_for("exec:order")["order"]
    api.undo(order)
    rec.wait_for("undo:done")
    assert api._jobs.wait(5)
    types = [e["type"] for e in events()]
    assert types == ["start", "scan", "scan", "repair", "undo"]  # zgoda, skan + ponowna ocena po APK
    _, scan, apk_scan, repair, undo = events()
    assert apk_scan["apk_stage"] is True and scan["session"] == repair["session"]
    assert repair["levels"]["disable"] == 1 and repair["packages"] is None
    assert undo["apps"] == 1 and undo["failed"] == 0
    text = json.dumps(events())
    assert SERIAL not in text and "Anna" not in text and order not in text


def test_packages_only_with_second_consent():
    api, rec = make_api(make_cli_phone())
    api.set_telemetry(True, True)
    scanned(api, rec)
    api.execute(WLIVE, [])
    rec.wait_for("exec:done")
    assert api._jobs.wait(5)
    repair = events()[-1]
    assert repair["packages"][0]["package"] == "com.wlive.forecast"


def test_withdraw_marks_delete_pending():
    api, _ = make_api(make_cli_phone())
    api.set_telemetry(True, False)
    view = api.set_telemetry(False, False)
    assert view["telemetry_id"] is None and view["telemetry_delete_pending"] is True


def test_sample_and_privacy_link():
    opened = []
    api, _ = make_api(make_cli_phone(), open_url=opened.append)
    sample = api.telemetry_sample()
    assert {e["type"] for e in sample["basic"]} == {"start", "scan", "repair", "undo"}
    api.open_privacy()
    assert opened == ["https://admenot.e-wlodarski.workers.dev/pl/privacy"]


def test_consent_records_start_for_today():
    # Zgoda dana na ekranie powitalnym: „start” z tego dnia, a nie dopiero przy następnym uruchomieniu.
    api, _ = make_api(make_cli_phone())
    api.accept_welcome(True, False)
    api.set_telemetry(True, True)  # przełączenie w tym samym dniu nie dubluje zdarzenia
    assert [e["type"] for e in events()] == ["start"]


def test_finished_deletion_reaches_the_ui(monkeypatch):
    from admenot.app import telemetry

    api, rec = make_api(make_cli_phone())
    started = {}
    monkeypatch.setattr(telemetry, "start", lambda on_deleted=None: started.update(cb=on_deleted))
    api._start_telemetry()
    started["cb"]()  # wątek wysyłki: lista ID do usunięcia właśnie opustoszała
    assert rec.wait_for("telemetry:deleted") == {}
