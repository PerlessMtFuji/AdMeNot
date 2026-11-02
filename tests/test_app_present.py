import json
from datetime import datetime
from pathlib import Path

import pytest
from fakephone import make_cli_phone

from admenot.app.present import (
    action_view,
    app_name,
    app_view,
    device_card,
    device_checks_view,
    eta_view,
    history_view,
    image_uri,
    plain,
    plan_view,
    result_view,
    scan_view,
    severity,
    source_view,
    step_view,
    symptoms,
)
from admenot.engine.actions.executor import ExecOptions
from admenot.engine.adb.transport import AdbError
from admenot.engine.apk.timing import Eta
from admenot.engine.collectors.profiles import PM_USERS
from admenot.engine.collectors.system import DEVICE_POLICY
from admenot.engine.facts import AppFacts
from admenot.engine.journal.db import Journal
from admenot.engine.phones.provider import SILHOUETTE, PhoneMatch
from admenot.engine.rules.model import Finding
from admenot.engine.session import run_scan
from admenot.engine.share import plan_code
from admenot.engine.workflow import execute_order, plan_order, start


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_plain_makes_everything_json():
    value = {"s": {"b", "a"}, "t": (1, 2), "d": datetime(2026, 9, 26, 14, 0), "p": Path("x"), 1: None}
    assert plain(value) == {"s": ["a", "b"], "t": [1, 2], "d": "2026-09-26T14:00:00",
                            "p": "x", "1": None}


def test_scan_view_pl_and_en(synthetic_adb):
    report = run_scan(synthetic_adb)
    view = scan_view(report, "pl")
    json.dumps(view)
    apps = {a["package"]: a for a in view["apps"]}
    boost = apps["com.clean.pro.boost"]
    assert boost["verdict"] == "malicious" and boost["verdict_label"] == "Szkodliwa"
    assert boost["default_level"] == "disable" and boost["is_admin"] is True
    assert boost["confidence"] == "high"
    assert 1 <= len(boost["problems"]) <= 3 and len(set(boost["problems"])) == len(boost["problems"])
    assert boost["findings"][0]["weight"] >= boost["findings"][-1]["weight"]
    assert apps["com.whatsapp"]["default_level"] is None
    counts = view["counts"]
    assert counts["malicious"] >= 1 and counts["admins"] == 1 and counts["total"] == len(apps)
    assert view["collectors"]["ok"] == view["collectors"]["total"]
    assert scan_view(report, "en")["apps"][0]["verdict_label"] in ("Malicious", "Suspicious")


def test_default_level_follows_the_phone_android_version(synthetic_adb):
    """Plan w GUI, zlecenie i protokół liczą domyślne działanie z wersji Androida telefonu."""
    from dataclasses import replace

    from admenot.engine.report.snapshot import scan_snapshot
    from admenot.engine.workflow import recommended_requests

    report = run_scan(synthetic_adb)
    r = report.results[0]
    report.results = [replace(r, verdict="suspicious", facts=replace(
        r.facts, accessibility_enabled=False, notification_listener=False, is_home_holder=False))]
    report.device = replace(report.device, sdk=31)
    pkg = r.facts.package
    assert scan_view(report, "pl")["apps"][0]["default_level"] == "disable"
    assert recommended_requests(report) == {pkg: "disable"}
    snap = scan_snapshot(report, PhoneMatch("none", "silhouette"))
    assert {a["package"]: a["default_level"] for a in snap["apps"]} == {pkg: "disable"}


def test_device_card_always_shows_the_silhouette(synthetic_adb, tmp_path):
    report = run_scan(synthetic_adb)
    card = device_card(report.device, None)
    assert card["image"] == image_uri(SILHOUETTE)
    assert card["name"] == "samsung SM-A145R" and card["match"] is None and card["sdk"] == 34
    match = PhoneMatch("exact", "model_code", None, "SM-A145R")
    card = device_card(report.device, match)
    assert card["image"] == image_uri(SILHOUETTE)
    assert card["match"] == {"confidence": "exact", "step": "model_code", "matched": "SM-A145R"}
    assert image_uri(tmp_path / "missing.webp") == ""
    assert image_uri(SILHOUETTE).startswith("data:image/svg+xml")


def _f(rule_id, category, weight, text):
    return Finding(rule_id, "behavior", weight, {}, {"pl": text, "en": text}, {}, category,
                   {"pl": rule_id, "en": rule_id})


