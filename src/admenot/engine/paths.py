"""Katalogi danych użytkownika: %LOCALAPPDATA%\\AdMeNot (poza Windows: ~/.local/share/admenot)."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "AdMeNot"
    return Path.home() / ".local" / "share" / "admenot"


def journal_path() -> Path:
    return data_dir() / "journal.db"


def backups_dir() -> Path:
    from admenot.engine.settings import load_settings  # settings importuje paths

    custom = load_settings().backups_dir
    return Path(custom) if custom else data_dir() / "backups"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def logs_dir() -> Path:
    return data_dir() / "logs"


def reports_dir() -> Path:
    return data_dir() / "reports"


def crashes_dir() -> Path:
    """Raporty błędów czekające na wysłanie (spec raportów błędów §3.2)."""
    return data_dir() / "crashes"


def incident_path(serial: str) -> Path:
    """Ostatnie nagranie incydentu (`who --watch`) telefonu o tym numerze."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in serial)
    return data_dir() / "incidents" / f"{safe}.json"


def screenshots_dir() -> Path:
    return data_dir() / "screenshots"


def screenshot_files(shot_id: int) -> tuple[Path, Path]:
    """Oryginał PNG i kopia JPG do protokołu (Plan 6b §5.1)."""
    directory = screenshots_dir()
    return directory / f"{shot_id}.png", directory / f"{shot_id}.jpg"


def phone_overrides_path() -> Path:
    return data_dir() / "phone_overrides.json"


def update_manifest_path() -> Path:
    """Ostatni poprawny manifest aktualizacji, z podpisem (spec aktualizacji §4.2)."""
    return data_dir() / "update-manifest.json"


def updates_dir() -> Path:
    """Pobrane instalatory aktualizacji."""
    return data_dir() / "updates"


PACKAGE_ASSETS = Path(__file__).resolve().parents[1] / "assets"


def assets_dir() -> Path:
    """Zbudowane dane telefonów (phones.db, phones/*.webp); ADMENOT_ASSETS nadpisuje."""
    override = os.environ.get("ADMENOT_ASSETS")
    return Path(override) if override else PACKAGE_ASSETS
