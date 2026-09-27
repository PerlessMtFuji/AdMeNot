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
    assert set(fresh) == {"adware", "clean", "disconnect", "unauthorized", "many", "empty"}
    for name, data in fresh.items():
        path = OUT / f"{name}.json"
        assert path.exists(), f"brak {path} — uruchom: python scripts/record_bridge_fixtures.py"
        assert json.loads(path.read_text("utf-8")) == data, (
            f"{name}.json jest nieaktualny — uruchom: python scripts/record_bridge_fixtures.py")


def test_adware_scenario_covers_the_whole_flow():
    data = _module().record_all()["adware"]
    methods = [c["method"] for c in data["calls"]]
    assert methods == ["list_devices", "start_scan", "preview_plan", "execute", "history", "undo",
                       "history"]
    events = [name for c in data["calls"] for name, _ in c["events"]]
    for name in ("scan:device", "scan:done", "apk:done", "exec:order", "exec:admin_wait",
                 "exec:done", "undo:done", "adb:command"):
        assert name in events, name
    clean = _module().record_all()["clean"]
    done = next(d for c in clean["calls"] for n, d in c["events"] if n == "scan:done")
    assert {a["verdict"] for a in done["scan"]["apps"]} == {"safe"}
