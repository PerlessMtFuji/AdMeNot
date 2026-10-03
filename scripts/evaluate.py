"""Ocena silnika na nagraniach z etykietami: python scripts/evaluate.py [--ablation] [katalog_nagrania ...]"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from admenot.engine.adb.fake import FakeAdb
from admenot.engine.apk.providers import StoredApkProvider
from admenot.engine.evaluation import (
    LABELS_FILE,
    evaluate,
    format_contribution_table,
    format_evaluation,
    format_label_audit,
    format_threshold_table,
    load_label_sets,
    load_labels,
    parse_label_meta,
    with_install_age,
)
from admenot.engine.session import run_scan

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def main(argv: list[str]) -> int:
    ablation = "--ablation" in argv
    argv = [a for a in argv if a != "--ablation"]
    dirs = [Path(a) for a in argv] or sorted(p.parent for p in FIXTURES.glob(f"*/{LABELS_FILE}"))
    if not dirs:
        print(f"Brak nagrań z plikiem {LABELS_FILE}.", file=sys.stderr)
        return 1
    for d in dirs:
        labels = load_labels(d)
        if labels is None:
            print(f"{d.name}: brak {LABELS_FILE}, pomijam.", file=sys.stderr)
            continue
        apk_dir = d / "apk"
        provider = StoredApkProvider(apk_dir) if apk_dir.is_dir() else None
        report = run_scan(FakeAdb.from_capture(d), apk=provider)
        print(f"== {d.name}")
        targets_path = d / "targets.yaml"
        status = (yaml.safe_load(targets_path.read_text("utf-8")) or {}).get("labels_status")\
            if targets_path.exists() else None
        print(format_label_audit(parse_label_meta((d / LABELS_FILE).read_text("utf-8")), status))
        print(format_evaluation(evaluate(report.results, labels)))
        sets = load_label_sets(d) or {}
        print(format_threshold_table(report.results, labels, sets))
        if ablation:
            print(format_contribution_table(report, labels, sets))
            bare = run_scan(FakeAdb.from_capture(d), apk=None)
            print("  Bez analizy APK (skan bez raportów):")
            print(format_threshold_table(bare.results, labels, sets))
        aged = evaluate(with_install_age(report, 30.0), labels)
        print(f"  Stabilność (instalacja +30 dni): TP {len(evaluate(report.results, labels).tp)} → {len(aged.tp)}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
