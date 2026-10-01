"""Pomiar analizy na prawdziwych APK: python scripts/apk_bench.py <korpus> [timeout_s]

Korpus: katalog <pakiet>/<*.apk>. Wynik: czas, liczba klas, błędy — bez wpływu na wagi."""

from __future__ import annotations

import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from demalware.engine.apk.isolated import IsolatedAnalyzer


@dataclass(frozen=True)
class BenchRow:
    package: str
    seconds: float
    files: int
    class_count: int
    error: str | None


def bench(corpus: Path, timeout_s: float) -> list[BenchRow]:
    rows = []
    analyzer = IsolatedAnalyzer(timeout_s)
    try:
        for d in sorted(p for p in corpus.iterdir() if p.is_dir()):
            paths = sorted(d.glob("*.apk"))
            if not paths:
                continue
            start = time.perf_counter()
            report = analyzer.analyze(d.name, paths)
            rows.append(BenchRow(d.name, time.perf_counter() - start, len(paths),
                                 report.class_count, report.error))
    finally:
        analyzer.close()
    return rows


def format_bench(rows: list[BenchRow]) -> str:
    out = [f"{'s':>7}  {'pliki':>5}  {'klasy':>7}  pakiet  [błąd]"]
    out += [f"{r.seconds:7.2f}  {r.files:>5}  {r.class_count:>7}  {r.package}"
            + (f"  [{r.error}]" if r.error else "") for r in rows]
    if rows:
        times = [r.seconds for r in rows]
        timeouts = sum(1 for r in rows if r.error and r.error.startswith("timeout"))
        errors = sum(1 for r in rows if r.error)
        out.append(f"aplikacji: {len(rows)}, mediana: {statistics.median(times):.2f} s, "
                   f"maks.: {max(times):.2f} s, błędy: {errors}, w tym timeouty: {timeouts}")
    return "\n".join(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    print(format_bench(bench(Path(sys.argv[1]), float(sys.argv[2]) if len(sys.argv) > 2 else 60.0)))
