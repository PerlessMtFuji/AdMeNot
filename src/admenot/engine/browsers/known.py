"""Tabela znanych przeglądarek ze wspólnym kanałem powiadomień witryn i tych, które ich nie mają."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources

import yaml


@dataclass(frozen=True)
class KnownBrowser:
    package: str
    name: str
    shared_channel: str
    origin_from: str  # "tag" | "subtext"
    rdp_socket: str | None = None  # Firefox: gniazdo zdalnego debugowania
    block_action: bool = False  # aktywne powiadomienie witryny ma akcję „Blokuj” (Samsung Internet)


def parse_browsers(text: str) -> dict[str, KnownBrowser]:
    raw = (yaml.safe_load(text) or {}).get("browsers") or []
    return {item["package"]: KnownBrowser(**item) for item in raw}


def _data() -> str:
    return resources.files("admenot.engine.browsers").joinpath("data/browsers.yaml").read_text("utf-8")


@cache
def known_browsers() -> dict[str, KnownBrowser]:
    return parse_browsers(_data())


@cache
def browser_names() -> dict[str, str]:
    """Pakiet → nazwa popularnej przeglądarki (też spoza tabeli `browsers`)."""
    return dict((yaml.safe_load(_data()) or {}).get("names") or {})


@cache
def without_site_notifications() -> frozenset[str]:
    """Przeglądarki, w których strony nie mogą wysyłać powiadomień — kontrola je pomija."""
    return frozenset((yaml.safe_load(_data()) or {}).get("without_site_notifications") or [])