def test_symptoms_group_by_category_sort_and_join():
    out = symptoms([
        _f("A", "removal", 15, "Ukrywa ikonę."),
        _f("B", "ads", 25, "Okna."),
        _f("C", "removal", 25, "Admin."),
        _f("D", "removal", 15, "Ukrywa ikonę."),
        _f("E", "origin", 8, "Spoza Play."),
        Finding("X", "combo", 20, {}, {"pl": "k"}, {}, "combo", {"pl": "k"}),
    ], "pl")
    assert out == [
        {"category": "ads", "severity": "bad", "text": "Okna."},
        {"category": "removal", "severity": "bad", "text": "Admin. Ukrywa ikonę."},
        {"category": "origin", "severity": "neutral", "text": "Spoza Play."},
    ]
    assert [severity(w) for w in (25, 20, 19, 10, 9, 0)] == \
        ["bad", "bad", "warn", "warn", "neutral", "neutral"]
    assert symptoms([], "pl") == []


def test_source_view_names_installers():
    assert source_view(AppFacts("p", installer="com.apkpure.aegon", installed_days=3.4), "pl") == \
        {"label": "APKPure", "days": 3}
    assert source_view(AppFacts("p", installer="com.android.vending"), "en") == \
        {"label": "Play Store", "days": None}
    assert source_view(AppFacts("p", installer="com.android.vending"), "pl")["label"] == "Sklep Play"
    assert source_view(AppFacts("p", installer="com.foo.store"), "pl")["label"] == "com.foo.store"
    assert source_view(AppFacts("p"), "pl")["label"] == "nieznane"
    assert source_view(AppFacts("p", is_system=True), "en")["label"] == "system"


def test_source_view_names_vendor_stores():
    """Sklepy producentów po nazwie, nie po pakiecie — długi pakiet nie mieści się w kolumnie „Źródło”."""
    stores = {"com.xiaomi.mipicks": "GetApps", "com.xiaomi.market": "GetApps",
              "com.huawei.appmarket": "AppGallery", "com.sec.android.app.samsungapps": "Galaxy Store",
              "com.heytap.market": "App Market", "com.oppo.market": "App Market",
              "com.bbk.appstore": "V-Appstore", "com.amazon.venezia": "Amazon Appstore"}
    for installer, label in stores.items():
        assert source_view(AppFacts("p", installer=installer), "pl")["label"] == label


def test_scan_view_has_symptoms_labels_and_source(synthetic_adb):
    view = scan_view(run_scan(synthetic_adb), "pl")
    apps = {a["package"]: a for a in view["apps"]}
    boost = apps["com.clean.pro.boost"]
    cats = [s["category"] for s in boost["symptoms"]]
    assert cats and "combo" not in cats and len(cats) == len(set(cats))
    assert boost["symptoms"][0]["severity"] == "bad"
    assert all(f["label"] and f["category"] for f in boost["findings"])
    assert not any(f["label"].startswith("DM-") for f in boost["findings"])
    assert boost["source"]["label"] == "Chrome"
    json.dumps(view)


