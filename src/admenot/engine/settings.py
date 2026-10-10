"""Ustawienia programu: %LOCALAPPDATA%\\AdMeNot\\settings.json (spec §9.2 ekran 6, §9.3, §11).

`Settings` to klucze ekranu ustawień (`KEYS`), `ServiceInfo` to sekcja `service` (dane serwisu
do protokołu). Każdy zapis zmienia tylko swoją część pliku, reszta zostaje.
Uszkodzony plik nie blokuje startu: wartości domyślne, a zły plik zostaje jako `.bad`.
Plik ma pole `schema` (brak = 0). `MIGRATIONS[i]` podnosi dane z wersji i do i+1; odczyt stosuje
brakujące migracje w pamięci, zapis zapisuje wynik z `schema = len(MIGRATIONS)`. Pliku z nowszej
wersji programu nie nadpisujemy (`SettingsTooNew`) — tak jak dziennik (`journal/db.py`).
"""

from __future__ import annotations

import json
import locale
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from admenot.engine.paths import settings_path

LANGS = ("pl", "en")
MODES = ("simple", "expert")
THEMES = ("system", "light", "dark")
SELECT_LEVELS = ("silence", "disable", "remove")  # poziomy akcji (actions/planner.LEVELS)
KEYS = ("lang", "mode", "adb_path", "backups_dir", "theme", "mirror_auto",
        "apk_cache_limit_gb", "apk_cache_clear_after_repair", "select_level",
        "check_updates", "dismissed_update", "last_run_version")
# Klucze zmieniane tylko przez dedykowane funkcje (ostrzeżenie, zgody telemetrii), nigdy z ekranu
# ustawień: UI nie może podstawić własnego ID instalacji ani „zaakceptować” ostrzeżenia bokiem.
INTERNAL_KEYS = ("welcome_version", "welcome_at", "telemetry", "telemetry_packages",
                 "telemetry_id", "telemetry_at", "telemetry_start_day",
                 "donate_count", "donate_shown_at", "donate_off")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOGO_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".svg": "image/svg+xml",
}
MAX_LOGO_BYTES = 1_000_000
SCHEMA_KEY = "schema"


def _v1(data: dict[str, Any]) -> dict[str, Any]:
    return data  # wersja 1 = format sprzed wersjonowania


# Tylko dopisujemy na końcu — nigdy nie zmieniamy ani nie usuwamy istniejących migracji.
MIGRATIONS: tuple[Callable[[dict[str, Any]], dict[str, Any]], ...] = (_v1,)


class SettingsTooNew(Exception):
    def __init__(self, found: int, known: int) -> None:
        super().__init__(f"Ustawienia pochodzą z nowszej wersji AdMeNot (schemat {found}, "
                         f"ten program zna {known}) — zaktualizuj program.")
        self.found = found
        self.known = known


@dataclass(frozen=True)
class Settings:
    lang: str | None = None  # None = jeszcze nie wybrany (pierwsze uruchomienie)
    mode: str = "simple"
    adb_path: str | None = None
    backups_dir: str | None = None
    theme: str = "system"
    mirror_auto: bool = False
    apk_cache_limit_gb: int = 10  # górna granica; działa tyle, ile mieści dysk (apk/cache.py)
    apk_cache_clear_after_repair: bool = False
    select_level: str = "silence"  # akcja po zaznaczeniu aplikacji, dla której silnik nic nie proponuje
    check_updates: bool = True  # wyłączone = zero zapytań o aktualizacje (spec aktualizacji §4.3)
    dismissed_update: str | None = None  # wersja ukryta krzyżykiem na banerze
    last_run_version: str | None = None  # komunikat „Zaktualizowano” po zmianie wersji
    welcome_version: int | None = None  # zaakceptowana wersja ostrzeżenia (welcome.WELCOME_VERSION)
    welcome_at: str | None = None
    telemetry: bool = False  # zgoda na statystyki (spec kroku H §4)
    telemetry_packages: bool = False  # osobna zgoda na nazwy pakietów
    telemetry_id: str | None = None  # UUIDv4 instalacji; istnieje tylko przy telemetry=True
    telemetry_at: str | None = None
    telemetry_start_day: str | None = None  # dzień (UTC) ostatniego zdarzenia „start”
    donate_count: int = 0  # udane zlecenia od ostatniego przypomnienia o wsparciu (spec kroku J §4)
    donate_shown_at: str | None = None  # dzień (lokalny) ostatniego przypomnienia
    donate_off: bool = False  # „Już wspieram, nie pokazuj więcej”


@dataclass(frozen=True)
class ServiceInfo:
    name: str | None = None
    address: str | None = None
    phone: str | None = None
    logo: Path | None = None


