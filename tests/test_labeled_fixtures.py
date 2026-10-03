"""Progi trafności na oznaczonych nagraniach (labels.yaml + targets.yaml)."""

from pathlib import Path

import pytest
import yaml

from admenot.engine.adb.fake import FakeAdb
from admenot.engine.apk.providers import StoredApkProvider
from admenot.engine.evaluation import evaluate, format_evaluation, load_labels, with_install_age
from admenot.engine.session import run_scan

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
    if "min_recall" in targets:  # korpus samych czystych aplikacji (T2) mierzy tylko fałszywe alarmy
        assert (ev.recall or 0.0) >= targets["min_recall"], summary

    strict = evaluate(report.results, load_labels(fixture_dir), threshold="suspicious")
    assert len(strict.fp) <= targets.get("max_false_positives_suspicious", 0), format_evaluation(strict)


@pytest.mark.parametrize("fixture_dir", FIXTURES, ids=[p.name for p in FIXTURES])
def test_verdicts_do_not_depend_on_install_age(fixture_dir):
    """Audyt: sam upływ 14 dni nie może usuwać jedynego alarmu."""
    apk_dir = fixture_dir / "apk"
    report = run_scan(FakeAdb.from_capture(fixture_dir),
                      apk=StoredApkProvider(apk_dir) if apk_dir.is_dir() else None)
    labels = load_labels(fixture_dir)
    fresh = evaluate(report.results, labels)
    aged = evaluate(with_install_age(report, 30.0), labels)
    assert {r.facts.package for r in aged.tp} == {r.facts.package for r in fresh.tp}, \
        format_evaluation(aged)
