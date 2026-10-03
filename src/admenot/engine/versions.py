"""Wersje silnika i plików danych — zapisywane z każdym skanem, żeby diagnozę dało się odtworzyć."""

from __future__ import annotations

import hashlib
from functools import cache
from importlib import metadata, resources

from admenot.engine.apk.iocs import load_default_iocs

_DATA = {
    "rules": ("admenot.engine.rules", "data/rules.yaml"),
    "ad_sdks": ("admenot.engine.apk", "data/ad_sdks.yaml"),
    "trusted": ("admenot.engine.allowlist", "data/trusted.yaml"),
    "iocs": ("admenot.engine.apk", "data/iocs.yaml"),
}


def _digest(package: str, name: str) -> str:
    return hashlib.sha256(resources.files(package).joinpath(name).read_bytes()).hexdigest()[:12]


@cache
def _versions() -> tuple[tuple[str, str], ...]:
    try:
        engine = metadata.version("admenot")
    except metadata.PackageNotFoundError:
        engine = "dev"
    versions = {"engine": engine}
    versions.update({key: _digest(*where) for key, where in _DATA.items()})
    versions["iocs"] = f"{load_default_iocs().version}-{versions['iocs']}"
    return tuple(versions.items())


def engine_versions() -> dict[str, str]:
    return dict(_versions())  # nowy słownik przy każdym wywołaniu — cache jest niemutowalny
