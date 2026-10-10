import json
import re
from datetime import UTC, datetime, timedelta, timezone

from conftest import SERIAL

from admenot.app import telemetry_events as ev
from admenot.engine.actions.planner import AppPlan
from admenot.engine.session import run_scan
from admenot.engine.workflow import AppStatus, OrderResult

PKG_RE = re.compile(r"^[A-Za-z0-9_.]{1,255}$")


def test_hour_rounds_down_in_utc():
    local = datetime(2026, 10, 10, 16, 59, 59, tzinfo=timezone(timedelta(hours=2)))
    assert ev.hour(local) == "2026-10-10T14:00:00Z"


def test_common_fields():
    c = ev.common("id", "scan", datetime(2026, 10, 10, 14, 5, tzinfo=UTC), "pl")
    assert set(c) == {"install", "type", "t", "app", "os", "lang"}
    assert c["t"] == "2026-10-10T14:00:00Z" and c["type"] == "scan"


def test_scan_event_counts_verdicts_without_packages(synthetic_adb):
    report = run_scan(synthetic_adb)
    e = ev.scan_event(report, "ab12cd34", 41, packages=False)
    flagged = [r for r in report.results if r.verdict != "safe"]
    assert e["apps"] == len(report.results)
    assert sum(e["verdicts"].values()) == len(flagged)
    assert set(e["verdicts"]) == {"malicious", "suspicious", "review"}
    assert e["packages"] is None and e["seconds"] == 41 and e["apk_stage"] is False
    assert e["device"] == {"manufacturer": "samsung", "model": "SM-A145R", "android": "14"}


def test_scan_event_lists_only_flagged_packages(synthetic_adb):
    report = run_scan(synthetic_adb)
    e = ev.scan_event(report, "ab12cd34", 41, packages=True)
    flagged = {r.facts.package for r in report.results if r.verdict != "safe"}
    assert {p["package"] for p in e["packages"]} == flagged
    assert set(e["packages"][0]) == {"package", "verdict", "score", "confidence", "system"}


def test_no_serial_or_device_name_anywhere(synthetic_adb):
    report = run_scan(synthetic_adb)
    text = json.dumps(ev.scan_event(report, "ab12cd34", 1, packages=True))
    assert SERIAL not in text and "Telefon Anny" not in text


def _plans():
    return [AppPlan("com.clean.pro.boost", "remove", []), AppPlan("com.user.notes", "disable", [])]


def test_repair_event_sources_levels_and_errors(synthetic_adb):
    device = run_scan(synthetic_adb).device
    result = OrderResult(order=None, stopped=False, apps=[
        AppStatus("com.clean.pro.boost", "ok"),
        AppStatus("com.user.notes", "failed", errors=["admin_refused", "admin_refused"]),
    ])
    verdicts = {"com.clean.pro.boost": "malicious", "com.user.notes": "safe"}
    e = ev.repair_event(device, "ab12cd34", _plans(), verdicts, result, None, packages=True)
    assert e["levels"] == {"silence": 0, "disable": 1, "remove": 1}
    assert e["sources"] == {"flagged": 1, "manual": 1}
    assert e["failed"] == 1 and e["errors"] == ["admin_refused"] and e["interrupted"] is None
    assert e["packages"] == [
        {"package": "com.clean.pro.boost", "source": "flagged", "level": "remove", "ok": True},
        {"package": "com.user.notes", "source": "manual", "level": "disable", "ok": False},
    ]


def test_repair_event_disconnected_has_unknown_outcome(synthetic_adb):
    device = run_scan(synthetic_adb).device
    e = ev.repair_event(device, "ab12cd34", _plans(), {}, None, "disconnected", packages=True)
    assert e["interrupted"] == "disconnected" and e["failed"] == 0
    assert all(p["ok"] is None for p in e["packages"])


def test_packages_are_capped_and_filtered(synthetic_adb):
    device = run_scan(synthetic_adb).device
    plans = [AppPlan(f"com.app.n{i}", "disable", []) for i in range(250)]
    plans.append(AppPlan("bad name/../x", "disable", []))
    e = ev.repair_event(device, "s", plans, {}, None, None, packages=True)
    assert len(e["packages"]) == ev.MAX_PACKAGES
    assert all(PKG_RE.match(p["package"]) for p in e["packages"])
    assert e["sources"]["manual"] == 251  # liczby obejmują wszystko, lista jest tylko przycięta


def test_undo_event(synthetic_adb):
    device = run_scan(synthetic_adb).device
    e = ev.undo_event(device, ["a.b", "c.d"], ["c.d"], 3, packages=False)
    assert (e["apps"], e["failed"], e["age_days"], e["packages"]) == (2, 1, 3, None)
    e = ev.undo_event(device, ["a.b", "c.d"], ["c.d"], 3, packages=True)
    assert e["packages"] == [{"package": "a.b", "ok": True}, {"package": "c.d", "ok": False}]


def test_sample_uses_the_same_shapes():
    s = ev.sample()
    assert [e["type"] for e in s["basic"]] == ["start", "scan", "repair", "undo"]
    assert all(e["packages"] is None for e in s["basic"] if e["type"] != "start")
    assert all(e["packages"] for e in s["packages"] if e["type"] != "start")
    assert all(e["install"] == ev.SAMPLE_INSTALL for e in s["basic"] + s["packages"])


def test_sample_scan_matches_scan_event_keys(synthetic_adb):
    real = ev.scan_event(run_scan(synthetic_adb), "s", 1, packages=True)
    shown = next(e for e in ev.sample()["packages"] if e["type"] == "scan")
    assert set(real) <= set(shown) and set(shown) - set(real) == {"install", "type", "t", "app", "os", "lang"}
    assert set(real["packages"][0]) == set(shown["packages"][0])


def test_values_fit_server_limits(synthetic_adb):
    # Serwer odrzuca całą paczkę za jedno złe pole — program wysyła tylko to, co serwer przyjmie.
    from dataclasses import replace

    report = run_scan(synthetic_adb)
    odd = replace(report.device, manufacturer="", model="M" * 100, android_release="  ")
    assert ev.device_of(odd) == {"manufacturer": "?", "model": "M" * 64, "android": "?"}
    assert ev.scan_event(replace(report, device=odd), "s", 10**6, packages=False)["seconds"] == 86_400
    long_error = AppStatus("a.b", "failed", errors=["x" * 100, ""])
    result = OrderResult(order=None, stopped=False, apps=[long_error])
    e = ev.repair_event(odd, "s", [AppPlan("a.b", "disable", [])], {}, result, None, packages=False)
    assert e["errors"] == ["x" * 64]
    assert len(ev.common("id", "start", datetime(2026, 10, 10, tzinfo=UTC), "pl")["os"]) <= 64
