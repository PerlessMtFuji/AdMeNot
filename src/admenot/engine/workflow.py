"""Przebieg zlecenia (spec §3.2 kroki 6–8): plan → zlecenie → wykonanie → weryfikacja; cofanie.

Wspólny dla CLI i GUI. Nic nie drukuje: postęp idzie przez `ExecOptions.on_event`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from admenot.engine.actions.context import PhoneContext, read_phone_context
from admenot.engine.actions.errors import ActionError
from admenot.engine.actions.executor import (
    AppOutcome,
    ExecOptions,
    inverse_of,
    run_order,
    start_order,
    undo,
    verify,
)
from admenot.engine.actions.planner import (
    FIX_LEVEL,
    AppPlan,
    Blocked,
    default_level,
    plan_app,
    plan_fixes,
)
from admenot.engine.adb.transport import AdbTransport
from admenot.engine.allowlist.trust import load_protected_list
from admenot.engine.apk.cache import clear_cache
from admenot.engine.device.identity import device_key, identity_of
from admenot.engine.device.info import DeviceInfo
from admenot.engine.facts import AppFacts
from admenot.engine.journal.db import Action, Journal, Order
from admenot.engine.paths import backups_dir, device_dir_name
from admenot.engine.phones.provider import PhoneMatch
from admenot.engine.report.snapshot import scan_snapshot
from admenot.engine.session import ScanReport
from admenot.engine.settings import Settings

Runner = Callable[[AdbTransport, Journal, int, ExecOptions], list[AppOutcome]]


@dataclass
class OrderPlan:
    device: DeviceInfo
    ctx: PhoneContext
    facts: dict[str, AppFacts]
    results: list[AppPlan | Blocked]
    unlocked: frozenset[str] = frozenset()  # chronione pakiety odblokowane przez serwisanta
    fixes: tuple[str, ...] = ()  # wybrane poprawki „Stanu telefonu” (posortowane)

    @property
    def plans(self) -> list[AppPlan]:
        return [r for r in self.results if isinstance(r, AppPlan)]


@dataclass
class AppStatus:
    package: str
    status: str  # ok | still_active | failed | stopped
    errors: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)


@dataclass
class OrderResult:
    order: Order
    apps: list[AppStatus]
    stopped: bool


def clear_cache_after_repair(result: OrderResult, settings: Settings, cache_dir: Path) -> int | None:
    """Spec §3.7: tylko po zleceniu bez kroków do dokończenia; `backups/` zostaje nietknięty."""
    if result.stopped or not settings.apk_cache_clear_after_repair:
        return None
    try:
        return clear_cache(cache_dir)
    except OSError:  # czyszczenie to porządek po naprawie: nie może jej zepsuć
        return None


@dataclass
class UndoResult:
    order: Order
    errors: list[tuple[Action, str]]
    admin_not_restored: bool
    sites_total: int = 0  # kanały witryn wyłączone przez naprawę, objęte tym cofnięciem
    sites_restored: int = 0  # z nich włączone teraz (reszta: pominięte, czas minął, kanał zniknął)
    restored_sites: list[int] = field(default_factory=list)  # id kanałów włączonych teraz przez ekran
    firefox_debugging: bool = False  # cofnięto zgodę przez zdalne debugowanie: przypomnij o wyłączeniu


class OrderInterrupted(Exception):
    """Telefon zniknął w trakcie: kroki niewykonane zostają „pending” (dokończ albo cofnij)."""

    def __init__(self, order: Order) -> None:
        super().__init__(order.number)
        self.order = order


def recommended_requests(report: ScanReport) -> dict[str, str]:
    requests: dict[str, str] = {}
    for r in report.results:
        if (level := default_level(r, report.device.sdk)) is not None:
            requests[r.facts.package] = level
    return requests


def plan_order(
    adb: AdbTransport,
    report: ScanReport,
    requests: dict[str, str],
    unlocked: Iterable[str] = (),
    ctx: PhoneContext | None = None,
    fixes: Iterable[str] = (),
) -> OrderPlan:
    device = report.device
    ctx = ctx or read_phone_context(adb, device.manufacturer)
    facts = {r.facts.package: r.facts for r in report.results}
    protected = load_protected_list()
    # dwa telefony z jednym numerem seryjnym nie dzielą kopii
    root = backups_dir() / device_dir_name(device_key(device))
    free = frozenset(unlocked)
    destroyed = frozenset(p for p, level in requests.items() if level in ("disable", "remove"))
    chosen = tuple(sorted(set(fixes)))
    results = [*plan_fixes(chosen, report.device_checks, requests),
               *(plan_app(package, level, facts.get(package), ctx, protected, root, free, destroyed)
                 for package, level in requests.items())]
    used = frozenset(r.package for r in results if isinstance(r, AppPlan)
                     and r.level != FIX_LEVEL and r.package in free and (protected.matches(r.package)
                                                or r.package in ctx.system_launchers))
    return OrderPlan(device, ctx, facts, results, used, chosen)


def start(journal: Journal, plan: OrderPlan, client: str | None,
          report: ScanReport | None = None, match: PhoneMatch | None = None,
          consent: dict[str, str] | None = None) -> Order:
    order = start_order(journal, plan.device.serial, plan.device.model, plan.plans, client,
                        identity_of(plan.device))
    if report is not None and match is not None:
        # Migawka dla protokołu (spec §9.3): telefon, zakres skanu, problemy i decyzje
        # serwisanta z chwili zlecenia.
        # poprawki „Stanu telefonu” (poziom fix) nie są decyzją o aplikacji: wynik biorą z dziennika
        chosen = {p.package: p.level for p in plan.plans if p.level != FIX_LEVEL}
        snapshot = scan_snapshot(report, match, chosen)
        if plan.unlocked:  # decyzja operatora zostaje w zleceniu (audyt 2026-10-11, QA-01)
            snapshot["unlocked"] = sorted(plan.unlocked)
        if consent:  # klient zobaczył ten plan przed wykonaniem (spec plan-qr §5.4)
            snapshot["consent"] = dict(consent)
        journal.save_scan(order.id, snapshot)
    return order


def targeted_actions(
    journal: Journal, order_id: int, package: str | None = None, action_id: int | None = None,
) -> list[Action]:
    """Kroki zlecenia dotyczące wskazanej aplikacji/kroku (albo wszystkie, gdy oba None)."""
    return [a for a in journal.actions(order_id)
            if package in (None, a.package) and action_id in (None, a.id)]


def execute_order(adb: AdbTransport, journal: Journal, order: Order, options: ExecOptions,
                  runner: Runner = run_order) -> OrderResult:
    try:
        outcomes = runner(adb, journal, order.id, options)
        options.on_event({"type": "verify"})
        problems = verify(adb, journal, order.id)
        journal.save_verification(order.id, problems)
    except ActionError as exc:
        # Wszystko, co ucieknie z runnera albo weryfikacji, zostawia kroki „pending”:
        # zlecenie jest przerwane (dokończ albo cofnij), nawet gdy błąd nie jest „niepewny”
        # (np. `_Admin.apply`'s fallback do ADMIN_SETTINGS/SECURITY_SETTINGS oba zawodzą).
        raise OrderInterrupted(journal.order(order.id)) from exc
    # dict: kolejność aplikacji jak w zleceniu (do dopisania tych, do których runner nie doszedł)
    pending = dict.fromkeys(a.package for a in journal.actions(order.id) if a.status == "pending")
    apps: list[AppStatus] = []
    for outcome in outcomes:
        if not outcome.ok:
            keys = list(dict.fromkeys(key for _, key in outcome.failed))
            apps.append(AppStatus(outcome.package, "failed", errors=keys))
        elif outcome.package in pending:
            apps.append(AppStatus(outcome.package, "stopped"))
        elif outcome.package in problems:
            apps.append(AppStatus(outcome.package, "still_active", kinds=problems[outcome.package]))
        else:
            apps.append(AppStatus(outcome.package, "ok"))
    reached = {outcome.package for outcome in outcomes}
    # „Wstrzymaj” przed aplikacją: nie ma jej w wynikach runnera, a nadal czeka w zleceniu
    apps.extend(AppStatus(package, "stopped") for package in pending if package not in reached)
    return OrderResult(journal.order(order.id), apps, stopped=bool(pending))


def undo_order(
    adb: AdbTransport,
    journal: Journal,
    order: Order,
    package: str | None = None,
    action_id: int | None = None,
    options: ExecOptions | None = None,
) -> UndoResult:
    # Stan sprzed cofnięcia: krok admina po cofnięciu dostaje „undone”, choć uprawnień nie oddajemy.
    targeted = targeted_actions(journal, order.id, package, action_id)
    base = options or ExecOptions()
    screened: set[int] = set()  # kanały włączone przez ekran w tym cofaniu

    def on_event(event: dict) -> None:
        if event["type"] == "undo" and event.get("via_screen"):
            screened.add(event["action_id"])
        base.on_event(event)

    try:
        errors = undo(adb, journal, order.id, package=package, action_id=action_id,
                      options=replace(base, on_event=on_event))
    except ActionError as exc:
        if exc.uncertain:
            raise OrderInterrupted(journal.order(order.id)) from exc
        raise
    admin = any(a.step["kind"] == "admin" and a.status == "done" for a in targeted)
    # Witryny do włączenia: kanały „done”, które naprawa naprawdę wyłączyła (wyłączone już
    # przed naprawą nie liczą się — nie ma czego przywracać).
    sites = [a.id for a in targeted
             if a.step["kind"] == "channel" and a.status == "done" and inverse_of(a) is not None]
    # Zgodę cofa zdalne debugowanie, więc po cofnięciu jest włączone. „undone” z powodem
    # (app_gone, not_started) niczego na telefonie nie zmieniło.
    after = {a.id: a for a in journal.actions(order.id)}
    restored = [i for i in sites if after[i].status == "undone" and after[i].error is None]
    debugging = any(a.step["kind"] == "site_permission" and a.status != "undone"
                    and after[a.id].status == "undone" and after[a.id].error is None for a in targeted)
    return UndoResult(journal.order(order.id), errors, admin, sites_total=len(sites),
                      sites_restored=len(restored),
                      restored_sites=[i for i in restored if i in screened], firefox_debugging=debugging)
