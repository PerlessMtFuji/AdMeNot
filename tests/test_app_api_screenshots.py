import pytest
from apphelpers import make_api
from conftest import SERIAL
from fakephone import make_cli_phone

import admenot.app.api as api_module
from admenot.engine import paths
from admenot.engine.foreground import ACTIVITIES, WINDOWS
from admenot.engine.journal.db import Journal
from admenot.engine.screenshot import take_screenshot as real_take_screenshot

AD = "  topResumedActivity=ActivityRecord{1 u0 com.clean.pro.boost/.Ad t1}\n"


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))
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


def test_leaving_the_order_makes_new_shots_wait_for_the_next_one():
    # „Nowe skanowanie” wraca na ekran Połącz: zrzut „przed skanem” należy do następnej sprawy
    # (próba 2026-09-30 na OPPO — trafiał do poprzedniego zlecenia).
    api, rec = make_api(_phone())
    _scan(api, rec)
    first = _order(api, rec)
    assert api.close_order(SERIAL) == {"ok": True}
    shot = api.screenshot(SERIAL)["shot"]
    assert api.screenshots(first)["items"] == []
    _scan(api, rec)
    second = _order(api, rec)
    assert [i["id"] for i in api.screenshots(second)["items"]] == [shot["id"]]


def test_close_order_rejects_a_bad_serial():
    api, _ = make_api(_phone())
    assert api.close_order("  ")["error"]["key"] == "bad_request"


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


def test_screenshot_started_before_the_order_still_joins_it(monkeypatch):
    """Fix round 1 (review): screenshot() reads `_open_order` before the slow screencap, so a job
    thread can create the order and call `_bind_order` while the screenshot is still in flight —
    without the fix the shot stays orphaned (order_id NULL) instead of joining that order."""
    api, _rec = make_api(_phone())
    opened = {}

    def fake_take_screenshot(adb, journal, serial, names, order_id):
        shot = real_take_screenshot(adb, journal, serial, names, order_id)
        # Simuluje wątek zadania, który w tym momencie otwiera zlecenie i wywołuje _bind_order —
        # zanim ten wątek mostu wróci do sprawdzenia _open_order po zrzucie.
        order = journal.create_order(serial, "SM-A145R")
        api._bind_order(journal, serial, order.id)
        opened["number"] = order.number
        return shot

    monkeypatch.setattr(api_module, "take_screenshot", fake_take_screenshot)
    result = api.screenshot(SERIAL)

    assert [i["id"] for i in api.screenshots(opened["number"])["items"]] == [result["shot"]["id"]]
    with Journal(paths.journal_path()) as journal:
        assert journal.orphan_screenshots() == []


def test_pending_shot_count_excludes_shots_off_and_caps_at_the_limit():
    api, _rec = make_api(_phone())
    results = [api.screenshot(SERIAL) for _ in range(3)]
    assert [r["count"] for r in results] == [1, 2, 3]
    api.set_screenshot_in_report(results[0]["shot"]["id"], False)
    fourth = api.screenshot(SERIAL)
    assert fourth["count"] == 3  # 4 czekające, jeden odznaczony: tylko 3 trafią do protokołu
    for _ in range(5):
        last = api.screenshot(SERIAL)
    assert last["count"] == 8  # 9 czekających, jeden odznaczony (8 zaznaczonych) — limit i tak 8
