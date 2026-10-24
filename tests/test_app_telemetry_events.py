import dataclasses
import json
import re
from datetime import UTC, datetime, timedelta, timezone

from conftest import SERIAL

from admenot.app import telemetry_events as ev
from admenot.engine.actions.planner import FIX_LEVEL, AppPlan
from admenot.engine.apk.timing import Eta
from admenot.engine.journal.db import Action
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
    assert e["sources"] == {"flagged": 1, "manual": 1, "blind": 0}
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


def test_undo_targets_leave_out_fix_only_browsers():
    # przeglądarka z samą poprawką ustawień to nie „aplikacja” i jej pakiet nie trafia do telemetrii
    targeted = [_action(1, "com.example.browser", FIX_LEVEL, "channel", "done"),
                _action(2, "com.wlive.forecast", "disable", "enabled", "done"),
                _action(3, "com.android.chrome", FIX_LEVEL, "channel", "done"),
                _action(4, "com.android.chrome", "silence", "permission", "done")]
    errors = [(targeted[0], "not_restored"), (targeted[1], "not_restored")]
    assert ev.undo_targets(targeted, errors) == (["com.android.chrome", "com.wlive.forecast"],
                                                 ["com.wlive.forecast"])


def test_undo_targets_do_not_fail_an_app_for_skipped_or_timed_out_sites():
    # niewłączone witryny liczą się w `sites`/`sites_restored`, nie jako błąd aplikacji
    targeted = [_action(1, "com.android.chrome", "silence", "channel", "done"),
                _action(2, "com.android.chrome", "silence", "channel", "done"),
                _action(3, "com.wlive.forecast", "disable", "enabled", "done")]
    errors = [(targeted[0], "site_skipped"), (targeted[1], "site_timeout"),
              (targeted[2], "site_timeout"), (targeted[2], "not_restored")]
    assert ev.undo_targets(targeted, errors) == (["com.android.chrome", "com.wlive.forecast"],
                                                 ["com.wlive.forecast"])
    assert ev.undo_targets(targeted[:2], errors[:2]) == (["com.android.chrome"], [])


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


def test_scan_event_carries_mode_and_eta(scan_report):
    body = ev.scan_event(dataclasses.replace(scan_report, apk_mode="manual"), "ab12cd34", 5, False,
                         apk_stage=True, eta=Eta(600, "rough", 360, 900))
    assert body["apk_mode"] == "manual" and body["eta"] == {"kind": "rough", "seconds": 600}
    assert ev.scan_event(scan_report, "ab12cd34", 5, False)["eta"] is None


def test_repair_event_marks_blind_picks():
    plans = [AppPlan("com.a", "remove", []), AppPlan("com.b", "disable", [])]
    body = ev.repair_event(ev._SAMPLE_DEVICE, "ab12cd34", plans, {"com.a": "malicious"}, None, None,
                           True, blind=frozenset({"com.a", "com.b"}))
    assert body["sources"] == {"flagged": 0, "manual": 0, "blind": 2}
    assert {p["source"] for p in body["packages"]} == {"blind"}


def test_ui_sample_json_matches_sample_and_shows_a_quick_scan():
    # Plik „co wysyłamy” w UI (atrapa mostu) = `sample()`; wersja programu zmienia się z wydaniem.
    from pathlib import Path

    path = Path(__file__).parent.parent / "ui" / "src" / "lib" / "telemetrySample.json"
    shown = json.loads(path.read_text("utf-8"))

    def strip(s):
        return {k: [{**e, "app": None} for e in v] for k, v in s.items()}

    assert strip(shown) == strip(ev.sample())
    scan = next(e for e in ev.sample()["basic"] if e["type"] == "scan")
    assert scan["apk_stage"] is False and scan["apk_mode"] == "pending" and scan["eta"] is None
    assert scan["apk"] is None


