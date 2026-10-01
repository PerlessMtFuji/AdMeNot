import json

from demalware.engine.adb.transport import AdbError
from demalware.engine.allowlist.trust import parse_trust_list
from demalware.engine.apk.analyze import ApkReport, report_to_json
from demalware.engine.apk.providers import StoredApkProvider
from demalware.engine.collectors.behavior import USAGESTATS
from demalware.engine.collectors.profiles import PM_USERS, ProfileScope
from demalware.engine.collectors.system import DEVICE_POLICY
from demalware.engine.device.info import UPTIME, read_device_info
from demalware.engine.session import SCAN_STAGES, analyze_apks, report_to_dict, run_scan


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

    assert results["com.whatsapp"].verdict == "safe" and not results["com.whatsapp"].trusted
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
    boost = _by_pkg(report)["com.clean.pro.boost"]
    # score wciąż wysoki, ale niepełne dane obniżają pewność — "Szkodliwa" wymaga wysokiej pewności
    assert boost.score == 100 and boost.verdict == "suspicious" and boost.confidence != "high"


def test_failed_collector_makes_every_app_incomplete_including_trusted(synthetic_adb):
    synthetic_adb.responses[DEVICE_POLICY] = AdbError("timeout", "slow")
    report = run_scan(synthetic_adb)
    assert report.low_behavior_data is False  # device_policy to nie zachowanie
    assert all(r.incomplete and "device_policy" in r.facts.gaps for r in report.results)
    assert report_to_dict(report)["results"][0]["gaps"] == ["device_policy"]


def test_report_to_dict_is_json_serializable(synthetic_adb):
    data = report_to_dict(run_scan(synthetic_adb), lang="en")
    text = json.dumps(data, default=str)
    assert data["device"]["model"] == "SM-A145R"
    first = data["results"][0]
    assert first["package"] == "com.clean.pro.boost"
    assert first["verdict"] == "malicious"
    assert any("administrator" in f["text"] for f in first["findings"])
    assert "Anna: hej" not in text  # treść powiadomień nie trafia do wyników


class _RecordingProvider:
    def __init__(self, reports):
        self.reports = reports
        self.asked = []

    def reports_for(self, apps, progress=None, flagged=frozenset()):
        self.asked = [f.package for f in apps]
        return {p: r for p, r in self.reports.items() if p in self.asked}


SIX_SDKS = ["admob", "applovin", "meta", "mintegral", "pangle", "vungle"]


def test_apk_analysis_rescores_targets(synthetic_adb):
    provider = _RecordingProvider({"com.wlive.forecast": ApkReport(
        "com.wlive.forecast", 31, label="Weather Live", ad_sdks=SIX_SDKS, class_count=500)})
    report = run_scan(synthetic_adb, apk=provider)
    # wszystkie aplikacje użytkownika trafiają do analizy APK — zaufanie wymaga certyfikatu z pliku
    assert provider.asked == ["com.clean.pro.boost", "com.wlive.forecast", "com.whatsapp"]
    weather = _by_pkg(report)["com.wlive.forecast"]
    assert weather.facts.label == "Weather Live"
    assert {"DM-NOTIF-02", "DM-ADSDK-02", "DM-COMBO-03"} <= {f.rule_id for f in weather.findings}
    assert (weather.score, weather.verdict) == (65, "suspicious")
    assert report.apk.requested == 3 and report.apk.analyzed == 1 and report.apk.failed == {}


def test_apk_failures_are_reported_not_fatal(synthetic_adb):
    provider = _RecordingProvider({"com.clean.pro.boost": ApkReport("com.clean.pro.boost",
                                                                    error="timeout")})
    report = run_scan(synthetic_adb, apk=provider)
    assert report.apk.failed == {"com.clean.pro.boost": "timeout"}
    boost = _by_pkg(report)["com.clean.pro.boost"]
    # brakująca analiza APK to luka w danych ("apk" w gaps) — ocena niepełna, więc niższa pewność
    assert boost.score == 100 and boost.verdict == "suspicious" and boost.incomplete is True


def test_scan_without_apk_has_no_apk_status(synthetic_adb):
    assert run_scan(synthetic_adb).apk is None


def test_stored_provider_roundtrip_and_json(synthetic_adb, tmp_path):
    (tmp_path / "com.wlive.forecast.json").write_text(json.dumps(report_to_json(ApkReport(
        "com.wlive.forecast", label="Weather Live", ad_sdks=SIX_SDKS, class_count=500))))
    report = run_scan(synthetic_adb, apk=StoredApkProvider(tmp_path))
    data = json.loads(json.dumps(report_to_dict(report), default=str))
    weather = next(r for r in data["results"] if r["package"] == "com.wlive.forecast")
    assert weather["label"] == "Weather Live" and weather["ad_sdks"] == SIX_SDKS
    # wszystkie aplikacje użytkownika (bez systemowego launchera): boost, whatsapp, forecast
    assert data["apk"]["requested"] == 3


def test_synthetic_adware_wakes_phone(synthetic_adb):
    adware = _by_pkg(run_scan(synthetic_adb))["com.clean.pro.boost"]
    assert "DM-ALARM-01" in {f.rule_id for f in adware.findings}


