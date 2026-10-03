"""Wersjonowana baza potwierdzonych wskaźników (IOC) z udokumentowanym pochodzeniem."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from importlib import resources

import yaml

from admenot.engine.facts import AppFacts

KINDS = ("sha256", "signer")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Ioc:
    kind: str
    value: str
    family: str
    source: str
    added: date
    exclusive: bool = False  # tylko signer: źródło stwierdza, że certyfikat podpisuje wyłącznie szkodliwe aplikacje


@dataclass(frozen=True)
class IocList:
    version: int
    entries: tuple[Ioc, ...]

    def match(self, facts: AppFacts) -> list[Ioc]:
        seen = {"sha256": set(facts.apk_sha256 or ()), "signer": set(facts.cert_sha256 or ())}
        return [i for i in self.entries if i.value in seen[i.kind]]


def _entry(raw: object) -> Ioc:
    if not isinstance(raw, dict):
        raise ValueError(f"iocs: entry must be a map: {raw!r}")  # noqa: TRY004
    kind, value = raw.get("kind"), str(raw.get("value", "")).lower()
    family, source, added = raw.get("family"), raw.get("source"), raw.get("added")
    if kind not in KINDS:
        raise ValueError(f"iocs: kind must be one of {KINDS}: {kind!r}")
    if not _HEX64.match(value):
        raise ValueError(f"iocs: value is not a SHA-256: {value!r}")
    if not isinstance(family, str) or not family.strip():
        raise ValueError(f"iocs: {value}: missing family")
    if not isinstance(source, str) or not source.startswith("https://"):
        raise ValueError(f"iocs: {value}: source must be an https:// report")
    if not isinstance(added, date):
        raise ValueError(f"iocs: {value}: added must be a date (YYYY-MM-DD)")  # noqa: TRY004
    exclusive = raw.get("exclusive", False)
    if not isinstance(exclusive, bool) or (exclusive and kind != "signer"):
        raise ValueError(f"iocs: {value}: exclusive is a bool and only for kind: signer")
    return Ioc(kind, value, family.strip(), source, added, exclusive)


def parse_iocs(text: str) -> IocList:
    data = yaml.safe_load(text) or {}
    version = data.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("iocs: version must be a positive int")
    return IocList(version, tuple(_entry(e) for e in data.get("entries") or []))


@cache
def load_default_iocs() -> IocList:
    path = resources.files("admenot.engine.apk").joinpath("data/iocs.yaml")
    return parse_iocs(path.read_text("utf-8"))
