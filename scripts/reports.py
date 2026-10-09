"""Przegląd raportów błędów z D1 (spec raportów błędów §7): list | show | delete.

Woła wranglera z `server/node_modules` przez `node` (bez `npx.cmd` — cmd.exe przetwarzałby znaki SQL)
z zalogowaniem autora do Cloudflare. Jedyne wejście w SQL to numer raportu sprawdzony wzorcem.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
WRANGLER = SERVER / "node_modules" / "wrangler" / "bin" / "wrangler.js"
ID_RE = re.compile(r"R-[0-9A-HJKMNP-TV-Z]{6}")
# znaki sterujące poza \n i \t (ESC, BEL, C1…) — treść raportu nie może sterować terminalem
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

Run = Callable[..., Any]


class ReportsError(Exception):
    pass


def run_sql(sql: str, local: bool = False, run: Run = subprocess.run) -> list[dict[str, Any]]:
    node = shutil.which("node") or "node"
    args = [node, str(WRANGLER), "d1", "execute", "admenot", "--local" if local else "--remote",
            "--json", "--command", sql]
    proc = run(args, cwd=SERVER, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise ReportsError((proc.stderr or proc.stdout or "wrangler").strip())
    try:
        data = json.loads(proc.stdout[proc.stdout.index("["):])
        return list(data[0]["results"])
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ReportsError(f"nieczytelna odpowiedź wranglera: {exc}") from None


def _safe(value: Any) -> str:
    return _CONTROL.sub("", str(value))


def _check(report_id: str) -> str:
    if not ID_RE.fullmatch(report_id):
        raise ValueError(report_id)
    return report_id


def cmd_list(new: bool, limit: int, local: bool, run: Run) -> int:
    where = "WHERE seen = 0 " if new else ""
    rows = run_sql("SELECT id, created, app, kind, error_type, error_where, "
                   "json_extract(body, '$.count') AS count, seen FROM reports "
                   f"{where}ORDER BY created DESC LIMIT {int(limit)}", local, run)
    if not rows:
        print("Brak raportów.")
    for r in rows:
        mark = " " if r["seen"] else "*"
        print(_safe(f"{mark} {r['id']}  {r['created']}  {r['app']:<8} {r['kind']:<6} "
                    f"x{r['count'] or 1:<3} {r['error_type']}  {r['error_where'] or ''}"))
    return 0


def _section(title: str, text: str | None) -> None:
    if text:
        print(f"\n## {title}\n{_safe(text)}")


def cmd_show(report_id: str, local: bool, run: Run) -> int:
    rows = run_sql(f"SELECT id, created, body, seen FROM reports WHERE id = '{report_id}'", local, run)
    if not rows:
        print(f"Nie ma raportu {report_id}.", file=sys.stderr)
        return 1
    body = json.loads(rows[0]["body"])
    ctx, err = body.get("context") or {}, body.get("error") or {}
    device = ctx.get("device") or {}
    print(_safe(f"{report_id}  {rows[0]['created']} UTC  {body.get('kind')}  x{body.get('count')}"))
    print(_safe(f"AdMeNot {body.get('app')}  {body.get('os')}  język {body.get('lang')}  (u użytkownika: {body.get('created')})"))
    print(_safe(f"Kontekst: call={ctx.get('call')} job={ctx.get('job')} screen={ctx.get('screen')}"))
    if device:
        print(_safe(f"Telefon: {device.get('manufacturer')} {device.get('model')}, Android {device.get('android')}"))
    print(_safe(f"Błąd: {err.get('type')}: {err.get('message')}  [{err.get('where') or '-'}]"))
    _section("Opis od użytkownika", body.get("comment"))
    _section("Traceback", err.get("trace"))
    _section("Log programu", body.get("log_tail"))
    _section("Polecenia ADB", "\n".join(body.get("adb_tail") or []))
    run_sql(f"UPDATE reports SET seen = 1 WHERE id = '{report_id}'", local, run)
    return 0


def cmd_delete(report_id: str, local: bool, run: Run) -> int:
    rows = run_sql(f"DELETE FROM reports WHERE id = '{report_id}' RETURNING id", local, run)
    if not rows:
        print(f"Nie ma raportu {report_id}.", file=sys.stderr)
        return 1
    print(f"Usunięto {report_id}.")
    return 0


def main(argv: Sequence[str] | None = None, run: Run = subprocess.run) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # konsola bez UTF-8 nie wywróci wydruku raportu
    parser = argparse.ArgumentParser(description="Raporty błędów AdMeNot (D1)")
    sub = parser.add_subparsers(dest="command", required=True)
    lst = sub.add_parser("list")
    lst.add_argument("--new", action="store_true")
    lst.add_argument("--limit", type=int, default=50)
    for name in ("show", "delete"):
        sub.add_parser(name).add_argument("id")
    for p in sub.choices.values():
        p.add_argument("--local", action="store_true", help="lokalna D1 z wrangler dev")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return cmd_list(args.new, args.limit, args.local, run)
        try:
            report_id = _check(args.id)
        except ValueError:
            print(f"Zły numer raportu: {args.id!r} (wzór R-XXXXXX).", file=sys.stderr)
            return 2
        if args.command == "show":
            return cmd_show(report_id, args.local, run)
        return cmd_delete(report_id, args.local, run)
    except ReportsError as exc:
        print(f"Błąd wranglera: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
