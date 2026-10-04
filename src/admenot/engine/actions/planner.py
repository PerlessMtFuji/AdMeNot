"""Plan akcji dla jednej aplikacji: kroki poziomów Wycisz/Wyłącz/Usuń i blokady (spec §7.1, §7.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from admenot.engine.actions.context import SECURE_LIST_KEYS, PhoneContext
from admenot.engine.actions.steps import Step, split_items
from admenot.engine.allowlist.trust import PackagePatterns
from admenot.engine.facts import AppFacts
from admenot.engine.scoring import AppResult

LEVELS = ("silence", "disable", "remove")
POST_NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS"
SYSTEM_ALERT_WINDOW = "android.permission.SYSTEM_ALERT_WINDOW"
NOTIF_PERMISSION_MIN_SDK = 33  # od Androida 13 powiadomienia to uprawnienie wykonawcze
FSI_OP_MIN_SDK = 34  # appop USE_FULL_SCREEN_INTENT istnieje od Androida 14


@dataclass
class AppPlan:
    package: str
    level: str
    steps: list[Step]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Blocked:
    package: str
    level: str
    reason: str  # unknown_level | not_installed | protected | active_ime | home_no_alternative


def default_level(result: AppResult) -> str | None:
    """Domyślny wybór w planie: werdykt + pewność, nie sam wynik (audyt 2026-09-27)."""
    if result.verdict == "malicious":
        level = "remove"  # werdykt wymaga już wysokiej pewności (scoring.verdict_for)
    elif result.verdict == "suspicious":
        level = "silence" if result.confidence == "low" else "disable"
    else:
        return None
    if result.facts.is_system and level == "remove":
        level = "disable"  # komponent producenta: usunięcie ocenia serwisant, nie heurystyka
    return level


def backup_dir_for(root: Path, package: str, version_code: int | None) -> Path:
    return root / package / (str(version_code) if version_code is not None else "unknown")


def _alternative_home(package: str, ctx: PhoneContext) -> str | None:
    """Launcher, na który przełączamy: tylko systemowy (producenta), nigdy inna aplikacja z Play."""
    for candidate in sorted(ctx.system_launchers):
        if candidate != package:
            return ctx.home_candidates[candidate]
    return None


def _silence_steps(package: str, facts: AppFacts, ctx: PhoneContext,
                   warnings: list[str]) -> list[Step]:
    steps: list[Step] = []
    if ctx.home_package == package:
        alternative = _alternative_home(package, ctx)
        if alternative:
            steps.append(Step("home", package, {"component": alternative}))
        else:
            warnings.append("home_not_switched")
    for key in SECURE_LIST_KEYS:
        own = [c for c in split_items(ctx.secure_lists.get(key, "")) if c.split("/")[0] == package]
        if own:
            steps.append(Step("secure_list", package,
                              {"key": key, "op": "remove", "components": ":".join(own)}))
    if ctx.sdk >= NOTIF_PERMISSION_MIN_SDK:
        steps.append(Step("permission", package, {"permission": POST_NOTIFICATIONS, "granted": "0"}))
    elif ctx.sdk == 0:  # wersja nieznana: appop to jedyne, co da się spróbować
        steps.append(Step("appop", package, {"op": "POST_NOTIFICATION", "mode": "ignore"}))
    # Android ≤12: przez ADB powiadomień nie wyłączymy — appop POST_NOTIFICATION nie blokuje ich
    # (OPPO CPH2271, 2026-10-04), a przełącznik zmienia tylko system; UI każe zrobić to ręcznie.
    if SYSTEM_ALERT_WINDOW in facts.requested_permissions:
        # Bez tego uprawnienia aplikacja i tak nie rysuje nad innymi, a Android 12 (OPPO)
        # przyjmuje `appops set` z kodem 0, nie zmieniając trybu — weryfikacja by go zgłosiła.
        steps.append(Step("appop", package, {"op": "SYSTEM_ALERT_WINDOW", "mode": "deny"}))
    if ctx.sdk >= FSI_OP_MIN_SDK:
        steps.append(Step("appop", package, {"op": "USE_FULL_SCREEN_INTENT", "mode": "deny"}))
    steps.append(Step("force_stop", package))  # na końcu: wcześniejsze kroki mogą ją wybudzić
    return steps


def plan_app(
    package: str,
    level: str,
    facts: AppFacts | None,
    ctx: PhoneContext,
    protected: PackagePatterns,
    backup_root: Path,
    unlocked: frozenset[str] = frozenset(),
) -> AppPlan | Blocked:
    if level not in LEVELS:
        return Blocked(package, level, "unknown_level")
    if facts is None:
        return Blocked(package, level, "not_installed")
    if (protected.matches(package) or package in ctx.system_launchers) and package not in unlocked:
        return Blocked(package, level, "protected")
    if level != "silence":
        if package == ctx.ime_package:
            return Blocked(package, level, "active_ime")
        if ctx.home_package == package and _alternative_home(package, ctx) is None:
            return Blocked(package, level, "home_no_alternative")

    warnings: list[str] = []
    steps = _silence_steps(package, facts, ctx, warnings)
    if level == "disable":
        steps.append(Step("enabled", package, {"enabled": "0"}))
    elif level == "remove":
        backup = str(backup_dir_for(backup_root, package, facts.version_code))
        version = "" if facts.version_code is None else str(facts.version_code)
        steps.append(Step("backup", package, {"dir": backup, "version_code": version}))
        steps.append(Step("installed", package, {"installed": "0", "backup_dir": backup}))
    return AppPlan(package, level, steps, warnings)
