import json
import threading
from collections import namedtuple

import pytest

from demalware.engine.adb.fake import FakeAdb
from demalware.engine.adb.transport import AdbError
from demalware.engine.apk import cache as C
from demalware.engine.apk.analyze import ApkReport, report_to_json
from demalware.engine.apk.fetch import FetchedApks
from demalware.engine.apk.isolated import IsolatedAnalyzer
from demalware.engine.apk.providers import (
    CachePolicy,
    DeviceApkProvider,
    StoredApkProvider,
    select_apk_targets,
)
from demalware.engine.facts import AppFacts
from demalware.engine.rules.model import Finding
from demalware.engine.scoring import AppResult


def _result(package, verdict="safe", trusted=False, is_system=False):
    return AppResult(AppFacts(package, is_system=is_system), [], 0, verdict, trusted, False)


def test_select_targets_every_user_app_and_flagged_system_apps():
    results = [
        _result("com.user.app"),
        _result("com.whatsapp", trusted=True),
        _result("com.sys.quiet", is_system=True, trusted=True),
        _result("com.sys.flagged", verdict="review", is_system=True),
    ]
    assert [f.package for f in select_apk_targets(results)] == [
        "com.user.app", "com.whatsapp", "com.sys.flagged"]


def test_select_targets_includes_system_apps_with_strong_signals():
    admin = Finding("DM-ADMIN-01", "position", 25, {}, {}, {}, category="removal", basis="granted")
    quiet_admin = AppResult(AppFacts("com.sys.admin", is_system=True), [admin], 24, "safe", False, False)
    trusted_admin = AppResult(AppFacts("com.sys.oem", is_system=True), [admin], 0, "safe", True, False)
    targets = [f.package for f in select_apk_targets([quiet_admin, trusted_admin])]
    assert targets == ["com.sys.admin"]


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


Disk = namedtuple("Disk", "total used free")


def _apps(n):
    return [AppFacts(f"com.app{i}", version_code=1, apk_path=f"/data/app/a{i}/base.apk")
            for i in range(n)]


def _writing_fetch(size):
    """Pobranie, które zapisuje `size` bajtów do wpisu `<pakiet>/id`, jak `fetch_apks`."""
    def fetch(adb, package, cache_dir):
        entry = cache_dir / package / "id"
        entry.mkdir(parents=True, exist_ok=True)
        (entry / "base.apk").write_bytes(b"x" * size)
        return FetchedApks([entry / "base.apk"], verified=True)
    return fetch


@pytest.fixture
def free(monkeypatch):
    state = {"free": 100 * C.GB}
    monkeypatch.setattr(C, "disk_usage", lambda path: Disk(500 * C.GB, 0, state["free"]))
    return state


def _provider(tmp_path, policy, fetch, workers=1):
    return DeviceApkProvider(FakeAdb(), cache_dir=tmp_path, workers=workers, fetch=fetch,
                             analyze=lambda package, paths: ApkReport(package, class_count=1),
                             policy=policy)


def test_limit_below_one_app_still_analyzes_everything(tmp_path, free):
    reports = _provider(tmp_path, CachePolicy(limit_bytes=1), _writing_fetch(1000)).reports_for(_apps(4))
    assert all(r.error is None for r in reports.values())
    assert C.cache_size(tmp_path) <= 1000  # zostaje najwyżej wpis ostatniej aplikacji w toku


def test_pruning_keeps_flagged_apps_for_the_repair(tmp_path, free):
    _provider(tmp_path, CachePolicy(limit_bytes=2000), _writing_fetch(1000)).reports_for(
        _apps(4), flagged=frozenset({"com.app0"}))
    assert (tmp_path / "com.app0").exists()
    assert C.cache_size(tmp_path) <= 2000


def test_no_space_stops_the_rest_without_pulling(tmp_path, free):
    pulled = []
    lock = threading.Lock()
    app1_failed = threading.Event()

    def fetch(adb, package, cache_dir):
        with lock:
            pulled.append(package)
        if package == "com.app1":
            try:
                raise C.NoSpace(package)
            finally:
                app1_failed.set()
        app1_failed.wait(5)  # app0 czeka na NoSpace z app1: kolejne zadania startują po nim
        return FetchedApks([], verified=True)

    reports = _provider(tmp_path, CachePolicy(limit_bytes=C.GB), fetch, workers=2).reports_for(_apps(8))
    assert set(pulled) == {"com.app0", "com.app1"}
    assert reports["com.app0"].error is None
    assert sorted(p for p, r in reports.items() if r.error == C.NO_SPACE) == [
        f"com.app{i}" for i in range(1, 8)]


def test_low_free_space_before_a_pull_is_no_space(tmp_path, free):
    free["free"] = C.RESERVE - 1
    reports = _provider(tmp_path, CachePolicy(limit_bytes=C.GB), _writing_fetch(10)).reports_for(_apps(2))
    assert {r.error for r in reports.values()} == {C.NO_SPACE}
    assert not tmp_path.joinpath("com.app0").exists()