class LogoError(ValueError):
    def __init__(self, key: str) -> None:  # missing | type | size
        super().__init__(key)
        self.key = key


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        try:
            shutil.copyfile(path, path.with_name(path.name + ".bad"))
        except OSError:
            pass
        return {}
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)


def _schema(data: dict[str, Any]) -> int:
    value = data.get(SCHEMA_KEY, 0)
    valid = isinstance(value, int) and not isinstance(value, bool) and value >= 0
    return value if valid else 0


def _load(path: Path) -> dict[str, Any]:
    """Dane po brakujących migracjach; plik z nowszej wersji czytamy bez zmian (znane klucze)."""
    data = _read(path)
    for step in MIGRATIONS[_schema(data):]:
        data = step(data)
    return data


def _save(path: Path, update: Callable[[dict[str, Any]], None]) -> None:
    found = _schema(_read(path))
    if found > len(MIGRATIONS):
        raise SettingsTooNew(found, len(MIGRATIONS))
    data = _load(path)
    update(data)
    data[SCHEMA_KEY] = len(MIGRATIONS)
    _write(path, data)


def _valid(key: str, value: Any) -> bool:
    if key == "donate_count":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if key == "donate_off":
        return isinstance(value, bool)
    if key in ("telemetry_start_day", "donate_shown_at"):
        return value is None or (isinstance(value, str) and DAY_RE.match(value) is not None)
    if key in ("telemetry", "telemetry_packages"):
        return isinstance(value, bool)
    if key == "welcome_version":
        return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 1)
    if key == "telemetry_id":
        return value is None or (isinstance(value, str) and UUID_RE.match(value) is not None)
    if key in ("mirror_auto", "apk_cache_clear_after_repair", "check_updates"):
        return isinstance(value, bool)
    if key == "apk_cache_limit_gb":
        # bool to podklasa int — True nie może znaczyć „1 GB"
        return isinstance(value, int) and not isinstance(value, bool) and value >= 1
    if key == "lang":
        return value in LANGS
    if key == "mode":
        return value in MODES
    if key == "theme":
        return value in THEMES
    if key == "select_level":
        return value in SELECT_LEVELS
    return value is None or (isinstance(value, str) and value.strip() != "")


def load_settings(path: Path | None = None) -> Settings:
    data = _load(path or settings_path())
    return Settings(**{k: data[k] for k in KEYS + INTERNAL_KEYS if k in data and _valid(k, data[k])})


def save_settings(changes: dict[str, Any], path: Path | None = None) -> Settings:
    path = path or settings_path()
    unknown = sorted(set(changes) - set(KEYS))
    bad = sorted(k for k, v in changes.items() if k in KEYS and not _valid(k, v))
    if unknown or bad:
        raise ValueError(f"unknown={unknown} bad={bad}")
    _save(path, lambda data: data.update(changes))
    return load_settings(path)


def save_internal(changes: dict[str, Any], path: Path | None = None) -> Settings:
    """Zapis kluczy wewnętrznych (`INTERNAL_KEYS`) — tylko z `welcome`, `app.telemetry` i `donate`."""
    path = path or settings_path()
    unknown = sorted(set(changes) - set(INTERNAL_KEYS))
    bad = sorted(k for k, v in changes.items() if k in INTERNAL_KEYS and not _valid(k, v))
    if unknown or bad:
        raise ValueError(f"unknown={unknown} bad={bad}")
    _save(path, lambda data: data.update(changes))
    return load_settings(path)


def system_lang() -> str:
    name = (locale.getlocale()[0] or "").lower()
    return "pl" if name.startswith(("pl", "polish")) else "en"


def effective_lang(settings: Settings) -> str:
    return settings.lang or system_lang()


def _text(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    return (value.strip() or None) if isinstance(value, str) else None


def load_service(path: Path | None = None) -> ServiceInfo:
    raw = _load(path or settings_path()).get("service")
    if not isinstance(raw, dict):
        return ServiceInfo()
    logo = _text(raw, "logo")
    return ServiceInfo(_text(raw, "name"), _text(raw, "address"), _text(raw, "phone"),
                       Path(logo) if logo else None)


def save_service(info: ServiceInfo, path: Path | None = None) -> None:
    service = {"name": info.name, "address": info.address, "phone": info.phone,
               "logo": str(info.logo) if info.logo else None}
    _save(path or settings_path(), lambda data: data.update(service=service))  # KEYS zostają


def check_logo(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise LogoError("missing")
    if path.suffix.lower() not in LOGO_TYPES:
        raise LogoError("type")
    if path.stat().st_size > MAX_LOGO_BYTES:
        raise LogoError("size")
    return path
