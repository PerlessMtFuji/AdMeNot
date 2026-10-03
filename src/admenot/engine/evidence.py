"""Drabina dowodów: o co aplikacja prosi, co ma w kodzie, co jej przyznano, co zaobserwowano.

Ocena 2026-10-01 §7.3. None = nie wiadomo (brak danych) — nigdy nie znaczy „nie”.
"""

from __future__ import annotations

from dataclasses import dataclass

from admenot.engine.facts import AppFacts

LEVELS = ("declared", "code", "granted", "observed")
OVERLAY = "android.permission.SYSTEM_ALERT_WINDOW"
BIND_A11Y = "android.permission.BIND_ACCESSIBILITY_SERVICE"
BOOT = "android.intent.action.BOOT_COMPLETED"
RECENT_S = 24 * 3600


@dataclass(frozen=True)
class Ladder:
    capability: str
    levels: dict[str, bool | None]


def _any(*values: bool | None) -> bool | None:
    if any(v is True for v in values):
        return True
    return None if any(v is None for v in values) else False


def _overlay(f: AppFacts) -> dict[str, bool | None]:
    op = f.appops.get("SYSTEM_ALERT_WINDOW")
    return {"declared": OVERLAY in f.requested_permissions if f.requested_permissions else None,
            "code": f.code_overlay,
            "granted": None if op is None else op.mode == "allow",
            "observed": None if op is None or op.last_access_s is None else op.last_access_s <= RECENT_S}


def _accessibility(f: AppFacts) -> dict[str, bool | None]:
    comps = f.apk_components
    # a11y=None bywa „to nie usługa dostępności” albo „XML konfiguracji nieczytelny” — liczy się też samo uprawnienie
    declared = None if comps is None else any(
        c.a11y is not None or (c.kind == "service" and c.permission == BIND_A11Y) for c in comps)
    return {"declared": declared,
            "code": f.code_match(lambda p: p.sink in ("a11y_gesture", "a11y_read") and p.origin != "library"),
            "granted": f.accessibility_enabled if "secure_settings" not in f.gaps else None,
            "observed": None}


def _boot(f: AppFacts) -> dict[str, bool | None]:
    comps = f.apk_components
    return {"declared": None if comps is None else any(BOOT in c.actions for c in comps),
            "code": f.code_boot_ui,
            "granted": f.has_boot_receiver if "components" not in f.gaps else None,
            "observed": None}


def _hide_icon(f: AppFacts) -> dict[str, bool | None]:
    return {"declared": None, "code": f.code_hides_icon, "granted": None,
            "observed": None if f.has_launcher_icon is None else not f.has_launcher_icon}


_BUILDERS = (("overlay", _overlay), ("accessibility", _accessibility), ("boot", _boot),
             ("hide_icon", _hide_icon))


def ladders(facts: AppFacts) -> list[Ladder]:
    out = []
    for name, build in _BUILDERS:
        levels = build(facts)
        if any(v is True for v in levels.values()):
            out.append(Ladder(name, levels))
    return out
