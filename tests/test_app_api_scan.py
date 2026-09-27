import pytest
from apphelpers import SlowApk, make_api, names
from conftest import SERIAL
from fakephone import make_cli_phone

from demalware.engine.actions.steps import Step
from demalware.engine.adb.transport import AdbError
from demalware.engine.journal.db import Journal
from demalware.engine.paths import journal_path


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("DEMALWARE_ASSETS", str(tmp_path / "no-assets"))


def test_settings_roundtrip_and_errors():
    paths = []
    phone = make_cli_phone()
    api, _ = make_api(phone)
    api._host_factory = lambda path: paths.append(path) or phone
    assert api.save_settings({"mode": "expert", "lang": "en"})["mode"] == "expert"
    assert api.get_settings()["lang"] == "en"
    assert api.save_settings({"lang": "de"})["error"]["key"] == "bad_request"
    api.save_settings({"adb_path": "C:\\adb\\adb.exe"})
    assert paths == ["C:\\adb\\adb.exe"]


def test_list_devices_and_adb_missing():
    phone = make_cli_phone()
    api, _ = make_api(phone)
    assert api.list_devices() == {"devices": [{"serial": SERIAL, "state": "device",
                                               "model": "SM_A145R"}], "error": None}
    phone.host["devices -l"] = AdbError("adb_missing", "adb not found")
    assert api.list_devices() == {"devices": [], "error": "adb_missing"}


def test_scan_events_in_order_then_apk_in_background():
    api, rec = make_api(make_cli_phone())
    assert api.rerender() == {"scan": None}
    assert api.start_scan(SERIAL, "  Anna K. ") == {"job_id": "job-1"}
    seq = names(rec)
    assert seq[:7] == ["scan:stage", "scan:device", "scan:stage", "scan:stage", "scan:stage",
                       "scan:done", "apk:progress"]
    assert seq[-2:] == ["apk:done", "job:end"]
    assert [d["stage"] for d in rec.of("scan:stage")] == ["identify", "packages", "collectors",
                                                           "score"]
    device = rec.of("scan:device")[0]["device"]
    assert device["serial"] == SERIAL and device["image"].startswith("data:image/svg+xml")
    done = rec.of("scan:done")[0]
    assert done["client"] == "Anna K." and done["interrupted"] == []
    assert any(a["package"] == "com.clean.pro.boost" for a in done["scan"]["apps"])
    assert rec.of("job:end") == [{"job_id": "job-1", "kind": "apk"}]
    commands = rec.of("adb:command")
    assert commands and all(c["serial"] == SERIAL for c in commands)
    assert api.rerender()["scan"]["apps"][0]["verdict_label"] == "Szkodliwa"
    api.save_settings({"lang": "en"})
    assert api.rerender()["scan"]["apps"][0]["verdict_label"] == "Malicious"


def test_scan_reports_interrupted_orders():
    with Journal(journal_path()) as j:
        order = j.create_order(SERIAL, "SM-A145R")
        step = Step("enabled", "com.wlive.forecast", {"enabled": "0"})
        j.add_action(order.id, "com.wlive.forecast", "disable", step.to_dict(), "pm disable-user")
    api, rec = make_api(make_cli_phone())
    api.start_scan(SERIAL)
    assert rec.of("scan:done")[0]["interrupted"] == [order.number]


def test_scan_of_a_disconnected_phone_is_a_job_error():
    phone = make_cli_phone()
    phone.disconnected = True
    api, rec = make_api(phone)
    api.start_scan(SERIAL)
    assert rec.of("job:error")[0]["key"] == "disconnected"
    assert api.rerender() == {"scan": None}
    assert api.start_scan("")["error"]["key"] == "bad_request"


def test_new_scan_abandons_the_running_apk_analysis():
    slow = SlowApk()
    api, rec = make_api(make_cli_phone(), sync=False, apk=slow)
    api.start_scan(SERIAL)
    rec.wait_for("apk:progress")
    second = api.start_scan(SERIAL)
    assert second == {"job_id": "job-2"}
    slow.release.set()
    rec.wait_for("apk:done")
    rec.wait_for("apk:stopped")
    assert len(rec.of("apk:done")) == 1