def test_plan_step_result_and_history_views(tmp_path):
    phone = make_cli_phone()
    report = run_scan(phone)
    plan = plan_order(phone, report, {"com.sec.android.app.launcher": "disable",
                                      "com.wlive.forecast": "disable"})
    view = plan_view(plan, "pl")
    blocked, ok = view["apps"]
    assert blocked["blocked"] is True and blocked["reason"] == "protected"
    assert "chroniona" in blocked["reason_text"] and blocked["level_label"] == "WYŁĄCZ"
    assert ok["blocked"] is False and "wyłączenie aplikacji" in ok["steps"]
    assert view["runnable"] == 1
    assert view["code"] == plan_code(plan)  # kod kontrolny planu dla klienta (spec plan-qr §3.1)

    names = {p: app_name(f, p) for p, f in plan.facts.items()}
    event = {"type": "step", "action_id": 3, "package": "com.wlive.forecast",
             "step": {"kind": "enabled", "package": "com.wlive.forecast", "params": {"enabled": "0"}},
             "status": "failed", "error": "security"}
    sv = step_view(event, "pl", "Xiaomi", names)
    assert {k: sv[k] for k in ("action_id", "package", "name", "kind", "label", "status")} == {
        "action_id": 3, "package": "com.wlive.forecast", "name": names["com.wlive.forecast"],
        "kind": "enabled", "label": "wyłączenie aplikacji", "status": "failed"}
    assert "zabezpieczeń" in sv["error"]
    # surowy klucz obok tekstu: UI rozróżnia po nim stan witryny w kolejce cofania (`channel_gone`)
    assert sv["error_key"] == "security"
    assert step_view({**event, "status": "done", "error": None}, "pl", "Xiaomi", names)["error_key"] is None

    with Journal(tmp_path / "j.db") as journal:
        order = start(journal, plan, "Anna <b>")
        result = execute_order(phone, journal, order, ExecOptions())
        rv = result_view(result, names, "en", "samsung")
        assert rv["order"] == order.number and rv["status_label"] == "done"
        assert rv["apps"] == [{"package": "com.wlive.forecast", "name": names["com.wlive.forecast"],
                               "outcome": "ok", "errors": [], "kinds": []}]
        hv = history_view(journal, phone.serial, [phone.serial], "pl")
        json.dumps(hv)
        (o,) = hv["orders"]
        assert o["number"] == order.number and o["client"] == "Anna <b>"
        assert o["status_label"] == "wykonane" and o["interrupted"] is False
        assert {a["status_label"] for a in o["actions"]} == {"wykonane"}
        assert hv["devices"] == [{"serial": phone.serial, "name": o["model"], "model": o["model"],
                                  "image": image_uri(SILHOUETTE), "imei": None}]
        empty = history_view(journal, None, [], "pl")
        assert empty["orders"] == [] and empty["devices"] == []


def test_app_view_passes_icon():
    from admenot.engine.scoring import AppResult

    facts = AppFacts("com.x", icon="data:image/png;base64,iVBORw0KGgo=")
    view = app_view(AppResult(facts, [], 0, "safe", False, False), "pl")
    assert view["icon"] == "data:image/png;base64,iVBORw0KGgo="


def test_app_view_says_whether_the_app_is_disabled_on_the_phone():
    from admenot.engine.scoring import AppResult

    assert app_view(AppResult(AppFacts("com.x"), [], 0, "safe", False, False), "pl")["enabled"] is True
    off = AppFacts("com.x", enabled=False)
    assert app_view(AppResult(off, [], 0, "safe", False, False), "pl")["enabled"] is False


def test_app_view_shows_confidence_gaps_and_scoped_safe_label(synthetic_adb):
    synthetic_adb.responses[DEVICE_POLICY] = AdbError("timeout", "slow")
    report = run_scan(synthetic_adb)
    apps = {a["package"]: a for a in scan_view(report, "pl")["apps"]}
    whatsapp = apps["com.whatsapp"]
    assert whatsapp["verdict_label"] == "Brak istotnych sygnałów (ocena niepełna)"
    assert whatsapp["gaps"] == [{"key": "device_policy", "label": "administratorzy urządzenia"}]
    # brak danych obniża pewność: zachowanie dwóch rodzajów daje „wysoką” tylko przy pełnych danych
    assert apps["com.clean.pro.boost"]["confidence_label"].startswith("średnia")


def test_scan_view_reports_other_profiles_and_usage_window(synthetic_adb):
    synthetic_adb.responses[PM_USERS] = "Users:\n\tUserInfo{0:A:c13}\n\tUserInfo{10:W:1030}\n"
    view = scan_view(run_scan(synthetic_adb), "en")
    assert view["profiles"] == {"others": [10], "known": True}
    assert view["usage_window_h"] is not None


def test_scan_view_reports_partial_collectors(synthetic_adb):
    """Przegląd końcowy I2: częściowa awaria kolektora musi być widoczna w GUI."""
    from admenot.engine.collectors.behavior import APPOPS_GET

    synthetic_adb.responses[APPOPS_GET.format(package="com.whatsapp")] = AdbError("command_failed", "x")
    view = scan_view(run_scan(synthetic_adb), "pl")
    assert view["collectors"]["partial"] == [{"name": "appops", "count": 1}]
    assert view["collectors"]["failed"] == []


