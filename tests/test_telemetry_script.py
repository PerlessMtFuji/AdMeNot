import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "telemetry.py"
ID = "3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b"


@pytest.fixture(scope="module")
def script():
    sys.path.insert(0, str(SCRIPT.parent))  # skrypt importuje `reports` z tego samego katalogu
    try:
        spec = importlib.util.spec_from_file_location("telemetry_script", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(SCRIPT.parent))


class Wrangler:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def __call__(self, args, **kw):
        self.sql.append(args[args.index("--command") + 1])
        return subprocess.CompletedProcess(args, 0, json.dumps([{"results": self.rows}]), "")


@pytest.mark.parametrize("command", [["active"], ["phones"], ["verdicts"], ["packages"],
                                     ["packages", "--left"]])
def test_queries_run_and_print(script, command, capsys):
    run = Wrangler([{"a": 1, "b": "x\x1b[31m"}])
    assert script.main([*command, "--days", "7", "--local"], run=run) == 0
    assert "-7 days" in run.sql[0] and "\x1b" not in capsys.readouterr().out


def test_delete_checks_uuid(script):
    run = Wrangler([{"install": ID}, {"install": ID}])
    assert script.main(["delete", "abc"], run=run) == 2 and run.sql == []
    assert script.main(["delete", ID], run=run) == 0
    assert f"install = '{ID}'" in run.sql[0]


def test_days_must_be_positive(script):
    with pytest.raises(SystemExit):
        script.main(["active", "--days", "0"], run=Wrangler([]))
