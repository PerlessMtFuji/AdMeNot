"""Odczyt statystyk użycia z D1 (spec kroku H §8): active | phones | verdicts | packages | delete.

Jak `reports.py`: wrangler z `server/node_modules`, zalogowany autor. Do SQL trafiają tylko
liczba dni (int) i ID instalacji sprawdzony wzorcem.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence

from reports import ReportsError, Run, _safe, run_sql

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")


def _since(days: int) -> str:
    return f"created >= datetime('now', '-{int(days)} days')"


QUERIES = {
    "active": lambda d: (
        "SELECT date(created) AS day, COUNT(DISTINCT install) AS installs, "
        "group_concat(DISTINCT app) AS versions FROM events "
        f"WHERE type = 'start' AND {_since(d)} GROUP BY day ORDER BY day DESC"),
    "phones": lambda d: (
        "SELECT json_extract(body, '$.device.manufacturer') AS maker, "
        "json_extract(body, '$.device.model') AS model, json_extract(body, '$.device.android') AS android, "
        "COUNT(*) AS scans, COUNT(DISTINCT install) AS installs FROM events "
        f"WHERE type = 'scan' AND json_extract(body, '$.apk_stage') = 0 AND {_since(d)} "
        "GROUP BY maker, model, android ORDER BY scans DESC LIMIT 100"),
    "verdicts": lambda d: (
        "SELECT type, COUNT(*) AS events, "
        "SUM(json_extract(body, '$.verdicts.malicious')) AS malicious, "
        "SUM(json_extract(body, '$.verdicts.suspicious')) AS suspicious, "
        "SUM(json_extract(body, '$.verdicts.review')) AS review, "
        "SUM(json_extract(body, '$.levels.silence')) AS silence, "
        "SUM(json_extract(body, '$.levels.disable')) AS disable, "
        "SUM(json_extract(body, '$.levels.remove')) AS remove, "
        "SUM(json_extract(body, '$.sources.manual')) AS manual, "
        "SUM(json_extract(body, '$.apps')) AS apps FROM events "
        f"WHERE type IN ('scan', 'repair', 'undo') AND json_extract(body, '$.apk_stage') IS NOT 1 "
        f"AND {_since(d)} GROUP BY type"),
    "packages": lambda d: (
        "SELECT json_extract(p.value, '$.package') AS package, json_extract(p.value, '$.level') AS level, "
        "json_extract(p.value, '$.source') AS source, COUNT(*) AS times, COUNT(DISTINCT e.install) AS installs "
        "FROM events e, json_each(e.body, '$.packages') p "
        f"WHERE e.type = 'repair' AND e.{_since(d)} GROUP BY package, level, source ORDER BY times DESC LIMIT 100"),
    "left": lambda d: (
        "SELECT json_extract(p.value, '$.package') AS package, json_extract(p.value, '$.verdict') AS verdict, "
        "COUNT(*) AS times FROM events s, json_each(s.body, '$.packages') p "
        f"WHERE s.type = 'scan' AND s.{_since(d)} AND NOT EXISTS ("
        "SELECT 1 FROM events r, json_each(r.body, '$.packages') q WHERE r.type = 'repair' "
        "AND r.install = s.install AND json_extract(r.body, '$.session') = json_extract(s.body, '$.session') "
        "AND json_extract(q.value, '$.package') = json_extract(p.value, '$.package')) "
        "GROUP BY package, verdict ORDER BY times DESC LIMIT 100"),
}


def _print(rows: list[dict]) -> None:
    if not rows:
        print("Brak danych.")
        return
    print("\t".join(rows[0]))
    for r in rows:
        print(_safe("\t".join("" if v is None else str(v) for v in r.values())))


def _days(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("co najmniej 1")
    return value


def main(argv: Sequence[str] | None = None, run: Run = subprocess.run) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description="Statystyki użycia AdMeNot (D1)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, days in (("active", 30), ("phones", 90), ("verdicts", 90), ("packages", 90)):
        p = sub.add_parser(name)
        p.add_argument("--days", type=_days, default=days)
    sub.choices["packages"].add_argument("--left", action="store_true",
                                         help="oznaczone w skanie, a nieruszone w naprawie")
    sub.add_parser("delete").add_argument("install")
    for p in sub.choices.values():
        p.add_argument("--local", action="store_true", help="lokalna D1 z wrangler dev")
    args = parser.parse_args(argv)
    try:
        if args.command == "delete":
            if not UUID_RE.fullmatch(args.install):
                print(f"Zły identyfikator instalacji: {args.install!r}.", file=sys.stderr)
                return 2
            rows = run_sql(f"DELETE FROM events WHERE install = '{args.install}' RETURNING install",
                           args.local, run)
            print(f"Usunięto {len(rows)} zdarzeń.")
            return 0
        key = "left" if args.command == "packages" and args.left else args.command
        _print(run_sql(QUERIES[key](args.days), args.local, run))
        return 0
    except ReportsError as exc:
        print(f"Błąd wranglera: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