def test_history_devices_show_phone_name_model_and_silhouette(tmp_path):
    photo = tmp_path / "samsung-galaxy-a14.webp"  # migawka z wersji ≤ 0.9.4 ze zdjęciem
    photo.write_bytes(b"RIFF\0\0\0\0WEBP")
    with Journal(tmp_path / "j.db") as journal:
        order = journal.create_order("R58", "SM-A145R", "Anna")
        journal.save_scan(order.id, {
            "device": {"serial": "R58", "brand": "samsung", "model": "SM-A145R", "market_name": None},
            "phone": {"name": "Samsung Galaxy A14", "slug": "samsung-galaxy-a14",
                      "confidence": "exact", "image": str(photo)},
            "apps": []})
        journal.create_order("OLD1", "Redmi_Note_8", None)  # zlecenie sprzed migawek (Plan 6)
        hv = history_view(journal, "R58", ["R58", "OLD1"], "pl")
    json.dumps(hv)
    a14, old = hv["devices"]
    assert (a14["serial"], a14["name"], a14["model"]) == ("R58", "Samsung Galaxy A14", "SM-A145R")
    assert a14["image"] == image_uri(SILHOUETTE)
    assert (old["serial"], old["name"], old["model"]) == ("OLD1", "Redmi_Note_8", "Redmi_Note_8")
    assert old["image"] == image_uri(SILHOUETTE)


def test_history_orders_name_apps_and_show_icons_from_the_order_snapshot(tmp_path):
    with Journal(tmp_path / "j.db") as journal:
        order = journal.create_order("R58", "SM-A145R", None)
        journal.save_scan(order.id, {"apps": [
            {"package": "com.wlive.forecast", "label": "Weather Live", "icon": "data:image/png;base64,AA=="},
            {"package": "com.other", "label": None, "icon": None}]})
        step = {"kind": "enabled", "package": "com.wlive.forecast", "params": {"enabled": "0"}}
        journal.add_action(order.id, "com.wlive.forecast", "disable", step, "pm disable-user")
        journal.add_action(order.id, "com.gone", "disable", {**step, "package": "com.gone"}, "pm disable-user")
        journal.create_order("OLD1", "Redmi_Note_8", None)  # zlecenie bez migawki
        (o,) = history_view(journal, "R58", ["R58"], "pl")["orders"]
        (old,) = history_view(journal, "OLD1", ["OLD1"], "pl")["orders"]
    assert o["apps"] == {"com.wlive.forecast": {"name": "Weather Live", "icon": "data:image/png;base64,AA=="},
                         "com.gone": {"name": None, "icon": None}}
    assert all(a["manual_undo"] is None for a in o["actions"])
    assert old["apps"] == {}


def test_eta_view():
    assert eta_view(None) == {"eta_s": None, "eta_kind": None, "eta_min_s": None, "eta_max_s": None}
    assert eta_view(Eta(90, "rough", 54, 135)) == {"eta_s": 90, "eta_kind": "rough",
                                                   "eta_min_s": 54, "eta_max_s": 135}


def test_scan_view_carries_mode_and_install_dates(scan_report):
    view = scan_view(scan_report, "pl")
    assert view["apk_mode"] == "pending" and view["on_demand"] == []
    assert all("first_install" in a for a in view["apps"])
    dated = [r for r in scan_report.results if r.facts.first_install]
    if dated:
        app = next(a for a in view["apps"] if a["package"] == dated[0].facts.package)
        assert datetime.fromisoformat(app["first_install"]) == dated[0].facts.first_install.replace(microsecond=0)


def test_history_marks_manual_orders(tmp_path):
    with Journal(tmp_path / "j.db") as journal:
        manual = journal.create_order("R58", "SM-A145R", None)
        journal.save_scan(manual.id, {"apps": [], "apk_mode": "manual"})
        plain_order = journal.create_order("R58", "SM-A145R", None)
        journal.save_scan(plain_order.id, {"apps": []})
        orders = history_view(journal, "R58", ["R58"], "pl")["orders"]
    by_id = {o["id"]: o["manual"] for o in orders}
    assert by_id == {manual.id: True, plain_order.id: False}


def test_app_view_lists_analysis_scope_for_a_quiet_app():
    from admenot.engine.scoring import AppResult

    facts = AppFacts("com.x", ad_sdks=set(), dynamic_code=True, obfuscation_ratio=0.9)
    view = app_view(AppResult(facts, [], 0, "safe", False, False), "pl")
    assert [s["key"] for s in view["scope"]] == ["obfuscated", "dynamic_code"]


