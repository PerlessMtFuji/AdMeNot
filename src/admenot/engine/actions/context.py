"""Stan telefonu potrzebny do planowania akcji: klawiatura, launcher, listy w ustawieniach."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from admenot.engine.actions import commands as C
from admenot.engine.actions.steps import NOTIF_LISTENERS_KEY, read, read_secure_list
from admenot.engine.adb.transport import AdbTransport
from admenot.engine.collectors.components import HOME_QUERY
from admenot.engine.collectors.packages import PM_SYSTEM
from admenot.engine.collectors.system import RESOLVE_HOME
from admenot.engine.parsers.common import (
    UnrecognizedOutput,
    parse_components,
    parse_package_list,
    query_packages,
)
from admenot.engine.parsers.system import parse_resolved_component

SECURE_LIST_KEYS = ("enabled_accessibility_services", NOTIF_LISTENERS_KEY)
# FallbackHome to ekran startowy Ustawień, a nie launcher, na który można przełączyć.
_NOT_LAUNCHERS = frozenset({"com.android.settings"})
_IME = re.compile(r"^([A-Za-z][\w.]*)/[\w.$]+$")
_NO_ACTIVITY = re.compile(r"No activity found", re.IGNORECASE)
# Odczyty, bez których planer nie wie, czy wyłączenie/usunięcie nie trafi w klawiaturę albo
# launcher (audyt 2026-10-11, BUG-03): nierozpoznana odpowiedź to „nie wiadomo”, nie „brak”.
CONTEXT_READS = ("ime", "home", "launchers", "system_packages")


@dataclass(frozen=True)
class PhoneContext:
    sdk: int
    manufacturer: str
    ime_package: str | None
    home_component: str | None
    home_candidates: dict[str, str]  # pakiet → komponent aktywności HOME
    system_packages: frozenset[str]
    secure_lists: dict[str, str]  # klucz → komponenty rozdzielone „:” („” gdy brak)
    unknown: frozenset[str] = field(default=frozenset())  # nierozpoznane odczyty (CONTEXT_READS)

    @property
    def home_package(self) -> str | None:
        return self.home_component.split("/")[0] if self.home_component else None

    @property
    def system_launchers(self) -> frozenset[str]:
        return frozenset(p for p in self.home_candidates if p in self.system_packages)


def _ime(text: str) -> tuple[str | None, bool]:
    """(pakiet aktywnej klawiatury, czy odczyt rozpoznany). „null” = rozpoznany brak klawiatury."""
    value = text.strip()
    if value == "null":
        return None, True
    m = _IME.match(value)
    return (m.group(1), True) if m else (None, False)


def _home(text: str) -> tuple[str | None, bool]:
    component = parse_resolved_component(text)
    known = component is not None or bool(parse_components(text)) or bool(_NO_ACTIVITY.search(text))
    return component, known


def _launchers(text: str) -> tuple[dict[str, str], bool]:
    try:
        query_packages(text)
    except UnrecognizedOutput:
        return {}, False
    candidates = {c.split("/")[0]: c for c in parse_components(text)}
    return {p: c for p, c in candidates.items() if p not in _NOT_LAUNCHERS}, True


def read_phone_context(adb: AdbTransport, manufacturer: str = "") -> PhoneContext:
    sdk = read(adb, C.GETPROP_SDK).strip()
    ime, ime_known = _ime(read(adb, C.DEFAULT_IME))
    home, home_known = _home(read(adb, RESOLVE_HOME))
    candidates, launchers_known = _launchers(read(adb, HOME_QUERY))
    system = frozenset(parse_package_list(read(adb, PM_SYSTEM)))
    known = {"ime": ime_known, "home": home_known, "launchers": launchers_known,
             "system_packages": bool(system)}  # każdy telefon ma pakiety systemowe
    return PhoneContext(
        sdk=int(sdk) if sdk.isdigit() else 0,
        manufacturer=manufacturer,
        ime_package=ime,
        home_component=home,
        home_candidates=candidates,
        system_packages=system,
        secure_lists={key: read_secure_list(adb, key) for key in SECURE_LIST_KEYS},
        unknown=frozenset(name for name, ok in known.items() if not ok),
    )
