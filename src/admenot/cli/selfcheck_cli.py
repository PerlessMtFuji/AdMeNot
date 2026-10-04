"""`admenot selfcheck`: czy program ma wszystkie swoje pliki (spec wydania §5).

Bez telefonu sprawdza to, co spakowany program musi zabrać ze sobą — każdy element przez tę
samą ścieżkę kodu, której używa skan (próba pakowania: brak danych androguarda psuł analizę
manifestu po cichu). Kod 0 = wszystko OK, 1 = czegoś brakuje.
"""

from __future__ import annotations

import importlib
import importlib.util
import sqlite3
import tempfile
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from admenot.app import main as app_main
from admenot.engine import paths
from admenot.engine.allowlist.trust import load_default_trust_list, load_protected_list
from admenot.engine.apk.iocs import load_default_iocs
from admenot.engine.apk.sdks import load_default_ad_sdks
from admenot.engine.phones.build import DB_NAME, IMAGES_DIR
from admenot.engine.rules.engine import load_default_ruleset
from admenot.engine.tools import tools_dir

STATUS = {"pl": ("OK", "BRAK"), "en": ("OK", "MISSING")}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


def _file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(str(path))


def _phones_db() -> None:
    db = paths.assets_dir() / DB_NAME
    _file(db)
    with closing(sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)) as con:
        con.execute("SELECT count(*) FROM meta").fetchone()


def _phone_images() -> None:
    images = paths.assets_dir() / IMAGES_DIR
    if not images.is_dir():
        raise FileNotFoundError(str(images))


def androguard_resources() -> Path:
    spec = importlib.util.find_spec("androguard.core.resources")
    return Path(next(iter(spec.submodule_search_locations)))


def _androguard() -> None:
    _file(androguard_resources() / "public.xml")
    public = importlib.import_module("androguard.core.resources.public")  # ta sama ścieżka co analiza manifestu
    if not public.SYSTEM_RESOURCES["attributes"]["forward"]:
        raise ValueError("public.xml: brak atrybutów")


def _data_dir_writable() -> None:
    directory = paths.data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=directory):
        pass  # plik znika po zamknięciu


CHECKS: tuple[tuple[str, Callable[[], object]], ...] = (
    ("rules.yaml", load_default_ruleset),
    ("ad_sdks.yaml", load_default_ad_sdks),
    ("iocs.yaml", load_default_iocs),
    ("trusted.yaml", load_default_trust_list),
    ("protected.yaml", load_protected_list),
    ("adb.exe", lambda: _file(tools_dir() / "adb.exe")),
    ("scrcpy.exe", lambda: _file(tools_dir() / "scrcpy.exe")),
    ("scrcpy-server", lambda: _file(tools_dir() / "scrcpy-server")),
    ("SDL3.dll", lambda: _file(tools_dir() / "SDL3.dll")),  # DLL-e scrcpy zostają przy scrcpy.exe
    ("phones.db", _phones_db),
    ("phones/", _phone_images),
    ("app/web/index.html", lambda: _file(app_main.WEB_DIR / "index.html")),
    ("admenot.ico", lambda: _file(paths.PACKAGE_ASSETS / "icon" / "admenot.ico")),
    ("androguard public.xml", _androguard),
    ("katalog danych", _data_dir_writable),
)


def run_checks() -> list[Check]:
    results = []
    for name, check in CHECKS:
        try:
            check()
        except Exception as exc:  # noqa: BLE001 — każdy błąd oznacza brak tego elementu
            results.append(Check(name, False, f"{type(exc).__name__}: {exc}"))
        else:
            results.append(Check(name, True))
    return results


def cmd_selfcheck(lang: str) -> int:
    ok_word, missing_word = STATUS[lang]
    results = run_checks()
    for r in results:
        word = ok_word if r.ok else missing_word
        detail = "" if r.ok else f" — {r.detail}"
        print(f"{word:<7} {r.name}{detail}")  # kolumna 7 znaków: „MISSING” mieści się bez obcinania
    return 0 if all(r.ok for r in results) else 1
