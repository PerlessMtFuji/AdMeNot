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
                          "transfer", "unauthorized", "many", "empty"}
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
