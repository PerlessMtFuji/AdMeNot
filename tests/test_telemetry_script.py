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


def _db(*events):
    """Prawdziwa tabela z migracji serwera; zapytania skryptu wykonywane przez SQLite."""
    import sqlite3

    db = sqlite3.connect(":memory:")
    sql = (ROOT / "server" / "migrations" / "0003_telemetry.sql").read_text("utf-8")
    db.executescript(sql.replace("UPDATE schema_info SET version = 3;", ""))
    for e in events:
        db.execute("INSERT INTO events VALUES (?, datetime('now'), ?, ?, ?, ?)",
                   (ID, "2026-10-10T13:00:00Z", e["type"], "0.9.2", json.dumps(e)))
    return db


def _scan(session, apk_stage, review, packages):
    return {"type": "scan", "session": session, "apk_stage": apk_stage, "apps": 10,
            "verdicts": {"malicious": 0, "suspicious": 0, "review": review},
            "packages": [{"package": p, "verdict": "review"} for p in packages]}


def test_verdicts_and_left_use_the_final_scan_of_a_session(script):
    db = _db(_scan("s1", False, 1, ["a.a"]), _scan("s1", True, 3, ["a.a", "b.b", "c.c"]),
             _scan("s2", False, 2, ["d.d", "e.e"]),
             {"type": "repair", "session": "s1", "packages": [{"package": "b.b"}]})
    cur = db.execute(script.QUERIES["verdicts"](30))
    names = [c[0] for c in cur.description]
    scan = next(dict(zip(names, r)) for r in cur.fetchall() if r[0] == "scan")
    assert (scan["events"], scan["review"]) == (2, 5)  # s1 po APK (3) + s2 bez APK (2)
    left = {r[0] for r in db.execute(script.QUERIES["left"](30))}
    assert left == {"a.a", "c.c", "d.d", "e.e"}