CHROME = "com.android.chrome"
SBROWSER = "com.sec.android.app.sbrowser"
SB_CHANNEL = "SBROWSER_WEBSITES_NOTIFICATION_CHANNEL"
SITE = "web:https://www.example.com;1"


def _site_phone():
    phone = make_cli_phone()
    phone.channels = {CHROME: {SITE: 3, "web:https://b.pl;2": 0}, SBROWSER: {SB_CHANNEL: 3}}
    phone.active = [(SBROWSER, SB_CHANNEL, "p#https://news.example.org/#1", "news.example.org")]
    return phone


def test_scan_view_lists_device_checks_with_labels():
    view = scan_view(run_scan(_site_phone()), "pl")
    json.dumps(view)
    (check,) = view["device_checks"]
    assert (check["id"], check["state"], check["state_label"]) == (
        "site_notifications", "review", "Do sprawdzenia")
    chrome, sbrowser = check["browsers"]
    assert {k: chrome[k] for k in ("package", "name", "mode", "read", "rdp_hint", "all_fix")} == {
        "package": CHROME, "name": "Chrome", "mode": "per_site", "read": "ok", "rdp_hint": False,
        "all_fix": None}
    assert chrome["all_fix_label"] is None
    blocked, enabled = chrome["sites"]  # po hoście: b.pl przed www.example.com
    assert enabled == {"host": "www.example.com", "origin": "https://www.example.com", "blocked": False,
                       "active": False, "fix": f"site:{CHROME}:{SITE}",
                       "fix_label": "Wyłączenie powiadomień: www.example.com (Chrome)"}
    assert blocked["blocked"] is True and blocked["fix"] is None and blocked["fix_label"] is None
    assert sbrowser["all_fix"] == f"site_all:{SBROWSER}"
    # akcję „Blokuj” w aktywnym powiadomieniu ma Samsung Internet, nie Chrome (ani Firefox)
    assert (chrome["block_action"], sbrowser["block_action"]) == (False, True)
    assert sbrowser["all_fix_label"] == "Wyłączenie powiadomień wszystkich witryn (Samsung Internet)"
    assert sbrowser["sites"][0]["host"] == "news.example.org" and sbrowser["sites"][0]["fix"] is None
    english = scan_view(run_scan(_site_phone()), "en")["device_checks"][0]
    assert english["state_label"] == "Review"
    assert english["browsers"][0]["sites"][1]["fix_label"] == (
        "Turning off notifications: www.example.com (Chrome)")


def test_browser_names_come_from_the_table_then_from_labels_known_after_the_scan():
    from admenot.engine.device_checks import BrowserSites, DeviceCheck

    check = DeviceCheck("site_notifications", "ok", [
        BrowserSites("com.vivaldi.browser", "Vivaldi", "per_site", "ok", []),
        BrowserSites("org.example.web", "org.example.web", "per_site", "ok", []),
        BrowserSites("org.other.web", "org.other.web", "per_site", "ok", [])])
    view = device_checks_view([check], "pl", {"org.example.web": "Przeglądarka X", "com.vivaldi.browser": "Inna"})
    assert [b["name"] for b in view[0]["browsers"]] == ["Vivaldi", "Przeglądarka X", "org.other.web"]
    phone = make_cli_phone()
    phone.channels = {"com.brave.browser": {"web:https://a.pl;1": 3}}
    (brave,) = run_scan(phone).device_checks[0].browsers
    assert brave.name == "Brave"


def test_plan_view_shows_fix_plans_with_their_labels():
    phone = _site_phone()
    report = run_scan(phone)
    fixes = [f"site:{CHROME}:{SITE}", f"site_all:{SBROWSER}", "site:com.android.chrome:web:https://gone.pl;9"]
    plan = plan_order(phone, report, {}, fixes=fixes)
    view = plan_view(plan, "pl")
    json.dumps(view)
    fix, sb, blocked = view["apps"]
    assert (fix["package"], fix["level"], fix["level_label"]) == (CHROME, "fix", "Ustawienia witryn")
    assert fix["steps"] == ["Wyłączenie powiadomień: www.example.com (Chrome)"]
    assert sb["steps"] == ["Wyłączenie powiadomień wszystkich witryn (Samsung Internet)"]
    assert blocked["blocked"] is True and blocked["reason"] == "unknown_fix"
    assert blocked["reason_text"] and "unknown_fix" not in blocked["reason_text"]
    assert view["runnable"] == 2
    en = plan_view(plan, "en")["apps"][0]
    assert en["level_label"] == "Site settings"


