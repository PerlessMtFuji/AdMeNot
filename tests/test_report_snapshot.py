import dataclasses
import json

from conftest import SERIAL, make_synthetic_adb
from phonedb import make_phone_assets

from admenot.engine.apk.analyze import ApkReport
from admenot.engine.phones.provider import PhoneProvider
from admenot.engine.report.snapshot import MAX_PROBLEMS, scan_snapshot
from admenot.engine.session import ApkStatus, run_scan

BOOST, FORECAST = "com.clean.pro.boost", "com.wlive.forecast"


def test_snapshot_keeps_device_phone_scope_and_flagged_apps(tmp_path):
    report = run_scan(make_synthetic_adb())
    provider = PhoneProvider(make_phone_assets(tmp_path), tmp_path / "overrides.json")
    snap = scan_snapshot(report, provider.match(report.device))

    assert json.loads(json.dumps(snap)) == snap
    assert snap["version"] == 1
    assert snap["scanned_at"] == report.device.local_now.isoformat(timespec="seconds")
    assert snap["versions"] == report.versions and set(snap["versions"]) >= {"engine", "rules"}
    assert snap["device"] == {
        "serial": SERIAL, "brand": "samsung", "manufacturer": "samsung", "model": "SM-A145R",
        "market_name": None, "android_release": "14", "sdk": 34, "security_patch": "2026-07-01",
        "imei": None,
    }
    assert snap["phone"]["slug"] == "samsung-galaxy-a14" and "Galaxy A14" in snap["phone"]["name"]
    assert snap["phone"]["confidence"] == "exact"
    assert "image" not in snap["phone"]
    assert snap["app_count"] == len(report.results)

    scope = snap["scope"]
    assert scope["profiles"] == {"scanned": [0], "present": None}  # syntetyczny telefon: brak listy
    assert scope["low_behavior_data"] is False and scope["apk"] is None
    assert scope["usage_window_h"] == report.usage_window_h
    assert set(scope["collectors"]) == set(report.collectors)
    assert all(set(c) == {"ok", "error", "partial"} for c in scope["collectors"].values())

    apps = {a["package"]: a for a in snap["apps"]}
    assert set(apps) == {BOOST, FORECAST}  # pozostałe: safe i z pełną oceną
    boost = apps[BOOST]
    assert (boost["verdict"], boost["confidence"], boost["incomplete"], boost["gaps"]) == (
        "malicious", "high", False, [])
    assert boost["score"] >= 75 and boost["trusted"] is False and boost["apk"] is None
    assert boost["default_level"] == "disable" and boost["chosen_level"] is None
    assert apps[FORECAST]["default_level"] is None  # „Do sprawdzenia”: silnik nic nie proponuje
    result = next(r for r in report.results if r.facts.package == BOOST)
    assert [f["rule_id"] for f in boost["findings"]] == [f.rule_id for f in result.findings]
    first = boost["findings"][0]
    assert set(first) == {"rule_id", "class", "weight", "basis", "source", "locations", "evidence",
                        "text"}
    assert set(first["text"]) == {"pl", "en"} and first["text"]["pl"]
    for lang in ("pl", "en"):
        assert 1 <= len(boost["problems"][lang]) <= MAX_PROBLEMS
        assert len(set(boost["problems"][lang])) == len(boost["problems"][lang])
    scores = [a["score"] for a in snap["apps"]]
    assert scores == sorted(scores, reverse=True)