def _estimating(tmp_path, sizes, answer, seen):
    adb = FakeAdb()
    apps = _apps(len(sizes))
    out = "".join(f"{s} /data/app/a{i}/base.apk\n" for i, s in enumerate(sizes))
    adb.responses[C.stat_command(C._stat_paths(apps)[0])] = out
    policy = CachePolicy(limit_bytes=10 * C.GB,
                         on_estimate=lambda est, use: seen.append(("estimate", est.to_fetch_bytes)),
                         decide=lambda est, use: seen.append(("decide", est.largest_bytes)) or answer)
    provider = DeviceApkProvider(adb, cache_dir=tmp_path, workers=1, fetch=_writing_fetch(10),
                                 analyze=lambda package, paths: ApkReport(package, class_count=1),
                                 policy=policy)
    return provider, apps


def test_estimate_is_shown_and_no_question_when_it_fits(tmp_path, free):
    seen = []
    provider, apps = _estimating(tmp_path, [100, 200], "skip", seen)
    reports = provider.reports_for(apps)
    assert seen == [("estimate", 300)]
    assert all(r.error is None for r in reports.values())


@pytest.mark.parametrize("answer", ["skip", "run", "clear"])
def test_question_when_two_largest_do_not_fit(tmp_path, free, answer):
    old = tmp_path / "com.old" / "id"
    old.mkdir(parents=True)
    (old / "base.apk").write_bytes(b"x" * 5)
    free["free"] = C.RESERVE + 250  # 250 wolne + 5 do przycięcia < 300 (dwie największe)
    seen = []
    provider, apps = _estimating(tmp_path, [100, 200], answer, seen)
    reports = provider.reports_for(apps)
    assert seen == [("estimate", 300), ("decide", 300)]
    if answer == "skip":
        assert {r.error for r in reports.values()} == {C.NO_SPACE}
        assert old.exists()
    else:
        assert all(r.error is None for r in reports.values())  # każda osobno mieści się w 250
        assert old.exists() == (answer == "run")


def test_without_policy_no_space_from_fetch_is_reported(tmp_path):
    def fetch(adb, package, cache_dir):
        raise C.NoSpace(package)

    provider = DeviceApkProvider(FakeAdb(), cache_dir=tmp_path, fetch=fetch,
                                 analyze=lambda package, paths: ApkReport(package))
    assert provider.reports_for([AppFacts("com.a")])["com.a"].error == C.NO_SPACE


def test_broken_disk_usage_disables_the_policy(tmp_path, monkeypatch):
    def broken(path):
        raise OSError("no such device")

    monkeypatch.setattr(C, "disk_usage", broken)
    reports = _provider(tmp_path, CachePolicy(limit_bytes=1), _writing_fetch(10)).reports_for(_apps(2))
    assert all(r.error is None for r in reports.values())


def test_disk_usage_failing_midway_does_not_break_the_run(tmp_path, monkeypatch):
    calls = {"n": 0}

    def flaky(path):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("gone")
        return Disk(500 * C.GB, 0, 100 * C.GB)

    monkeypatch.setattr(C, "disk_usage", flaky)
    reports = _provider(tmp_path, CachePolicy(limit_bytes=1), _writing_fetch(10)).reports_for(_apps(3))
    assert all(r.error is None for r in reports.values())


def test_spec_example_prunes_enough_room_before_each_pull(tmp_path, monkeypatch):
    """Spec §3.2 w skali 1 GB = 1000 B: wolne 4 GB, limit 10 GB, 10 aplikacji po 600 MB.

    Wolne miejsce maleje z każdym zapisanym plikiem — kontrola przed pobraniem musi przyciąć
    tyle, żeby zmieściło się kolejne pobranie, a nie tylko do limitu efektywnego.
    """
    unit = 1000
    monkeypatch.setattr(C, "RESERVE", 2 * unit)
    free_at_start = 4 * unit
    monkeypatch.setattr(C, "disk_usage",
                        lambda path: Disk(120 * unit, 0, free_at_start - C.cache_size(tmp_path)))
    size, apps = 600, _apps(10)
    adb = FakeAdb()
    out = "".join(f"{size} /data/app/a{i}/base.apk\n" for i in range(len(apps)))
    adb.responses[C.stat_command(C._stat_paths(apps)[0])] = out
    peak = {"bytes": 0}
    write = _writing_fetch(size)
    lock = threading.Lock()

    def fetch(adb, package, cache_dir):
        fetched = write(adb, package, cache_dir)
        with lock:
            peak["bytes"] = max(peak["bytes"], C.cache_size(tmp_path))
        return fetched

    provider = DeviceApkProvider(adb, cache_dir=tmp_path, workers=2, fetch=fetch,
                                 analyze=lambda package, paths: ApkReport(package, class_count=1),
                                 policy=CachePolicy(limit_bytes=10 * unit))
    reports = provider.reports_for(apps)
    assert {p: r.error for p, r in reports.items()} == {f.package: None for f in apps}
    effective = 2 * unit  # min(10 GB, 0 + 4 GB − 2 GB)
    assert C.cache_size(tmp_path) <= effective
    assert peak["bytes"] <= effective + 2 * size