def test_browser_removed_reason_has_texts():
    phone = _site_phone()
    plan = plan_order(phone, run_scan(phone), {CHROME: "disable"}, fixes=[f"site:{CHROME}:{SITE}"])
    blocked = next(a for a in plan_view(plan, "en")["apps"] if a["level"] == "fix")
    assert blocked["reason"] == "browser_removed" and blocked["reason_text"] != "browser_removed"


def test_firefox_site_permission_label():
    from admenot.engine.texts import step_label

    step = {"kind": "site_permission", "package": "org.mozilla.firefox",
            "params": {"origin": "https://www.example.com", "permission": "desktop-notification",
                       "capability": "2"}}
    assert step_label(step, "pl") == "Blokada powiadomień: www.example.com (Firefox)"


def test_channel_label_names_a_popular_browser_before_its_label_is_read():
    from admenot.engine.texts import step_label

    # etykieta jeszcze nieodczytana: nazwa ze skanu to sam pakiet
    step = {"kind": "channel", "package": "com.vivaldi.browser",
            "params": {"channel_id": "web:https://www.example.com;0", "importance": 0}}
    assert step_label(step, "pl", {"com.vivaldi.browser": "com.vivaldi.browser"}) \
        == "Wyłączenie powiadomień: www.example.com (Vivaldi)"


def test_history_names_a_browser_with_only_fix_actions_and_points_to_manual_undo(tmp_path):
    with Journal(tmp_path / "j.db") as journal:
        order = journal.create_order("R58", "SM-A145R", None)
        journal.save_scan(order.id, {"apps": [], "device_checks": [
            {"id": "site_notifications", "state": "review", "browsers": [
                {"package": "org.example.browser", "name": "Przeglądarka X", "mode": "per_site",
                 "read": "ok", "sites": [], "all_fix": None, "rdp_hint": False}]}]})
        chrome = {"kind": "channel", "package": CHROME, "params": {"channel_id": SITE}}
        journal.add_action(order.id, CHROME, "fix", chrome, "cmd")
        shared = {"kind": "channel", "package": SBROWSER, "params": {"channel_id": SB_CHANNEL}}
        journal.add_action(order.id, SBROWSER, "fix", shared, "cmd")
        perm = {"kind": "site_permission", "package": "org.mozilla.firefox",
                "params": {"origin": "https://www.example.com", "permission": "desktop-notification",
                           "capability": "2"}}
        journal.add_action(order.id, "org.mozilla.firefox", "fix", perm, "cmd")
        journal.add_action(order.id, "org.example.browser", "fix",
                           {**chrome, "package": "org.example.browser"}, "cmd")
        (o,) = history_view(journal, "R58", ["R58"], "pl")["orders"]
    assert {p: a["name"] for p, a in o["apps"].items()} == {
        CHROME: "Chrome", SBROWSER: "Samsung Internet", "org.mozilla.firefox": "Firefox",
        "org.example.browser": "Przeglądarka X"}
    by = {a["package"]: a for a in o["actions"]}
    assert by[CHROME]["level_label"] == "Ustawienia witryn"
    assert by[CHROME]["step_label"] == "Wyłączenie powiadomień: www.example.com (Chrome)"
    assert all(a["manual_undo"] is None for a in o["actions"])  # cofnięcie automatyczne
    assert by["org.example.browser"]["step_label"].endswith("(Przeglądarka X)")