def _site_phone():
    from fakephone import make_cli_phone

    phone = make_cli_phone()
    phone.channels = {"com.android.chrome": {"web:https://www.example.com;1": 3,
                                              "web:https://b.example.org;2": 0},
                      "com.sec.android.app.sbrowser": {"SBROWSER_WEBSITES_NOTIFICATION_CHANNEL": 3}}
    phone.active = [("com.sec.android.app.sbrowser", "SBROWSER_WEBSITES_NOTIFICATION_CHANNEL",
                     "p#https://news.example.net/#1", "news.example.net")]
    return phone


def test_scan_event_reports_check_state_and_site_counts_without_domains():
    e = ev.scan_event(run_scan(_site_phone()), "ab12cd34", 5, packages=True)
    assert e["checks"] == {"site_notifications": "review"}
    assert e["sites"] == {"per_site": 2, "shared": 1, "rdp": 0}
    assert "example" not in json.dumps(e) and "sbrowser" not in json.dumps(e)


def _action(aid, package, level, kind, status):
    return Action(aid, 1, package, level, {"kind": kind, "package": package, "params": {}}, "cmd",
                  {}, None, status, datetime(2026, 10, 10, tzinfo=UTC), None)


def test_repair_event_counts_fix_steps_and_keeps_them_out_of_app_stats():
    from admenot.engine.actions.steps import Step

    site = "web:https://www.example.com;1"
    plans = [AppPlan("com.android.chrome", FIX_LEVEL,
                     [Step("channel", "com.android.chrome", {"channel_id": site}),
                      Step("channel", "com.android.chrome", {"channel_id": "web:https://b.pl;2"})]),
             AppPlan("org.mozilla.firefox", FIX_LEVEL,
                     [Step("site_permission", "org.mozilla.firefox",
                           {"origin": "https://www.example.com", "permission": "desktop-notification",
                            "capability": "2"})]),
             AppPlan("com.wlive.forecast", "disable", [])]
    # Liczą się kroki wykonane („wykonanych” w spec), nie zaplanowane: pominięty kanał nie wchodzi.
    actions = [_action(1, "com.android.chrome", FIX_LEVEL, "channel", "done"),
               _action(2, "com.android.chrome", FIX_LEVEL, "channel", "failed"),
               _action(3, "org.mozilla.firefox", FIX_LEVEL, "site_permission", "done"),
               _action(4, "com.wlive.forecast", "disable", "enabled", "done")]
    body = ev.repair_event(ev._SAMPLE_DEVICE, "ab12cd34", plans, {}, None, None, True, actions=actions)
    assert body["fixes"] == {"channel": 1, "site_permission": 1}
    assert ev.repair_event(ev._SAMPLE_DEVICE, "s", plans, {}, None, None, False)["fixes"] == {
        "channel": 0, "site_permission": 0}  # przerwane przed pierwszym krokiem: nic nie wykonano
    assert body["levels"] == {"silence": 0, "disable": 1, "remove": 0}
    assert sum(body["sources"].values()) == 1
    assert [p["package"] for p in body["packages"]] == ["com.wlive.forecast"]
    assert "example" not in json.dumps(body)
    assert ev.repair_event(ev._SAMPLE_DEVICE, "s", [], {}, None, None, False)["fixes"] == {
        "channel": 0, "site_permission": 0}


def test_undo_event_counts_sites(synthetic_adb):
    device = run_scan(synthetic_adb).device
    e = ev.undo_event(device, ["a.b"], [], 1, packages=False, sites=3, sites_restored=2)
    assert (e["sites"], e["sites_restored"]) == (3, 2)
    e = ev.undo_event(device, ["a.b"], [], 1, packages=False)
    assert (e["sites"], e["sites_restored"]) == (0, 0)


def test_repair_event_does_not_count_a_browser_with_only_a_site_fix_as_a_failed_app():
    plans = [AppPlan("com.a", "silence", []), AppPlan("com.android.chrome", FIX_LEVEL, [])]
    result = OrderResult(order=None, stopped=False, apps=[
        AppStatus("com.a", "ok"), AppStatus("com.android.chrome", "failed", errors=["user_timeout"])])
    body = ev.repair_event(ev._SAMPLE_DEVICE, "s", plans, {}, result, None, False)
    assert body["levels"]["silence"] == 1 and body["failed"] == 0 and body["errors"] == []
