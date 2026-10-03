"""Buduje bazę telefonów i katalog zdjęć (spec §4.2). Uruchamiane przy budowaniu wersji.

python scripts/build_phone_db.py [--source F:\\Szklodo] [--gplay data/supported_devices.csv]
                                 [--out src/admenot/assets]

Aktualna lista Google: https://storage.googleapis.com/play_public/supported_devices.csv
(zapisz bez zmian jako data/supported_devices.csv; plik jest w UTF-16).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from admenot.engine.paths import PACKAGE_ASSETS
from admenot.engine.phones.build import build_phone_db

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = Path(r"F:\Szklodo")
DEFAULT_GPLAY = ROOT / "data" / "supported_devices.csv"


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):  # konsola Windows (cp1250) nie zna np. „→”
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    parser = argparse.ArgumentParser(prog="build_phone_db")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--gplay", type=Path, default=DEFAULT_GPLAY)
    parser.add_argument("--out", type=Path, default=PACKAGE_ASSETS)
    args = parser.parse_args(argv)
    data = args.source / "data" / "phones_full_data.json"
    images = args.source / "public" / "assets" / "phones"
    for path in (data, images, args.gplay):
        if not path.exists():
            print(f"Brak {path}", file=sys.stderr)
            return 1
    try:
        records = json.loads(data.read_text("utf-8"))
    except ValueError as exc:
        print(f"Błąd w {data}: {exc}", file=sys.stderr)
        return 1
    try:
        s = build_phone_db(records, images, args.gplay, args.out)
    except FileNotFoundError as exc:
        print(f"Brak zdjęć: {exc}", file=sys.stderr)
        return 1
    print(f"Telefony: {s.phones} (pominięte bez nazwy: {s.skipped}), ze zdjęciem: {s.with_image}")
    print(f"Kody modeli: {s.codes} (konflikty: {s.code_conflicts}), nazwy: {s.names}, "
          f"lista Google: {s.gplay_rows}")
    print(f"Zdjęcia: skopiowane {s.images_copied}, usunięte {s.images_removed} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
