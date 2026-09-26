import json
from datetime import datetime
from pathlib import Path

import pytest
from fakephone import make_cli_phone

from demalware.app.present import (
    app_name,
    device_card,
    history_view,
    image_uri,
    plain,
    plan_view,
    result_view,
    scan_view,
    step_view,
)
from demalware.engine.actions.executor import ExecOptions
from demalware.engine.journal.db import Journal
from demalware.engine.phones.provider import SILHOUETTE, PhoneMatch
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
        assert history_view(journal, None, [], "pl")["orders"] == []