class _OneReport:
    def __init__(self, reports):
        self.reports = reports

    def reports_for(self, apps, progress=None, flagged=frozenset()):
        for i, facts in enumerate(apps, start=1):
            if progress:
                progress(i, len(apps), facts.package)
        return {p: r for p, r in self.reports.items() if p in {a.package for a in apps}}


def test_short_usage_history_is_low_data_and_reported(synthetic_adb):
    now = "2026-09-26 14:00:00"
    synthetic_adb.responses[USAGESTATS] = (
        'user=0\n  In-memory daily stats\n    events\n'
        f'      time="2026-09-26 12:30:00" type=SCREEN_INTERACTIVE package=android\n'
        f'      time="{now}" type=ACTIVITY_RESUMED package=com.whatsapp\n')
    report = run_scan(synthetic_adb)
    assert report.usage_window_h == 1.5
    assert report.low_behavior_data is True
    assert all(r.incomplete for r in report.results)


def test_apk_step_keeps_usage_window(synthetic_adb, tmp_path):
    report = run_scan(synthetic_adb)
    assert analyze_apks(report, StoredApkProvider(tmp_path)).usage_window_h == report.usage_window_h


def test_run_scan_reports_stages_and_reuses_device(synthetic_adb):
    stages = []
    run_scan(synthetic_adb, on_stage=stages.append)
    assert stages == list(SCAN_STAGES)
    device = read_device_info(synthetic_adb)
    synthetic_adb.calls.clear()
    stages.clear()
    report = run_scan(synthetic_adb, device=device, on_stage=stages.append)
    assert stages == ["packages", "collectors", "score"]
    assert "getprop" not in synthetic_adb.calls and report.device == device


def test_analyze_apks_rescores_without_touching_the_first_report(synthetic_adb):
    report = run_scan(synthetic_adb)
    before = {r.facts.package: r.score for r in report.results}
    provider = _OneReport({"com.wlive.forecast": ApkReport(
        "com.wlive.forecast", 31, class_count=100, ad_sdks=["s1", "s2", "s3", "s4", "s5"])})
    progress = []
    after = analyze_apks(report, provider, lambda d, t, p: progress.append(p))
    assert after.apk is not None and after.apk.analyzed == 1
    assert "com.wlive.forecast" in progress
    scores = {r.facts.package: r.score for r in after.results}
    assert scores["com.wlive.forecast"] > before["com.wlive.forecast"]
    assert report.apk is None


def test_trust_comes_from_the_signer_seen_in_the_apk(synthetic_adb, tmp_path):
    trust = parse_trust_list(f"trusted:\n  - package: com.whatsapp\n    signers: ['{'a1' * 32}']\n")
    (tmp_path / "com.whatsapp.json").write_text(json.dumps(report_to_json(
        ApkReport("com.whatsapp", version_code=242000, class_count=5, cert_sha256=["a1" * 32]))))
    report = run_scan(synthetic_adb, trust=trust, apk=StoredApkProvider(tmp_path))
    assert _by_pkg(report)["com.whatsapp"].trusted


def test_other_profiles_are_reported_as_not_scanned(synthetic_adb):
    synthetic_adb.responses[PM_USERS] = "Users:\n\tUserInfo{0:A:c13} running\n\tUserInfo{10:W:1030}\n"
    report = run_scan(synthetic_adb)
    assert report.profiles == ProfileScope(scanned=(0,), present=(0, 10))
    assert report.profiles.others == (10,)


def test_missing_user_list_is_unknown_not_fatal(synthetic_adb):
    report = run_scan(synthetic_adb)  # nagrania sprzed Planu 4b nie mają `pm list users`
    assert report.profiles == ProfileScope(scanned=(0,), present=None)


def test_exception_from_progress_stops_the_analysis(synthetic_adb):
    report = run_scan(synthetic_adb)

    class Stop(Exception):
        pass

    def progress(done, total, package):
        raise Stop

    try:
        analyze_apks(report, _OneReport({}), progress)
    except Stop:
        pass
    else:
        raise AssertionError("Stop not raised")


def test_apk_target_without_any_report_is_a_gap(synthetic_adb):
    """Przegląd końcowy (T6): cel analizy APK, dla którego dostawca nic nie zwrócił, to luka."""
    provider = _RecordingProvider({"com.wlive.forecast": ApkReport(
        "com.wlive.forecast", 31, class_count=500)})
    report = run_scan(synthetic_adb, apk=provider)
    whatsapp = _by_pkg(report)["com.whatsapp"]
    assert "apk" in whatsapp.facts.gaps and whatsapp.incomplete
    assert "apk" not in _by_pkg(report)["com.wlive.forecast"].facts.gaps


def test_no_space_marks_the_apk_status_and_passes_flagged(synthetic_adb):
    seen = {}

    class Full:
        def reports_for(self, apps, progress=None, flagged=frozenset()):
            seen["flagged"] = flagged
            return {f.package: ApkReport(f.package, error="no_space") for f in apps}

    report = run_scan(synthetic_adb, apk=Full())
    assert report.apk.stopped_no_space is True and report.apk.analyzed == 0
    before = run_scan(synthetic_adb)  # werdykty sprzed analizy APK
    assert seen["flagged"] == {r.facts.package for r in before.results if r.verdict != "safe"}
    assert all("apk" in r.facts.gaps for r in report.results if r.facts.package in report.apk.failed)
