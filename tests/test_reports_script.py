import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reports.py"


def _module():
    spec = importlib.util.spec_from_file_location("reports_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRun:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, args, **kw):
        self.calls.append((args, kw))
        rows = self.results.pop(0) if self.results else []
        class P:
            returncode = 0
            stdout = json.dumps([{"results": rows, "success": True, "meta": {"changes": len(rows)}}])
            stderr = ""
        return P()


BODY = {"kind": "exit", "app": "0.9.3", "os": "Windows 10", "lang": "pl", "count": 2,
        "created": "2026-10-09T14:03:12", "comment": "skan",
        "context": {"call": None, "job": "scan", "screen": None, "device": {"manufacturer": "OPPO", "model": "X", "android": "14"}},
        "error": {"type": "fatal", "message": "access violation", "where": None, "trace": "Thread 0x1"},
        "log_tail": "--- log", "adb_tail": ["14:00:00\tok\t0.1s\tshell:pm list packages"]}


def test_list_new_uses_node_wrangler_and_filter(capsys):
    m = _module()
    run = FakeRun([{"id": "R-7K3Q9M", "created": "2026-10-09 14:03:15", "app": "0.9.3", "kind": "exit",
                    "error_type": "fatal", "error_where": None, "count": 2, "seen": 0}])
    assert m.main(["list", "--new"], run=run) == 0
    args, kw = run.calls[0]
    assert Path(args[0]).stem.lower() == "node"
    assert args[1].endswith("wrangler.js") and "--remote" in args and "--json" in args
    assert "WHERE seen = 0" in args[-1] and kw["cwd"] == m.SERVER
    assert "R-7K3Q9M" in capsys.readouterr().out


def test_show_prints_report_and_marks_seen(capsys):
    m = _module()
    run = FakeRun([{"id": "R-7K3Q9M", "created": "2026-10-09 14:03:15", "body": json.dumps(BODY), "seen": 0}], [])
    assert m.main(["show", "R-7K3Q9M", "--local"], run=run) == 0
    out = capsys.readouterr().out
    for part in ("access violation", "Thread 0x1", "--- log", "shell:pm list packages", "skan", "OPPO X"):
        assert part in out
    assert "--local" in run.calls[0][0]
    assert run.calls[1][0][-1] == "UPDATE reports SET seen = 1 WHERE id = 'R-7K3Q9M'"


@pytest.mark.parametrize("bad", ["R-7K3Q9", "R-7K3Q9MX", "R-ILOU00", "x'; DROP TABLE reports; --"])
def test_bad_id_is_refused_without_wrangler(bad, capsys):
    m = _module()
    run = FakeRun()
    assert m.main(["show", bad], run=run) == 2
    assert m.main(["delete", bad], run=run) == 2
    assert run.calls == []


def test_delete_reports_missing_id(capsys):
    m = _module()
    assert m.main(["delete", "R-7K3Q9M"], run=FakeRun([])) == 1
    assert "Nie ma raportu" in capsys.readouterr().err


def test_wrangler_failure_is_reported(capsys):
    m = _module()

    def failing(args, **kw):
        class P:
            returncode = 1
            stdout = ""
            stderr = "Not logged in"
        return P()

    assert m.main(["list"], run=failing) == 1
    assert "Not logged in" in capsys.readouterr().err
