"""Regresja na nagraniach z prawdziwych telefonów (tests/fixtures/<nazwa>/manifest.json)."""

from pathlib import Path

import pytest

from demalware.engine.adb.fake import FakeAdb
from demalware.engine.session import run_scan

FIXTURES = sorted(p.parent for p in (Path(__file__).parent / "fixtures").glob("*/manifest.json"))


@pytest.mark.parametrize("fixture_dir", FIXTURES, ids=[p.name for p in FIXTURES])
def test_real_capture_scans_cleanly(fixture_dir):
    report = run_scan(FakeAdb.from_capture(fixture_dir))
    failed = {n: s.error for n, s in report.collectors.items() if not s.ok}
    assert not failed, failed
    assert report.results, "no packages parsed"
    assert not any(r.verdict == "malicious" and r.trusted for r in report.results)
