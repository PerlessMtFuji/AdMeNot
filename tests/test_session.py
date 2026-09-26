import json

from demalware.engine.adb.transport import AdbError
from demalware.engine.collectors.behavior import USAGESTATS
from demalware.engine.device.info import UPTIME
from demalware.engine.session import report_to_dict, run_scan


def _by_pkg(report):
    return {r.facts.package: r for r in report.results}


def test_synthetic_phone_verdicts(synthetic_adb):
    report = run_scan(synthetic_adb)
    assert all(s.ok for s in report.collectors.values()), report.collectors
    assert report.low_behavior_data is False
    results = _by_pkg(report)

    adware = results["com.clean.pro.boost"]
    assert adware.verdict == "malicious" and adware.score == 100
    assert {"DM-ADMIN-01", "DM-OVERLAY-01", "DM-HIDDEN-01", "DM-COMBO-01"} <= {
        f.rule_id for f in adware.findings}

    weather = results["com.wlive.forecast"]
    assert (weather.verdict, weather.score) == ("review", 25)
    assert [f.rule_id for f in weather.findings] == ["DM-NOTIF-02"]

    assert results["com.whatsapp"].verdict == "safe" and results["com.whatsapp"].trusted
    assert results["com.sec.android.app.launcher"].verdict == "safe"

    assert report.results[0].facts.package == "com.clean.pro.boost"  # sortowanie malejąco


def test_low_uptime_sets_low_behavior_data(synthetic_adb):
    synthetic_adb.responses[UPTIME] = "3600.00 7000.00\n"
    report = run_scan(synthetic_adb)
    assert report.low_behavior_data is True
    assert _by_pkg(report)["com.wlive.forecast"].incomplete is True


def test_failed_usagestats_sets_low_data_and_keeps_scanning(synthetic_adb):
    synthetic_adb.responses[USAGESTATS] = AdbError("timeout", "slow")
    report = run_scan(synthetic_adb)
    assert report.collectors["usagestats"].ok is False
    assert report.low_behavior_data is True
    assert _by_pkg(report)["com.clean.pro.boost"].verdict == "malicious"


def test_report_to_dict_is_json_serializable(synthetic_adb):
    data = report_to_dict(run_scan(synthetic_adb), lang="en")
    text = json.dumps(data, default=str)
    assert data["device"]["model"] == "SM-A145R"
    first = data["results"][0]
    assert first["package"] == "com.clean.pro.boost"
    assert first["verdict"] == "malicious"
    assert any("administrator" in f["text"] for f in first["findings"])
    assert "Anna: hej" not in text  # treść powiadomień nie trafia do wyników
