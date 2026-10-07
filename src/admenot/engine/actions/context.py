"""Stan telefonu potrzebny do planowania akcji: klawiatura, launcher, listy w ustawieniach."""

from __future__ import annotations

from dataclasses import dataclass

from admenot.engine.actions import commands as C
from admenot.engine.actions.steps import NOTIF_LISTENERS_KEY, read, read_secure_list
from admenot.engine.adb.transport import AdbTransport
from admenot.engine.collectors.components import HOME_QUERY
from admenot.engine.collectors.packages import PM_SYSTEM
from admenot.engine.collectors.system import RESOLVE_HOME
from admenot.engine.parsers.common import parse_components, parse_package_list
from admenot.engine.parsers.system import parse_resolved_component

SECURE_LIST_KEYS = ("enabled_accessibility_services", NOTIF_LISTENERS_KEY)
# FallbackHome to ekran startowy Ustawień, a nie launcher, na który można przełączyć.
_NOT_LAUNCHERS = frozenset({"com.android.settings"})


@dataclass(frozen=True)
class PhoneContext:
    sdk: int
    manufacturer: str
    ime_package: str | None
    home_component: str | None
    home_candidates: dict[str, str]  # pakiet → komponent aktywności HOME
    system_packages: frozenset[str]
    secure_lists: dict[str, str]  # klucz → komponenty rozdzielone „:” („” gdy brak)

    @property
    def home_package(self) -> str | None:
        return self.home_component.split("/")[0] if self.home_component else None

    @property
    def system_launchers(self) -> frozenset[str]:
        return frozenset(p for p in self.home_candidates if p in self.system_packages)


def read_phone_context(adb: AdbTransport, manufacturer: str = "") -> PhoneContext:
    sdk = read(adb, C.GETPROP_SDK).strip()
    ime = read(adb, C.DEFAULT_IME).strip()
    candidates = {c.split("/")[0]: c for c in parse_components(read(adb, HOME_QUERY))}
    return PhoneContext(
        sdk=int(sdk) if sdk.isdigit() else 0,
        manufacturer=manufacturer,
        ime_package=ime.split("/")[0] if "/" in ime else None,
        home_component=parse_resolved_component(read(adb, RESOLVE_HOME)),
        home_candidates={p: c for p, c in candidates.items() if p not in _NOT_LAUNCHERS},
        system_packages=frozenset(parse_package_list(read(adb, PM_SYSTEM))),
        secure_lists={key: read_secure_list(adb, key) for key in SECURE_LIST_KEYS},
    )
