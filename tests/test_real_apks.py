"""Prawdziwe APK z lokalnego korpusu (DEMALWARE_APK_CORPUS) — bez korpusu test się pomija."""

import json
import os
from pathlib import Path

import pytest

from demalware.engine.apk.analyze import report_from_json
from demalware.engine.apk.isolated import IsolatedAnalyzer

CORPUS = Path(os.environ.get("DEMALWARE_APK_CORPUS", "")) if os.environ.get("DEMALWARE_APK_CORPUS") else None
STORED = Path(__file__).parent / "fixtures" / "oppo-cph2271-android12-adware-t1" / "apk"
pytestmark = pytest.mark.skipif(CORPUS is None or not CORPUS.is_dir(), reason="brak DEMALWARE_APK_CORPUS")


def _packages():
    return sorted(p for p in CORPUS.iterdir() if p.is_dir() and any(p.glob("*.apk"))) if CORPUS else []


def test_every_real_apk_is_analyzed_or_explains_why():
    analyzer = IsolatedAnalyzer(120.0)
    try:
        for d in _packages():
            report = analyzer.analyze(d.name, sorted(d.glob("*.apk")))
            assert report.class_count > 0 or report.error, d.name
    finally:
        analyzer.close()


def test_current_parser_matches_stored_reports():
    """Raporty w nagraniu T1 vs dzisiejszy parser na tych samych plikach: dryf = świadoma decyzja."""
    analyzer = IsolatedAnalyzer(120.0)
    try:
        for d in _packages():
            stored = STORED / f"{d.name}.json"
            if not stored.exists():
                continue
            old = report_from_json(json.loads(stored.read_text("utf-8")))
            new = analyzer.analyze(d.name, sorted(d.glob("*.apk")))
            if old.sha256 != new.sha256:
                continue  # inna kompilacja aplikacji niż w nagraniu
            assert (new.ad_sdks, new.dynamic_code) == (old.ad_sdks, old.dynamic_code), d.name
    finally:
        analyzer.close()
