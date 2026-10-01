from collections import namedtuple

import pytest
from apphelpers import SlowApk, make_api, names
from conftest import SERIAL
from fakephone import make_cli_phone

from demalware.engine.actions.steps import Step
from demalware.engine.adb.transport import AdbError
from demalware.engine.apk import cache as C
from demalware.engine.apk.analyze import ApkReport
from demalware.engine.apk.fetch import FetchedApks, default_cache_dir
from demalware.engine.apk.providers import DeviceApkProvider
from demalware.engine.journal.db import Journal
from demalware.engine.paths import journal_path

Disk = namedtuple("Disk", "total used free")


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


def _fake_fetch(cache_dir, package):
    """Pobranie bez telefonu: 1 bajt we wpisie `<pakiet>/id`, jak gotowy wpis `fetch_apks`."""
    entry = cache_dir / package / "id"
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "base.apk").write_bytes(b"x")
    return FetchedApks([entry / "base.apk"], verified=True)


def _policy_factory(policies):
    """Prawdziwy `DeviceApkProvider` z polityką od `Api`; `stat` podaje 1 GB na każdy cel."""
    def factory(adb, policy=None):
        policies.append(policy)
        real = adb.shell

        def shell(command, timeout=20.0):
            if command.startswith("stat -c"):
                paths = [a.strip("'") for a in command.split() if a.endswith(".apk'") or
                         (a.endswith(".apk") and "*" not in a)]
                return "".join(f"{C.GB} {path}\n" for path in paths)
            return real(command, timeout)

        adb.shell = shell
        return DeviceApkProvider(adb, cache_dir=default_cache_dir(), workers=1,
                                 fetch=lambda a, package, d: _fake_fetch(d, package),
                                 analyze=lambda package, paths: ApkReport(package, class_count=1),
                                 policy=policy)
    return factory


def _policy_api(monkeypatch, free, sync=True):
    monkeypatch.setattr(C, "disk_usage", lambda path: Disk(500 * C.GB, 0, free))
    api, rec = make_api(make_cli_phone(), sync=sync)
    policies = []
    api._apk_factory = _policy_factory(policies)
    return api, rec, policies


def test_estimate_event_before_apk_progress_and_limit_from_settings(monkeypatch):
    api, rec, policies = _policy_api(monkeypatch, free=500 * C.GB)
    api.start_scan(SERIAL)
    seq = names(rec)
    assert seq.index("apk:estimate") < seq.index("apk:progress")
    est = rec.of("apk:estimate")[0]
    assert est["limit_bytes"] == 10 * C.GB and est["apps"] >= 1 and est["to_fetch_bytes"] >= C.GB
    assert policies[0].limit_bytes == 10 * C.GB
    assert rec.of("apk:question") == []


def test_space_question_skip_marks_all_apps(monkeypatch):
    api, rec, _ = _policy_api(monkeypatch, free=C.RESERVE + C.GB, sync=False)
    api.start_scan(SERIAL)
    question = rec.wait_for("apk:question")
    assert question["kind"] == "no_space" and question["largest_bytes"] == 2 * C.GB
    api.answer(question["job_id"], "skip")
    scan = rec.wait_for("apk:done")["scan"]
    assert scan["apk"]["stopped_no_space"] is True and scan["apk"]["analyzed"] == 0


def test_stopping_during_the_space_question_skips_the_analysis(monkeypatch):
    api, rec, _ = _policy_api(monkeypatch, free=C.RESERVE + C.GB, sync=False)
    api.start_scan(SERIAL)
    question = rec.wait_for("apk:question")
    api.stop(question["job_id"])  # `job.ask` zwraca None → pominięcie, potem `job.check` kończy
    rec.wait_for("apk:stopped")
    assert rec.of("apk:done") == []
    assert C.cache_size(default_cache_dir()) == 0


def test_apk_cache_status_and_clear(monkeypatch):
    monkeypatch.setattr(C, "disk_usage", lambda path: Disk(120 * C.GB, 0, 4 * C.GB))
    api, _ = make_api(make_cli_phone())
    _fake_fetch(default_cache_dir(), "com.a")
    status = api.apk_cache()
    assert status["size_bytes"] == 1 and status["limit_bytes"] == 10 * C.GB
    assert status["effective_bytes"] == 2 * C.GB + 1
    assert status["path"] == str(default_cache_dir())
    assert api.clear_apk_cache() == {"freed_bytes": 1}


def test_clear_apk_cache_is_refused_while_a_job_runs():
    slow = SlowApk()
    api, rec = make_api(make_cli_phone(), sync=False, apk=slow)
    api.start_scan(SERIAL)
    rec.wait_for("apk:progress")
    assert api.clear_apk_cache()["error"]["key"] == "busy"
    slow.release.set()
    rec.wait_for("apk:done")


def test_cache_limit_above_the_disk_is_refused(monkeypatch):
    monkeypatch.setattr(C, "disk_usage", lambda path: Disk(120 * C.GB, 0, 4 * C.GB))
    api, _ = make_api(make_cli_phone())
    assert api.save_settings({"apk_cache_limit_gb": 121})["error"]["key"] == "bad_request"
    assert api.save_settings({"apk_cache_limit_gb": 120})["apk_cache_limit_gb"] == 120
    assert api.save_settings({"apk_cache_limit_gb": 0})["error"]["key"] == "bad_request"


def test_limit_check_is_skipped_when_the_disk_size_is_unknown(monkeypatch):
    def broken(path):
        raise OSError("no disk")

    monkeypatch.setattr(C, "disk_usage", broken)
    api, _ = make_api(make_cli_phone())
    assert api.save_settings({"apk_cache_limit_gb": 500})["apk_cache_limit_gb"] == 500