def test_snapshot_adds_chosen_and_incomplete_apps_and_apk_identity(tmp_path):
    report = run_scan(make_synthetic_adb())
    safe = [r for r in report.results if r.verdict == "safe"]
    chosen_safe, gapped = safe[0].facts.package, safe[1].facts.package
    results = [dataclasses.replace(r, incomplete=True) if r.facts.package == gapped else r
               for r in report.results]
    apk = ApkReport(BOOST, files={"base.apk": "ab" * 32}, cert_sha256=["cd" * 32])
    icon = "data:image/png;base64,iVBORw0KGgo="
    results = [dataclasses.replace(r, facts=dataclasses.replace(r.facts, icon=icon))
               if r.facts.package == BOOST else r for r in results]
    report = dataclasses.replace(report, results=results, apk_reports={BOOST: apk},
                                 apk=ApkStatus(requested=2, analyzed=1, failed={"x": "timeout"}))
    match = PhoneProvider(tmp_path / "missing", tmp_path / "o.json").match(report.device)
    snap = scan_snapshot(report, match, {chosen_safe: "silence", BOOST: "silence"})

    apps = {a["package"]: a for a in snap["apps"]}
    assert set(apps) == {BOOST, FORECAST, chosen_safe, gapped}
    assert apps[chosen_safe]["verdict"] == "safe" and apps[chosen_safe]["chosen_level"] == "silence"
    assert apps[gapped]["incomplete"] is True and apps[gapped]["chosen_level"] is None
    assert apps[BOOST]["chosen_level"] == "silence" and apps[BOOST]["default_level"] == "disable"
    assert apps[BOOST]["apk"] == {"files": {"base.apk": "ab" * 32}, "signers": ["cd" * 32],
                                  "error": None}
    assert snap["scope"]["apk"] == {"requested": 2, "analyzed": 1, "failed": {"x": "timeout"},
                                   "stopped_no_space": False}
    assert apps[BOOST]["icon"] == icon and apps[FORECAST]["icon"] is None


def test_snapshot_without_phone_database(tmp_path):
    report = run_scan(make_synthetic_adb())
    provider = PhoneProvider(tmp_path / "missing", tmp_path / "overrides.json")
    snap = scan_snapshot(report, provider.match(report.device))
    assert snap["phone"] == {"name": None, "slug": None, "confidence": "none"}


def _match(report, tmp_path):
    return PhoneProvider(tmp_path / "missing", tmp_path / "o.json").match(report.device)


def test_manual_snapshot_keeps_only_chosen_and_on_demand(scan_report, tmp_path):
    match = _match(scan_report, tmp_path)
    flagged = next(r.facts.package for r in scan_report.results if r.verdict != "safe")
    other = next(r.facts.package for r in scan_report.results if r.facts.package != flagged)
    report = dataclasses.replace(scan_report, apk_mode="partial",
                                 analyzed_on_demand=frozenset({other}))
    snap = scan_snapshot(report, match, {other: "remove"})
    assert snap["apk_mode"] == "partial" and snap["on_demand"] == [other]
    assert [a["package"] for a in snap["apps"]] == [other]  # ukryty werdykt `flagged` nie trafia
    manual = dataclasses.replace(scan_report, apk_mode="manual")
    assert [a["package"] for a in scan_snapshot(manual, match, {flagged: "remove"})["apps"]] \
        == [flagged]


def test_full_snapshot_is_unchanged(scan_report, tmp_path):
    snap = scan_snapshot(scan_report, _match(scan_report, tmp_path), {})
    assert snap["apk_mode"] == "pending"
    assert any(a["verdict"] != "safe" for a in snap["apps"])


def test_snapshot_carries_device_checks(scan_report, tmp_path):
    from admenot.engine.device_checks import BrowserSites, DeviceCheck, SiteEntry
    site = SiteEntry("https://a.pl", "a.pl", False, True, "site:com.android.chrome:web:https://a.pl;1")
    check = DeviceCheck("site_notifications", "review",
                        [BrowserSites("com.android.chrome", "Chrome", "per_site", "ok", [site])])
    report = dataclasses.replace(scan_report, device_checks=[check])
    snap = scan_snapshot(report, _match(report, tmp_path), {})
    assert json.loads(json.dumps(snap)) == snap
    assert snap["device_checks"] == [dataclasses.asdict(check)]
    plain = scan_snapshot(dataclasses.replace(scan_report, device_checks=[]),
                          _match(scan_report, tmp_path), {})
    assert plain["device_checks"] == []
