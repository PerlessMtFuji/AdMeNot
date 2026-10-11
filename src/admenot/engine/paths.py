"""Katalogi danych użytkownika: %LOCALAPPDATA%\\AdMeNot (poza Windows: ~/.local/share/admenot)."""

from __future__ import annotations

import hashlib
import os
import re
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


def device_dir_name(serial: str) -> str:
    """Nazwa katalogu telefonu: czytelny początek numeru + skrót całego numeru.

    Numer seryjny pochodzi z ADB i trafiał wprost do ścieżki kopii: „C:/Inny”, „..” albo
    „192.0.2.1:5555” zmieniały katalog lub psuły kopię (audyt 2026-10-11, SEC-02).
    """
    readable = re.sub(r"[^A-Za-z0-9_-]", "_", serial)[:32].strip("_") or "device"
    return f"{readable}-{hashlib.sha256(serial.encode('utf-8')).hexdigest()[:12]}"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def logs_dir() -> Path:
    return data_dir() / "logs"


def reports_dir() -> Path:
    return data_dir() / "reports"


def crashes_dir() -> Path:
    """Raporty błędów czekające na wysłanie (spec raportów błędów §3.2)."""
    return data_dir() / "crashes"


def telemetry_path() -> Path:
    """Zdarzenia statystyk czekające na wysłanie (spec kroku H §6)."""
    return data_dir() / "telemetry.jsonl"


def telemetry_delete_path() -> Path:
    """ID instalacji, których dane trzeba usunąć z serwera po cofnięciu zgody (spec kroku H §6.4)."""
    return data_dir() / "telemetry_delete.json"


def incident_path(serial: str) -> Path:
    """Ostatnie nagranie incydentu (`who --watch`) telefonu o tym numerze. Nazwa jak katalog kopii
    (SEC-02): „10.0.0.5:5555” i „10.0.0.5_5555” to różne pliki. Nagrania z poprzedniej wersji
    (najwyżej 24 h) przestają być widoczne — to akceptowalne."""
    return data_dir() / "incidents" / f"{device_dir_name(serial)}.json"


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