def test_manual_undo_only_for_gone_channel(tmp_path):
    with Journal(tmp_path / "j.db") as journal:
        order = journal.create_order("R58", "SM-A145R", None)
        chrome = {"kind": "channel", "package": CHROME, "params": {"channel_id": SITE}}
        shared = {"kind": "channel", "package": SBROWSER, "params": {"channel_id": SB_CHANNEL}}
        perm = {"kind": "site_permission", "package": "org.mozilla.firefox",
                "params": {"origin": "https://www.example.com", "permission": "desktop-notification",
                           "capability": "2"}}
        ids = {}
        for name, package, step in (("site", CHROME, chrome), ("shared", SBROWSER, shared),
                                    ("perm", "org.mozilla.firefox", perm)):
            ids[name] = journal.add_action(order.id, package, "fix", step, "cmd")
            journal.set_action_status(ids[name], "done", "channel_gone")
        plain_id = journal.add_action(order.id, CHROME, "fix", chrome, "cmd")
        journal.set_action_status(plain_id, "done")
        by = {a.id: action_view(a, "pl") for a in journal.actions(order.id)}
    assert by[plain_id]["manual_undo"] is None
    assert by[ids["site"]]["manual_undo"] == "Ustawienia → Aplikacje → Chrome → Powiadomienia → www.example.com"
    assert by[ids["shared"]]["manual_undo"] == "Ustawienia → Aplikacje → Samsung Internet → Powiadomienia"
    assert by[ids["perm"]]["manual_undo"] is None
    assert "usunęła ten kanał" in by[ids["site"]]["error"]


def test_action_view_site_url_only_when_undone(tmp_path):
    with Journal(tmp_path / "j.db") as journal:
        order = journal.create_order("R58", "SM-A145R", None)
        chrome = {"kind": "channel", "package": CHROME, "params": {"channel_id": SITE}}
        shared = {"kind": "channel", "package": SBROWSER, "params": {"channel_id": SB_CHANNEL}}
        rows = {}
        for name, package, step, status in (
                ("undone", CHROME, chrome, "undone"), ("done", CHROME, chrome, "done"),
                ("shared", SBROWSER, shared, "undone"),
                ("other", CHROME, {"kind": "enabled", "package": CHROME, "params": {"enabled": "0"}},
                 "undone")):
            rows[name] = journal.add_action(order.id, package, "fix", step, "cmd")
            journal.set_action_status(rows[name], status)
        rows["skipped"] = journal.add_action(order.id, CHROME, "fix", chrome, "cmd")
        journal.set_action_status(rows["skipped"], "undone", "site_skipped")  # błąd przy statusie „undone”
        by = {n: action_view(journal.action(i), "pl")["site_url"] for n, i in rows.items()}
    assert by == {"undone": "https://www.example.com", "done": None, "shared": None, "other": None,
                  "skipped": None}


def test_cli_and_gui_texts_cover_fix_reasons_levels_and_errors():
    from admenot.engine.texts import TEXTS

    for lang in ("pl", "en"):
        texts = TEXTS[lang]
        assert {"unknown_fix", "browser_removed"} <= set(texts["reasons"])  # CLI: texts["reasons"][reason]
        assert "fix" in texts["levels"]
        assert {"user_timeout", "rdp_unavailable", "rdp_failed", "browser_removed",
                "unknown_fix"} <= set(texts["errors"])


def test_inventory_view_lists_denied_and_export_candidates():
    from admenot.app.present import inventory_view
    from admenot.engine.transfer.exports import ExportFile
    from admenot.engine.transfer.inventory import Inventory

    stamp = 1_761_598_860
    remote = "/sdcard/Kopia kontaktów/kontakty.vcf"
    inv = Inventory(None, 5, 0, 0, 7, [], {}, [], [], None, None, 0,
                    denied=frozenset({"contacts"}),
                    exports={"contacts": [ExportFile(remote, 321, stamp, "contacts", 3)]})
    view = inventory_view(inv, "pl")
    assert view["denied"] == ["contacts"]
    assert view["exports"] == {"contacts": [{
        "remote": remote, "name": "kontakty.vcf", "size": 321,
        "mtime": datetime.fromtimestamp(stamp).isoformat(timespec="seconds"), "count": 3}]}
    assert inventory_view(
        Inventory(1, 1, 0, 0, 1, [], {}, [], [], None, None, 0), "pl")["exports"] == {}


@pytest.mark.parametrize("stamp", [-1, -62_135_596_801, 10**18])
def test_inventory_view_export_mtime_out_of_range_is_none(stamp):
    """P3: ujemny albo ogromny mtime z telefonu nie wywraca widoku inwentarza."""
    from admenot.app.present import inventory_view
    from admenot.engine.transfer.exports import ExportFile
    from admenot.engine.transfer.inventory import Inventory

    inv = Inventory(None, 5, 0, 0, 7, [], {}, [], [], None, None, 0,
                    exports={"sms": [ExportFile("/sdcard/sms.xml", 10, stamp, "sms", 1)]})
    assert inventory_view(inv, "pl")["exports"]["sms"][0]["mtime"] is None
