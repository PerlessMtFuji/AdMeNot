"""Prawdziwe APK z lokalnego korpusu (ADMENOT_APK_CORPUS) — bez korpusu test się pomija."""

import json
import os
import time
from pathlib import Path

import pytest

from admenot.engine.apk.analyze import report_from_json
from admenot.engine.apk.callgraph import AndroguardGraph, find_paths
from admenot.engine.apk.isolated import IsolatedAnalyzer
from admenot.engine.apk.manifest import read_manifest
from admenot.engine.apk.sdks import load_default_ad_sdks

CORPUS = Path(os.environ.get("ADMENOT_APK_CORPUS", "")) if os.environ.get("ADMENOT_APK_CORPUS") else None
STORED = Path(__file__).parent / "fixtures" / "oppo-cph2271-android12-adware-t1" / "apk"
pytestmark = pytest.mark.skipif(CORPUS is None or not CORPUS.is_dir(), reason="brak ADMENOT_APK_CORPUS")


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


# Pełny przebieg to 132 pakiety, ~25 s na aplikację; test bierze stały podzbiór, żeby dało się
# go uruchomić w kilka minut.
CALLGRAPH_SAMPLE = 10


def test_callgraph_runs_on_real_apks_within_limits():
    from androguard.misc import AnalyzeAPK

    prefixes = tuple(p + "." for s in load_default_ad_sdks().sdks for p in s.prefixes)
    for d in _packages()[:CALLGRAPH_SAMPLE]:
        base = d / "base.apk" if (d / "base.apk").exists() else min(d.glob("*.apk"))
        start = time.perf_counter()
        _, _, dx = AnalyzeAPK(str(base))
        components = read_manifest(base).components or ()
        package = d.name

        def origin(cls: str, package: str = package) -> str:
            return "sdk" if cls.startswith(prefixes) else "app" if cls.startswith(package) else "unknown"

        result = find_paths(AndroguardGraph(dx), components, origin_of=origin)
        assert set(result.undetermined) <= {"limit", "reflection"}, d.name
        assert all(p.entry is None or p.chain[0].startswith(p.entry + ".") for p in result.paths), d.name
        print(f"{d.name}: {time.perf_counter() - start:.1f} s, ścieżki {len(result.paths)}, "
              f"z komponentu {sum(p.entry is not None for p in result.paths)}, nie ustalono {result.undetermined}")
