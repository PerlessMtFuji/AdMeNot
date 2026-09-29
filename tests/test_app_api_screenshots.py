import pytest
from apphelpers import make_api
from conftest import SERIAL
from fakephone import make_cli_phone

from demalware.engine import paths
from demalware.engine.foreground import ACTIVITIES, WINDOWS
from demalware.engine.journal.db import Journal

AD = "  topResumedActivity=ActivityRecord{1 u0 com.clean.pro.boost/.Ad t1}\n"


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("DEMALWARE_ASSETS", str(tmp_path / "no-assets"))
    return tmp_path


def _phone():
    phone = make_cli_phone()
    phone.static[ACTIVITIES] = AD
    phone.static[WINDOWS] = ""
    return phone


def _scan(api, rec, serial=SERIAL):
    api.start_scan(serial)
    rec.wait_for("apk:done")
    rec.events.clear()


def _order(api, rec):
    api.execute({"com.wlive.forecast": "disable"}, [])
    return rec.wait_for("exec:done")["order"]


def test_screenshot_before_any_scan_waits_for_the_order():
    phone = _phone()
    api, rec = make_api(phone)
    result = api.screenshot(SERIAL)
    shot = result["shot"]
    assert result["count"] == 1
    assert shot["caption"] == "Na pierwszym planie: com.clean.pro.boost"
    assert shot["in_report"] is True and shot["black"] is False
    assert shot["image"].startswith("data:image/jpeg;base64,")
    assert shot["taken_at"] == "2026-09-26T14:30:00"
    commands = [e["command"] for e in rec.of("adb:command") if e["tag"] == "shot"]
    assert "host:exec-out screencap -p" in commands
    _scan(api, rec)
    number = _order(api, rec)
    listed = api.screenshots(number)
    assert listed["limit"] == 8 and [i["id"] for i in listed["items"]] == [shot["id"]]


def test_screenshot_after_the_order_goes_straight_to_it_and_uses_scan_names():
    api, rec = make_api(_phone())
    _scan(api, rec)
    number = _order(api, rec)
    result = api.screenshot(SERIAL)
    assert result["count"] == 1
    assert [i["id"] for i in api.screenshots(number)["items"]] == [result["shot"]["id"]]


def test_new_scan_closes_the_order_for_new_shots():
    api, rec = make_api(_phone())
    _scan(api, rec)
    number = _order(api, rec)
    _scan(api, rec)
    api.screenshot(SERIAL)
    assert api.screenshots(number)["items"] == []


def test_pending_shots_attach_only_to_their_phone():
    phone = _phone()
    api, rec = make_api(phone)
    api.screenshot("OTHER-PHONE")  # FakePhone odpowiada dla każdego numeru; zrzut czeka dla OTHER
    _scan(api, rec)
    number = _order(api, rec)
    assert api.screenshots(number)["items"] == []
    with Journal(paths.journal_path()) as journal:
        assert len(journal.orphan_screenshots()) == 1


def test_screenshot_works_during_an_order():
    api, rec = make_api(_phone(), sync=False, admin_timeout=0)
    _scan(api, rec)
    job = api.execute({"com.clean.pro.boost": "disable"}, [])["job_id"]
    rec.wait_for("exec:question")
    result = api.screenshot(SERIAL)
    assert "error" not in result
    api.answer(job, "skip")
    number = rec.wait_for("exec:done")["order"]
    assert [i["id"] for i in api.screenshots(number)["items"]] == [result["shot"]["id"]]


def test_in_report_toggle_and_limit():
    api, rec = make_api(_phone())
    _scan(api, rec)
    number = _order(api, rec)
    shots = [api.screenshot(SERIAL)["shot"] for _ in range(9)]
    assert [s["in_report"] for s in shots] == [True] * 8 + [False]
    assert api.set_screenshot_in_report(shots[8]["id"], True)["error"]["key"] == "shot_limit"
    assert api.set_screenshot_in_report(shots[0]["id"], False)["in_report"] is False
    assert api.set_screenshot_in_report(shots[8]["id"], True)["in_report"] is True
    assert api.set_screenshot_in_report(999, True)["error"]["key"] == "unknown_screenshot"
    assert api.set_screenshot_in_report("1", True)["error"]["key"] == "bad_request"
    assert api.screenshots("ZS/none")["error"]["key"] == "unknown_order"
    assert api.screenshot(" ")["error"]["key"] == "bad_request"
    history = api.history(SERIAL)
    assert history["orders"][0]["screenshots"] == 9 and history["orders"][0]["number"] == number


def test_orphans_from_a_previous_run_are_deleted_at_start():
    api, _rec = make_api(_phone())
    shot_id = api.screenshot(SERIAL)["shot"]["id"]
    png, jpg = paths.screenshot_files(shot_id)
    assert png.is_file() and jpg.is_file()
    make_api(_phone())  # następne uruchomienie programu
    assert not png.exists() and not jpg.exists()
    with Journal(paths.journal_path()) as journal:
        assert journal.orphan_screenshots() == []


def test_disconnected_phone_is_an_error_without_a_file():
    phone = _phone()
    phone.disconnected = True
    api, _rec = make_api(phone)
    assert api.screenshot(SERIAL)["error"]["key"] == "disconnected"
    assert not paths.screenshots_dir().exists() or not any(paths.screenshots_dir().iterdir())
