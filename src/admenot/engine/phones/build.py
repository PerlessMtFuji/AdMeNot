"""Budowa `phones.db` i katalogu zdjęć z danych Szklodo (spec §4.2)."""

from __future__ import annotations

import csv
import io
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from admenot.engine.phones.names import (
    canonical_brand,
    norm_name,
    parse_battery_mah,
    parse_display_in,
    parse_year,
    record_slugs,
    split_codes,
    with_brand,
)

SCHEMA_VERSION = 1
DB_NAME = "phones.db"
IMAGES_DIR = "phones"

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE phones(
    slug TEXT PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL,
    year INTEGER, display_in REAL, battery_mah INTEGER);
CREATE TABLE model_codes(code TEXT PRIMARY KEY, slug TEXT NOT NULL REFERENCES phones(slug));
CREATE TABLE market_names(norm_name TEXT PRIMARY KEY, slug TEXT NOT NULL REFERENCES phones(slug));
CREATE TABLE gplay(
    brand TEXT NOT NULL, device TEXT NOT NULL COLLATE NOCASE,
    model TEXT NOT NULL COLLATE NOCASE, market_name TEXT NOT NULL);
CREATE INDEX gplay_device_model ON gplay(device, model);
"""


@dataclass
class BuildStats:
    phones: int = 0
    skipped: int = 0
    with_image: int = 0
    codes: int = 0
    code_conflicts: int = 0
    names: int = 0
    gplay_rows: int = 0
    images_copied: int = 0
    images_removed: int = 0


def read_gplay_csv(path: Path) -> list[tuple[str, str, str, str]]:
    """`supported_devices.csv` od Google (UTF-16 z BOM albo UTF-8) → (marka, device, model, nazwa)."""
    raw = path.read_bytes()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    reader = csv.reader(io.StringIO(raw.decode(encoding), newline=""))
    next(reader, None)  # Retail Branding, Marketing Name, Device, Model
    rows = []
    for row in reader:
        if len(row) < 4:
            continue
        brand, market, device, model = (cell.strip() for cell in row[:4])
        if market and device and model:
            rows.append((brand, device, model, market))
    return rows


def build_phone_db(records: list[dict], images_src: Path, gplay_csv: Path | None,
                   out_dir: Path) -> BuildStats:
    if not images_src.is_dir():
        raise FileNotFoundError(images_src)  # pusty katalog źródłowy skasowałby zdjęcia
    slugs = record_slugs(records)
    if not any((images_src / f"{slug}.webp").is_file() for slug in slugs if slug):
        # Katalog istnieje, ale nie ma w nim żadnego znanego zdjęcia: to źle wskazane
        # źródło, a nie „usuń wszystkie zdjęcia” — nic w out_dir nie może się zmienić.
        raise FileNotFoundError(f"brak zdjęć w {images_src}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = BuildStats()
    tmp = out_dir / f"{DB_NAME}.tmp"
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(SCHEMA)
        _fill(con, records, slugs, gplay_csv, stats)
        con.commit()
        con.close()
        _sync_images(slugs, images_src, out_dir / IMAGES_DIR, stats)
    except BaseException:
        con.close()  # bezpieczne, jeśli już zamknięte powyżej
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, out_dir / DB_NAME)
    return stats


def _fill(con: sqlite3.Connection, records: list[dict], slugs: list[str | None],
          gplay_csv: Path | None, stats: BuildStats) -> None:
    for record, slug in zip(records, slugs, strict=True):
        if slug is None:
            stats.skipped += 1
            continue
        name = record["name"].strip()
        brand = (record.get("manufacturer") or name.split()[0]).strip()
        con.execute("INSERT INTO phones VALUES (?, ?, ?, ?, ?, ?)", (
            slug, name, brand, parse_year(record.get("year")),
            parse_display_in(record.get("displaysize")),
            parse_battery_mah(record.get("batdescription1")),
        ))
        stats.phones += 1
        for code in split_codes(record.get("models")):
            if _insert(con, "model_codes", code, slug):
                stats.codes += 1
            else:
                stats.code_conflicts += 1
        for norm in (norm_name(name), with_brand(canonical_brand(brand), name)):
            stats.names += _insert(con, "market_names", norm, slug)
    # Adres GSMArena bywa pełniejszy niż `name`: „Galaxy A57” ma slug samsung-galaxy-a57-5g.
    for slug in slugs:
        if slug:
            stats.names += _insert(con, "market_names", norm_name(slug), slug)
    if gplay_csv is not None:
        rows = read_gplay_csv(gplay_csv)
        con.executemany("INSERT INTO gplay VALUES (?, ?, ?, ?)", rows)
        stats.gplay_rows = len(rows)
    con.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("schema_version", str(SCHEMA_VERSION)),
        ("built_at", datetime.now().isoformat(timespec="seconds")),
    ])


def _insert(con: sqlite3.Connection, table: str, key: str, slug: str) -> bool:
    if not key:
        return False
    return con.execute(f"INSERT OR IGNORE INTO {table} VALUES (?, ?)", (key, slug)).rowcount == 1


def _sync_images(slugs: list[str | None], src_dir: Path, dst_dir: Path, stats: BuildStats) -> None:
    """Kopiuje tylko pełne zdjęcia rekordów (bez `-sm`), pomija niezmienione, usuwa zbędne."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    wanted: set[str] = set()
    for slug in slugs:
        if slug is None:
            continue
        src = src_dir / f"{slug}.webp"
        if not src.is_file():
            continue
        wanted.add(src.name)
        stats.with_image += 1
        dst = dst_dir / src.name
        s = src.stat()
        if dst.is_file() and dst.stat().st_size == s.st_size and dst.stat().st_mtime >= s.st_mtime:
            continue
        shutil.copy2(src, dst)
        stats.images_copied += 1
    for old in dst_dir.glob("*.webp"):
        if old.name not in wanted:
            old.unlink()
            stats.images_removed += 1
