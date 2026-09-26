"""Ocena silnika na nagraniach z etykietami: python scripts/evaluate.py [katalog_nagrania ...]"""

from __future__ import annotations

import sys
from pathlib import Path

from demalware.engine.adb.fake import FakeAdb
from demalware.engine.apk.providers import StoredApkProvider
from demalware.engine.evaluation import LABELS_FILE, evaluate, format_evaluation, load_labels
from demalware.engine.session import run_scan

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def main(argv: list[str]) -> int:
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
        print(format_evaluation(evaluate(report.results, labels)))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
