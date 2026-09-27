import json

from demalware.engine.adb.fake import FakeAdb
from demalware.engine.adb.transport import AdbError
from demalware.engine.apk.analyze import ApkReport, report_to_json
from demalware.engine.apk.fetch import FetchedApks
from demalware.engine.apk.isolated import IsolatedAnalyzer
from demalware.engine.apk.providers import (
    DeviceApkProvider,
    StoredApkProvider,
    select_apk_targets,
)
from demalware.engine.facts import AppFacts
from demalware.engine.scoring import AppResult


def _result(package, verdict="safe", trusted=False, is_system=False):
    return AppResult(AppFacts(package, is_system=is_system), [], 0, verdict, trusted, False)


def test_select_targets_user_untrusted_or_flagged():
    results = [
        _result("com.user.app"),
        _result("com.whatsapp", trusted=True),
        _result("com.whatsapp.flagged", verdict="review", trusted=True),
        _result("com.sys.quiet", is_system=True),
        _result("com.sys.flagged", verdict="review", is_system=True),
    ]
    assert [f.package for f in select_apk_targets(results)] == [
        "com.user.app", "com.whatsapp.flagged", "com.sys.flagged"]


def test_stored_provider_reads_existing_reports(tmp_path):
    (tmp_path / "com.a.json").write_text(json.dumps(report_to_json(ApkReport("com.a", ad_sdks=["admob"]))))
    reports = StoredApkProvider(tmp_path).reports_for([AppFacts("com.a"), AppFacts("com.b")])
    assert list(reports) == ["com.a"] and reports["com.a"].ad_sdks == ["admob"]


def test_device_provider_fetches_and_analyzes(tmp_path):
    seen = []

    def fetch(adb, package, cache_dir):
        seen.append((package, cache_dir))
        return FetchedApks([tmp_path / f"{package}.apk"], verified=True)

    def analyze(package, paths):
        return ApkReport(package, class_count=1, ad_sdks=["admob"])

    progress = []
    provider = DeviceApkProvider(FakeAdb(), cache_dir=tmp_path, fetch=fetch, analyze=analyze)
    reports = provider.reports_for([AppFacts("com.a", version_code=3), AppFacts("com.b")],
                                   progress=lambda done, total, pkg: progress.append((done, total, pkg)))
    assert set(reports) == {"com.a", "com.b"}
    assert ("com.a", tmp_path) in seen
    assert [p[:2] for p in progress] == [(1, 2), (2, 2)]
    assert reports["com.a"].error is None


def test_unverified_identity_is_reported_as_error(tmp_path):
    provider = DeviceApkProvider(
        FakeAdb(), cache_dir=tmp_path,
        fetch=lambda adb, package, cache_dir: FetchedApks([tmp_path / "x.apk"], verified=False),
        analyze=lambda package, paths: ApkReport(package, class_count=1))
    report = provider.reports_for([AppFacts("com.a")])["com.a"]
    assert report.error == "identity: unverified (no sha256sum on the phone)"


def test_device_provider_pull_error_and_crash_become_report_errors(tmp_path):
    def fetch(adb, package, cache_dir):
        if package == "com.gone":
            raise AdbError("command_failed", "pm path com.gone: no APK (uninstalled?)")
        return FetchedApks([], verified=True)

    def analyze(package, paths):
        raise RuntimeError("boom")

    reports = DeviceApkProvider(FakeAdb(), cache_dir=tmp_path, fetch=fetch, analyze=analyze
                                ).reports_for([AppFacts("com.gone"), AppFacts("com.crash")])
    assert reports["com.gone"].error.startswith("pull: ")
    assert reports["com.crash"].error == "RuntimeError: boom"


def _one_class(package, paths):
    return ApkReport(package, class_count=1)


def test_device_provider_isolates_analysis_by_default(tmp_path):
    made = []

    def isolated(timeout_s):
        made.append(IsolatedAnalyzer(timeout_s, analyze=_one_class))
        return made[-1]

    provider = DeviceApkProvider(
        FakeAdb(), cache_dir=tmp_path, workers=1, timeout_s=20,
        fetch=lambda adb, package, cache_dir: FetchedApks([], verified=True), isolated=isolated)
    reports = provider.reports_for([AppFacts("com.a"), AppFacts("com.b")])
    assert {p: r.class_count for p, r in reports.items()} == {"com.a": 1, "com.b": 1}
    assert len(made) == 1 and made[0]._proc is None  # jeden proces na wątek, zamknięty na końcu
