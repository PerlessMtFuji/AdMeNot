from __future__ import annotations

import re

_DURATION_PART = re.compile(r"(\d+)(ms|d|h|m|s)")
_UNIT_SECONDS = {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
_COMPONENT = re.compile(r"^\s*([A-Za-z][\w.]*)/([\w.$]+)\s*:?\s*$")
_PACKAGE_LINE = re.compile(r"^package:([A-Za-z0-9_.]+)\s*$")
_FOUND = re.compile(r"^\s*(\d+|No) (?:activities|receivers|services) found", re.MULTILINE)


class UnrecognizedOutput(ValueError):
    """Odpowiedź telefonu w formacie, którego parser nie zna — to „nie wiadomo”, nie „brak”."""


def parse_duration(text: str) -> float | None:
    parts = _DURATION_PART.findall(text.strip().lstrip("+-"))
    if not parts:
        return None
    return sum(int(value) * _UNIT_SECONDS[unit] for value, unit in parts)


def component_packages(text: str) -> set[str]:
    packages: set[str] = set()
    for line in text.splitlines():
        m = _COMPONENT.match(line)
        if m:
            packages.add(m.group(1))
    return packages


def parse_components(text: str) -> list[str]:
    """Pełne nazwy komponentów „pakiet/klasa” z wyniku `cmd package query-*` / `resolve-activity`."""
    return [f"{m.group(1)}/{m.group(2)}" for line in text.splitlines()
            if (m := _COMPONENT.match(line))]


def split_components(value: str) -> set[str]:
    value = value.strip()
    if not value or value == "null":
        return set()
    return {item.split("/", 1)[0] for item in value.split(":") if "/" in item}


def parse_package_list(text: str) -> set[str]:
    return {m.group(1) for line in text.splitlines() if (m := _PACKAGE_LINE.match(line.strip()))}


def query_packages(text: str, *, expect_some: bool = False) -> set[str]:
    """Pakiety z `cmd package query-activities/receivers --brief` z kontrolą formatu."""
    packages = component_packages(text)
    if packages:
        return packages
    header = _FOUND.search(text)
    if header is None:
        raise UnrecognizedOutput("no components and no 'found' header")
    if header.group(1) != "No" and int(header.group(1)) > 0:
        raise UnrecognizedOutput(f"header announces {header.group(1)} entries, none parsed")
    if expect_some:
        raise UnrecognizedOutput("empty result where the system always has entries")
    return packages
