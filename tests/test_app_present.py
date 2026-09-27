import json
from datetime import datetime
from pathlib import Path

import pytest
from fakephone import make_cli_phone

from demalware.app.present import (
    app_name,
    app_view,
    device_card,
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
from demalware.engine.actions.executor import ExecOptions
from demalware.engine.facts import AppFacts
from demalware.engine.journal.db import Journal
from demalware.engine.phones.provider import SILHOUETTE, PhoneMatch
from demalware.engine.rules.model import Finding
from demalware.engine.session import run_scan
from demalware.engine.workflow import execute_order, plan_order, start


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
    assert boost["default_level"] == "remove" and boost["is_admin"] is True
    assert 1 <= len(boost["problems"]) <= 3 and len(set(boost["problems"])) == len(boost["problems"])
    assert boost["findings"][0]["weight"] >= boost["findings"][-1]["weight"]
    assert apps["com.whatsapp"]["default_level"] is None
    counts = view["counts"]
    assert counts["malicious"] >= 1 and counts["admins"] == 1 and counts["total"] == len(apps)
    assert view["collectors"]["ok"] == view["collectors"]["total"]
    assert scan_view(report, "en")["apps"][0]["verdict_label"] in ("Malicious", "Suspicious")


def test_device_card_with_and_without_photo(synthetic_adb, tmp_path):
    report = run_scan(synthetic_adb)
    card = device_card(report.device, None)
    assert card["image"].startswith("data:image/svg+xml;base64,")
    assert card["name"] == "samsung SM-A145R" and card["match"] is None and card["sdk"] == 34
    photo = tmp_path / "a14.webp"
    photo.write_bytes(b"RIFF....WEBP")
    match = PhoneMatch("exact", "model_code", photo, None, "SM-A145R")
    card = device_card(report.device, match)
    assert card["image"].startswith("data:image/webp;base64,")
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
    assert [severity(w) for w in (25, 20, 19, 10, 9)] == ["bad", "bad", "warn", "warn", "neutral"]
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

    names = {p: app_name(f, p) for p, f in plan.facts.items()}
    event = {"type": "step", "action_id": 3, "package": "com.wlive.forecast",
             "step": {"kind": "enabled", "package": "com.wlive.forecast", "params": {"enabled": "0"}},
             "status": "failed", "error": "security"}
    sv = step_view(event, "pl", "Xiaomi", names)
    assert {k: sv[k] for k in ("action_id", "package", "name", "kind", "label", "status")} == {
        "action_id": 3, "package": "com.wlive.forecast", "name": names["com.wlive.forecast"],
        "kind": "enabled", "label": "wyłączenie aplikacji", "status": "failed"}
    assert "zabezpieczeń" in sv["error"]

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
        assert hv["devices"] == [{"serial": phone.serial, "model": o["model"]}]
        empty = history_view(journal, None, [], "pl")
        assert empty["orders"] == [] and empty["devices"] == []


def test_app_view_passes_icon():
    from demalware.engine.scoring import AppResult

    facts = AppFacts("com.x", icon="data:image/png;base64,iVBORw0KGgo=")
    view = app_view(AppResult(facts, [], 0, "safe", False, False), "pl")
    assert view["icon"] == "data:image/png;base64,iVBORw0KGgo="