def test_cached_app_needs_no_room_for_a_download(tmp_path, free, monkeypatch):
    """Trafienie w pamięci podręcznej nie pobiera nic — kontrola nie wymaga miejsca na plik,
    a przycinanie przed pobraniem nie usuwa wpisu tej aplikacji."""
    apps = _apps(1)
    entry = tmp_path / "com.app0" / "id"
    entry.mkdir(parents=True)
    (entry / "base.apk").write_bytes(b"x" * 500)
    adb = FakeAdb()
    adb.responses[C.stat_command(C._stat_paths(apps)[0])] = "500 /data/app/a0/base.apk\n"
    free["free"] = C.RESERVE + 100  # mniej niż 500 na pobranie

    def fetch(adb, package, cache_dir):
        assert (cache_dir / package / "id" / "base.apk").exists()
        return FetchedApks([cache_dir / package / "id" / "base.apk"], verified=True)

    provider = DeviceApkProvider(adb, cache_dir=tmp_path, workers=1, fetch=fetch,
                                 analyze=lambda package, paths: ApkReport(package, class_count=1),
                                 policy=CachePolicy(limit_bytes=10 * C.GB))
    assert provider.reports_for(apps)["com.app0"].error is None


def test_own_entry_is_not_pruned_before_its_fetch(tmp_path, monkeypatch):
    """Pakiet trafia do `busy` przed przycinaniem: jego wpis nie jest usuwany i pobierany od nowa."""
    apps = _apps(1)
    for package in ("com.app0", "com.other"):
        entry = tmp_path / package / "old"
        entry.mkdir(parents=True)
        (entry / "base.apk").write_bytes(b"x" * 500)
    # Wolne rośnie z usuwaniem; bez `com.other` mieści się (brak szacunku: need 0).
    monkeypatch.setattr(C, "disk_usage",
                        lambda path: Disk(500 * C.GB, 0, C.RESERVE + 700 - C.cache_size(tmp_path)))
    seen = []

    def fetch(adb, package, cache_dir):
        seen.append((cache_dir / package / "old").exists())
        return FetchedApks([], verified=True)

    _provider(tmp_path, CachePolicy(limit_bytes=1), fetch).reports_for(apps)
    assert seen == [True]
    assert not (tmp_path / "com.other").exists()


def test_estimate_failing_with_oserror_runs_without_estimate(tmp_path, free, monkeypatch):
    from demalware.engine.apk import providers as P

    def broken(*a, **kw):
        raise OSError("cache dir vanished")

    monkeypatch.setattr(P, "estimate", broken)
    reports = _provider(tmp_path, CachePolicy(limit_bytes=C.GB), _writing_fetch(10)).reports_for(_apps(2))
    assert all(r.error is None for r in reports.values())


def test_files_changed_after_verification_discard_the_analysis(tmp_path):
    expected = {"base.apk": "a" * 64}
    provider = DeviceApkProvider(
        FakeAdb(), cache_dir=tmp_path,
        fetch=lambda adb, package, cache_dir: FetchedApks(
            [tmp_path / "base.apk"], verified=True, expected=expected),
        analyze=lambda package, paths: ApkReport(
            package, class_count=10, ad_sdks=["admob"], files={"base.apk": "b" * 64}))
    report = provider.reports_for([AppFacts("com.a", version_code=7)])["com.a"]
    assert report.ad_sdks == [] and report.class_count == 0
    assert report.version_code == 7
    assert report.error == "identity: base.apk differs from the verified file"


def test_matching_files_keep_the_analysis(tmp_path):
    expected = {"base.apk": "a" * 64}
    provider = DeviceApkProvider(
        FakeAdb(), cache_dir=tmp_path,
        fetch=lambda adb, package, cache_dir: FetchedApks(
            [tmp_path / "base.apk"], verified=True, expected=expected),
        analyze=lambda package, paths: ApkReport(
            package, class_count=10, ad_sdks=["admob"], files=dict(expected)))
    report = provider.reports_for([AppFacts("com.a")])["com.a"]
    assert report.ad_sdks == ["admob"] and report.error is None


def test_deep_report_is_reused_by_verified_hashes(tmp_path):
    calls = []
    expected = {"base.apk": "a" * 64}

    def deep(package, paths):
        calls.append(package)
        return ApkReport(package, class_count=1, deep=True, files=dict(expected))

    def make():
        return DeviceApkProvider(
            FakeAdb(), cache_dir=tmp_path / "apk-cache", deep=frozenset({"com.a"}), deep_analyze=deep,
            fetch=lambda adb, package, cache_dir: FetchedApks([tmp_path / "base.apk"], True, expected),
            analyze=lambda package, paths: ApkReport(package, class_count=1, files=dict(expected)))

    assert make().reports_for([AppFacts("com.a")])["com.a"].deep
    assert make().reports_for([AppFacts("com.a")])["com.a"].deep
    assert calls == ["com.a"]  # drugi raz z pamięci wyników
