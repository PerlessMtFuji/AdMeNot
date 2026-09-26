"""Progi trafności na oznaczonych nagraniach (labels.yaml + targets.yaml)."""

from pathlib import Path

import pytest
import yaml

from demalware.engine.adb.fake import FakeAdb
from demalware.engine.apk.providers import StoredApkProvider
from demalware.engine.evaluation import evaluate, format_evaluation, load_labels
from demalware.engine.session import run_scan

FIXTURES = sorted(p.parent for p in (Path(__file__).parent / "fixtures").glob("*/targets.yaml"))


@pytest.mark.parametrize("fixture_dir", FIXTURES, ids=[p.name for p in FIXTURES])
def test_labeled_fixture_meets_targets(fixture_dir):
    targets = yaml.safe_load((fixture_dir / "targets.yaml").read_text("utf-8"))
    apk_dir = fixture_dir / "apk"
    report = run_scan(FakeAdb.from_capture(fixture_dir),
                      apk=StoredApkProvider(apk_dir) if apk_dir.is_dir() else None)
    ev = evaluate(report.results, load_labels(fixture_dir))
    summary = format_evaluation(ev)
    assert len(ev.fp) <= targets["max_false_positives"], summary
    assert (ev.recall or 0.0) >= targets["min_recall"], summary
