import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "record_bridge_fixtures.py"
OUT = ROOT / "tests" / "fixtures" / "bridge"


def _module():
    spec = importlib.util.spec_from_file_location("record_bridge_fixtures", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bridge_fixtures_are_up_to_date():
    fresh = _module().record_all()
    assert set(fresh) == {"adware", "adware-en", "clean", "manual", "disconnect", "report",
                          "transfer", "transfer_export", "transfer_restore", "transfer_restore_tel",
                          "explorer", "unauthorized", "many", "empty"}
    for name, data in fresh.items():
        path = OUT / f"{name}.json"
        assert path.exists(), f"brak {path} — uruchom: python scripts/record_bridge_fixtures.py"
        assert json.loads(path.read_text("utf-8")) == data, (
            f"{name}.json jest nieaktualny — uruchom: python scripts/record_bridge_fixtures.py")


def test_adware_scenario_covers_the_whole_flow():
    data = _module().record_all()["adware"]
    methods = [c["method"] for c in data["calls"]]
    assert methods == ["list_devices", "history", "start_scan", "preview_plan", "execute", "history",
                       "undo", "history"]
    events = [name for c in data["calls"] for name, _ in c["events"]]
    for name in ("scan:device", "scan:done", "apk:done", "exec:order", "exec:user_wait",
                 "exec:done", "undo:done", "adb:command"):
        assert name in events, name
    clean = _module().record_all()["clean"]
    done = next(d for c in clean["calls"] for n, d in c["events"] if n == "scan:done")
    assert {a["verdict"] for a in done["scan"]["apps"]} == {"safe"}


def test_manual_scenario_goes_manual_then_partial():
    data = _module().record_all()["manual"]
    modes = [(name, detail["scan"]["apk_mode"]) for c in data["calls"] for name, detail in c["events"]
             if name in ("scan:done", "apk:manual", "apk:done")]
    assert modes == [("scan:done", "pending"), ("apk:manual", "manual"), ("apk:done", "partial")]
    done = next(d for c in data["calls"] for n, d in c["events"] if n == "apk:done")
    assert done["scan"]["on_demand"] == ["com.clean.pro.boost"]
    assert "exec:done" in [n for c in data["calls"] for n, _ in c["events"]]


def test_transfer_scenario_inventories_copies_and_lists():
    data = _module().record_all()["transfer"]
    assert [c["method"] for c in data["calls"]] == ["list_devices", "transfers", "transfer_inventory",
                                                    "start_backup", "transfers"]
    events = [name for c in data["calls"] for name, _ in c["events"]]
    for name in ("scan:device", "transfer:inventory", "transfer:progress", "transfer:done"):
        assert name in events, name
    done = next(d for c in data["calls"] for n, d in c["events"] if n == "transfer:done")
    assert done["result"]["status"] == "complete"
    assert data["calls"][-1]["result"]["copies"][0]["id"] == done["copy"]["id"]


def test_transfer_restore_scenario_plans_uploads_and_lists():
    data = _module().record_all()["transfer_restore"]
    assert [c["method"] for c in data["calls"]] == ["list_devices", "transfer_inventory", "start_backup",
                                                    "transfers", "restore_plan", "start_restore", "transfers"]
    events = {name: d for c in data["calls"] for name, d in c["events"]}
    for name in ("transfer:restore_plan", "transfer:restore_progress", "transfer:restore_done"):
        assert name in events, name
    plan = events["transfer:restore_plan"]["plan"]
    assert plan["groups"]["photos"]["rename"] == 1  # inny plik pod tą ścieżką: zapis obok
    assert {a["outcome"] for a in plan["apks"]} == {"suspicious", "malicious"}
    result = events["transfer:restore_done"]["result"]
    assert (result["status"], result["files_renamed"], result["apk_skipped"]) == ("complete", 1, 1)
    listed = data["calls"][-1]["result"]["copies"][0]["restores"]
    assert [(r["serial"], r["status"]) for r in listed] == [(result["target_serial"], "complete")]


def test_transfer_restore_tel_scenario_plans_taps_and_reports_manual_import():
    data = _module().record_all()["transfer_restore_tel"]
    assert [c["method"] for c in data["calls"]] == ["list_devices", "transfer_inventory", "start_backup",
                                                    "restore_plan", "start_restore", "transfers"]
    events = [(name, d) for c in data["calls"] for name, d in c["events"]]
    plan = next(d for n, d in events if n == "transfer:restore_plan")["tel"]
    assert (plan["contacts"]["write"], plan["sms"]["write"], plan["calls"]["write"]) == (2, 2, 1)
    taps = [d["request"] for n, d in events if n == "transfer:tap"]
    assert taps == ["sms_role_grant", None]
    tel = next(d for n, d in events if n == "transfer:restore_done")["tel"]
    assert {k: v["path"] for k, v in tel["kinds"].items()} == {
        "contacts": "app_process", "sms": "companion", "calls": "file"}
    assert tel["manual"] == [{"kind": "calls", "name": "admenot-polaczenia-20260926-143100.xml"}]
    assert tel["cleanup"]["ok"] is True and tel["status"] == "incomplete"


def test_explorer_scenario_browses_previews_and_creates():
    data = _module().record_all()["explorer"]
    calls = {(c["method"], tuple(c["args"])): c for c in data["calls"]}
    opened = calls[("explorer_open", ("R58T00TEST",))]
    counts = {p["key"]: p["count"] for p in opened["events"][-1][1]["places"]}
    assert counts["camera"] == 40 and counts["music"] == 3 and counts["movies"] == 2
    camera = calls[("explorer_list", ("/sdcard/DCIM/Camera",))]["result"]
    assert len(camera["entries"]) == 40 and len({e["mtime"] // 86_400 for e in camera["entries"]}) == 3
    meta = calls[("explorer_meta", ("/sdcard/DCIM/Camera/IMG_20260926_0000.jpg",))]["result"]["meta"]
    assert meta["gps"]["lat"] > 52
    text = calls[("explorer_text", ("/sdcard/Download/notatka.txt", False))]["result"]
    assert text["encoding"] == "cp1250" and text["text"].startswith("Zażółć")
    android = calls[("explorer_list", ("/sdcard/Android",))]["result"]["entries"]
    assert next(e for e in android if e["name"] == "data")["locked"] is True
    assert calls[("explorer_list", ("/sdcard/Android/data",))]["result"]["locked"] is True
    errors = [c["result"]["error"]["key"] for c in data["calls"] if (c["result"] or {}).get("error")]
    assert errors == ["explorer_exists"]
