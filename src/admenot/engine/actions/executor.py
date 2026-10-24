"""Wykonanie, cofanie i weryfikacja zleceń (spec §3.2 kroki 7–8, §7.4).

Każdy krok jest w dzienniku, zanim dotknie telefonu. Stan sprzed zmiany i krok odwrotny
zapisujemy przed wykonaniem; po odłączeniu krok zostaje „pending”.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from admenot.engine.actions import steps as S
from admenot.engine.actions.backup import read_manifest
from admenot.engine.actions.context import read_phone_context
from admenot.engine.actions.errors import ActionError
from admenot.engine.actions.planner import AppPlan
from admenot.engine.actions.steps import Step
from admenot.engine.adb.transport import AdbTransport
from admenot.engine.apk.fetch import installed_hashes
from admenot.engine.journal.db import Action, Journal, Order, unresolved
from admenot.engine.oplock import device_lock

Event = dict[str, Any]
BLOCKING_KINDS = frozenset({"backup"})  # bez kopii APK nie odinstalowujemy
VERIFIED_KINDS = frozenset({"appop", "permission", "secure_list", "home", "enabled", "installed",
                            "channel", "site_permission"})
ADMIN_BLOCKED_KINDS = frozenset({"enabled", "installed"})  # blokowane przez aktywnego admina
SITE_TIMEOUTS_IN_A_ROW = 2  # tyle przekroczeń czasu z rzędu w cofaniu: nikt nie stoi przy telefonie

log = logging.getLogger(__name__)


def _ignore(event: Event) -> None:
    pass


def _skip(package: str) -> str:
    return "skip"


def _never() -> bool:
    return False


@dataclass
class ExecOptions:
    apk_cache_dir: Path | None = None
    admin_timeout: float = 180.0
    poll_interval: float = 1.0
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    on_event: Callable[[Event], None] = _ignore
    on_admin_timeout: Callable[[str], str] = _skip  # "retry" | "skip"
    should_stop: Callable[[], bool] = _never  # „Wstrzymaj”: sprawdzane przed każdym krokiem
    # „Otwórz ponownie”: True raz po prośbie serwisanta — ekran oczekującego kroku otwiera się znowu
    reopen: Callable[[], bool] = _never
    # „Pomiń”: True raz po prośbie serwisanta — oczekiwanie na bieżącym ekranie kończy się bez zmiany
    skip: Callable[[], bool] = _never


@dataclass
class AppOutcome:
    package: str
    failed: list[tuple[str, str]] = field(default_factory=list)  # (rodzaj kroku, klucz błędu)

    @property
    def ok(self) -> bool:
        return not self.failed


def start_order(
    journal: Journal,
    serial: str,
    model: str | None,
    plans: Iterable[AppPlan],
    client_name: str | None = None,
    identity: dict[str, Any] | None = None,
) -> Order:
    """Zakłada zlecenie i zapisuje wszystkie kroki jako „pending”, zanim coś trafi na telefon."""
    order = journal.create_order(serial, model, client_name, identity)
    for plan in plans:
        for step in plan.steps:
            journal.add_action(order.id, plan.package, plan.level, step.to_dict(),
                               S.command_for(step))
    return order


def _restore_size(inverse: Step) -> dict[str, int]:
    """Rozmiar kopii, z której cofnięcie może instalować (UI: „to potrwa”)."""
    if inverse.kind != "installed" or inverse.params.get("installed") != "1":
        return {}
    backup = Path(inverse.params.get("backup_dir") or "")
    sizes = [f.stat().st_size for f in backup.glob("*.apk")] if backup.is_dir() else []
    return {"restore_bytes": sum(sizes)} if sizes else {}


def _emit(options: ExecOptions, type_: str, row: Action, status: str,
          error: str | None = None, **extra: Any) -> None:
    options.on_event({"type": type_, "action_id": row.id, "package": row.package,
                      "step": row.step, "status": status, "error": error, **extra})


def is_destructive(step: Step) -> bool:
    return ((step.kind == "enabled" and step.params.get("enabled") == "0")
            or (step.kind == "installed" and step.params.get("installed") == "0"))


def _precheck(adb: AdbTransport, step: Step) -> None:
    """Warunki planu sprawdzane tuż przed wyłączeniem/usunięciem, także po wznowieniu (audyt
    2026-10-11, BUG-04, BUG-07): klient mógł zmienić klawiaturę, przełączenie ekranu głównego
    mogło się nie udać, aplikacja mogła się zaktualizować od zrobienia kopii."""
    ctx = read_phone_context(adb)
    if ctx.unknown:
        raise ActionError("context_unknown", ", ".join(sorted(ctx.unknown)))
    if step.package == ctx.ime_package:
        raise ActionError("active_ime")
    if step.package == ctx.home_package:
        raise ActionError("home_active")
    if step.kind == "installed":
        manifest = read_manifest(Path(step.params["backup_dir"]))
        if manifest is None or manifest.get("package") != step.package:
            raise ActionError("no_backup", step.params["backup_dir"])
        hashes = installed_hashes(adb, step.package)
        if hashes is not None and hashes != manifest["files"]:
            raise ActionError("backup_stale")


def _execute(adb: AdbTransport, journal: Journal, row: Action, options: ExecOptions) -> None:
    step = Step.from_dict(row.step)
    state = S.probe(adb, step)
    if S.is_applied(step, state):
        if row.prev_state is None:
            journal.record_prev_state(row.id, state, None)  # nic nie zmieniamy — nic do cofnięcia
        return  # przerwane zlecenie: krok zdążył się wykonać, odwrotność jest już zapisana
    if is_destructive(step):
        _precheck(adb, step)
    fresh = row.prev_state is None
    if row.prev_state is None:
        inverse = S.inverse(step, state)
        # Porównaj-i-ustaw: zapisany już stan (np. przez inny proces) wygrywa z naszą migawką.
        journal.record_prev_state(row.id, state, inverse.to_dict() if inverse else None)
    if step.kind == "admin":
        # Zaległy krok z przerwanego zlecenia: nikt już nie czeka na telefonie — tylko sprawdzamy stan.
        raise ActionError("admin_timeout")
    if step.kind == "channel":
        # Jak admin: zaległy krok z przerwanego zlecenia tylko sprawdzamy, ekranu nie otwieramy.
        if fresh and _wait_for_user(adb, journal, row, step, options) == "done":
            return
        raise ActionError("user_timeout")
    S.apply(adb, step, options.apk_cache_dir)


def _recover(adb: AdbTransport, journal: Journal, row: Action, exc: ActionError,
             options: ExecOptions) -> str | None:
    """Próba naprawy po błędzie kroku. None = krok ostatecznie wykonany, inaczej klucz błędu.

    Aktywny administrator urządzenia blokuje wyłączenie i usunięcie (spec §7.2): otwieramy ekran
    administratorów na telefonie, czekamy na „Dezaktywuj” i ponawiamy krok.
    """
    if exc.key != "device_admin" or row.step["kind"] not in ADMIN_BLOCKED_KINDS:
        return exc.key
    if not _admin_path(adb, journal, row, options):
        return exc.key
    try:
        _execute(adb, journal, journal.action(row.id), options)
    except ActionError as again:
        if again.uncertain:
            raise
        return again.key
    return None


def _admin_path(adb: AdbTransport, journal: Journal, row: Action, options: ExecOptions) -> bool:
    step = Step("admin", row.package)
    admin_id = journal.add_action(row.order_id, row.package, row.level, step.to_dict(),
                                  S.command_for(step))
    admin_row = journal.action(admin_id)
    state = S.probe(adb, step)
    journal.record_prev_state(admin_id, state, None)
    if S.is_applied(step, state):
        journal.set_action_status(admin_id, "failed", "not_admin")  # błąd polityki bez admina
        return False
    if _wait_for_user(adb, journal, admin_row, step, options) == "done":
        journal.set_action_status(admin_id, "done")
        return True
    journal.set_action_status(admin_id, "failed", "admin_timeout")
    return False


def _wait_for_user(adb: AdbTransport, journal: Journal, row: Action, step: Step,
                   options: ExecOptions, ask: bool = True) -> str:
    """Otwiera ekran na telefonie i czeka, aż użytkownik zrobi swoje (spec §7.2): `admin` albo
    `channel` (w cofaniu: włączenie kanału). Wynik: "done" = stan osiągnięty, "timeout" = czas
    minął, "skipped" = „Pomiń”, "stopped" = „Wstrzymaj”. `ask=False` (cofanie): po czasie bez
    pytania o ponowienie. Status wiersza ustawia wołający."""
    error = "admin_timeout" if step.kind == "admin" else "user_timeout"
    event = {"action_id": row.id, "package": row.package, "step": step.kind}

    def finish(result: str, key: str | None) -> str:
        status = "done" if result == "done" else "failed"
        options.on_event({"type": "user_done", **event, "status": status, "error": key})
        return result

    while True:
        S.apply(adb, step)
        options.on_event({"type": "user_wait", **event, "timeout": options.admin_timeout})
        deadline = options.clock() + options.admin_timeout
        while options.clock() < deadline:
            if options.reopen():  # ktoś zamknął ekran na telefonie: ten sam ekran, ten sam limit czasu
                S.apply(adb, step)
            if S.is_applied(step, S.probe(adb, step)):
                return finish("done", None)
            if options.should_stop():
                return finish("stopped", error)
            if options.skip():
                return finish("skipped", "site_skipped")
            options.sleep(options.poll_interval)
        if options.should_stop():
            return finish("stopped", error)
        if not ask or options.on_admin_timeout(row.package) != "retry":
            return finish("timeout", error)


def _finish(journal: Journal, order_id: int) -> None:
    if journal.order(order_id).status in ("undone", "partially_undone"):
        return  # wznowienie po cofnięciu nie może udawać, że zlecenie jest wykonane
    statuses = {a.status for a in journal.actions(order_id)}
    if "pending" not in statuses:
        journal.set_order_status(order_id, "failed" if "failed" in statuses else "done")


def _locked(journal: Journal, order_id: int) -> AbstractContextManager[None]:
    """Blokada telefonu zlecenia, wspólna dla procesów (BUG-06): DeviceBusy, gdy zajęty.
    Kroki czytamy z dziennika dopiero pod blokadą — nie ze starej migawki."""
    return device_lock(journal.path, journal.order(order_id).device_serial)


def run_order(adb: AdbTransport, journal: Journal, order_id: int,
              options: ExecOptions | None = None) -> list[AppOutcome]:
    """Wykonuje kroki „pending” po kolei. `should_stop` przerywa przed kolejnym krokiem:
    reszta zostaje „pending”, a zlecenie — przerwane, do dokończenia (`resume`) albo cofnięcia."""
    with _locked(journal, order_id):
        return _run_order(adb, journal, order_id, options or ExecOptions())


def _run_order(adb: AdbTransport, journal: Journal, order_id: int,
               options: ExecOptions) -> list[AppOutcome]:
    outcomes: dict[str, AppOutcome] = {}
    blocked: set[str] = set()
    for row in journal.actions(order_id):
        if row.status != "pending":
            continue
        if options.should_stop():
            options.on_event({"type": "stopped"})
            break
        outcome = outcomes.setdefault(row.package, AppOutcome(row.package))
        kind = row.step["kind"]
        if row.package in blocked:
            journal.set_action_status(row.id, "failed", "skipped")
            outcome.failed.append((kind, "skipped"))
            _emit(options, "step", row, "skipped", "skipped")
            continue
        _emit(options, "step", row, "running")
        try:
            _execute(adb, journal, row, options)
            error = None
        except ActionError as exc:
            if exc.uncertain:
                raise  # telefon zniknął: krok zostaje „pending” do dokończenia albo cofnięcia
            error = _recover(adb, journal, row, exc, options)
        if error is not None:
            journal.set_action_status(row.id, "failed", error)
            outcome.failed.append((kind, error))
            if kind in BLOCKING_KINDS:
                blocked.add(row.package)
            _emit(options, "step", row, "failed", error)
            continue
        journal.set_action_status(row.id, "done")
        _emit(options, "step", row, "done")
    _finish(journal, order_id)
    return list(outcomes.values())


def resume(adb: AdbTransport, journal: Journal, order_id: int,
           options: ExecOptions | None = None) -> list[AppOutcome]:
    """Dokończenie przerwanego zlecenia (spec §7.5).

    Kroki „pending” są sprawdzane na telefonie: jeśli zdążyły się wykonać, dostają „done” bez
    ponownego polecenia. Stan sprzed zmiany i krok odwrotny zostają te z dziennika, więc
    późniejsze cofnięcie przywraca telefon sprzed naprawy, a nie sprzed wznowienia.
    """
    return run_order(adb, journal, order_id, options)


def _is_installed(adb: AdbTransport, package: str, cache: dict[str, bool]) -> bool:
    if package not in cache:
        probe = Step("installed", package, {"installed": "1", "backup_dir": ""})
        cache[package] = S.is_applied(probe, S.probe(adb, probe))
    return cache[package]


def undo(
    adb: AdbTransport,
    journal: Journal,
    order_id: int,
    package: str | None = None,
    action_id: int | None = None,
    options: ExecOptions | None = None,
) -> list[tuple[Action, str]]:
    """Cofa kroki w odwrotnej kolejności: jeden krok, jedną aplikację albo całe zlecenie.

    `should_stop` przerywa przed kolejną odwrotnością (EDGE-01); krok jest „undone” dopiero, gdy
    ponowny odczyt potwierdzi stan sprzed naprawy (BUG-05)."""
    with _locked(journal, order_id):
        return _undo(adb, journal, order_id, package, action_id, options or ExecOptions())


def _confirmed(adb: AdbTransport, inverse: Step, options: ExecOptions) -> bool:
    if S.is_applied(inverse, S.probe(adb, inverse)):
        return True
    options.sleep(options.poll_interval)  # część telefonów zmienia stan z opóźnieniem
    return S.is_applied(inverse, S.probe(adb, inverse))


def inverse_of(row: Action) -> Step | None:
    """Krok odwrotny wiersza. Wiersze kanału sprzed odwrotności kanału mają tylko stan sprzed
    naprawy: `importance` > 0 znaczy, że naprawa kanał wyłączyła — odwrotność liczymy w locie."""
    if row.inverse is not None:
        return Step.from_dict(row.inverse)
    importance = (row.prev_state or {}).get("importance")
    if row.step["kind"] == "channel" and isinstance(importance, int) and importance > 0:
        step = Step.from_dict(row.step)
        return Step("channel", step.package, {**step.params, "enabled": "1"})
    return None


@dataclass
class _UndoRun:
    """Stan jednego cofania wspólny dla fazy automatycznej i fazy witryn."""
    adb: AdbTransport
    journal: Journal
    options: ExecOptions
    removed: set[str]  # aplikacje, które to zlecenie odinstalowało
    installed: dict[str, bool] = field(default_factory=dict)
    errors: list[tuple[Action, str]] = field(default_factory=list)
    gone: set[str] = field(default_factory=set)  # aplikacje, których nie udało się przywrócić

    def fail(self, row: Action, key: str) -> None:
        self.errors.append((row, key))
        if row.step["kind"] in ADMIN_BLOCKED_KINDS:  # włączenie / instalacja aplikacji
            self.gone.add(row.package)
        _emit(self.options, "undo", row, "failed", key)

    def resolve(self, row: Action, error: str | None = None, **extra: Any) -> None:
        self.journal.set_action_status(row.id, "undone", error)
        _emit(self.options, "undo", row, "undone", error, **extra)

    def app_missing(self, row: Action, inverse: Step) -> bool:
        """Aplikacji kroku nie ma na telefonie: krok obsłużony tutaj (True) albo do cofnięcia."""
        if inverse.kind == "installed" or _is_installed(self.adb, row.package, self.installed):
            return False
        if row.package in self.removed:
            # Sami ją usunęliśmy, a przywrócenie się nie udało: krok czeka na ponowne undo.
            self.gone.add(row.package)
            self.fail(row, "skipped")
        else:
            self.resolve(row, "app_gone")  # użytkownik sam odinstalował aplikację: nie ma czego cofać
        return True


def _undo(adb: AdbTransport, journal: Journal, order_id: int, package: str | None,
          action_id: int | None, options: ExecOptions) -> list[tuple[Action, str]]:
    everything = journal.actions(order_id)
    rows = [a for a in everything
            if (package is None or a.package == package) and (action_id is None or a.id == action_id)]
    if not rows:
        raise ValueError(f"nothing matches package={package!r} action={action_id!r}")
    # Aplikacje, które to zlecenie odinstalowało: ich brak na telefonie to nasza zmiana.
    removed = {a.package for a in everything if a.status == "done"
               and a.step["kind"] == "installed" and a.step["params"].get("installed") == "0"}
    run = _UndoRun(adb, journal, options, removed)
    errors, installed = run.errors, run.installed
    stopped = False
    # Najpierw odwrotności automatyczne (od końca), ekrany kanałów do klikania na sam koniec:
    # serwisant nie czeka przy telefonie w środku cofania, a przeglądarka zdąży wrócić.
    for row in reversed(rows):
        if row.status == "undone" or row.step["kind"] == "channel":
            continue
        if row.status == "failed" and (row.prev_state is None or row.inverse is None):
            continue  # krok nie zdążył niczego zmienić albo nie ma czego odwracać
        if options.should_stop():
            options.on_event({"type": "stopped"})
            stopped = True
            break
        # Krok „failed” z zapisanym stanem mógł się wykonać (np. adb: „error: closed”):
        # odwrotność jest idempotentna, więc bez zmiany na telefonie nic nie zostanie wysłane.
        if row.prev_state is None:  # przerwane zlecenie: krok nie zdążył się zacząć
            run.resolve(row, "not_started")
            continue
        try:
            if row.inverse is not None:
                inverse = Step.from_dict(row.inverse)
                if run.app_missing(row, inverse):
                    continue
                if not S.is_applied(inverse, S.probe(adb, inverse)):
                    _emit(options, "undo", row, "running", **_restore_size(inverse))
                    S.apply(adb, inverse, options.apk_cache_dir)
                    if not _confirmed(adb, inverse, options):
                        raise ActionError("not_restored")
                if inverse.kind == "installed":
                    installed[row.package] = inverse.params["installed"] == "1"
        except ActionError as exc:
            if exc.uncertain:
                raise
            run.fail(row, exc.key)
            continue
        run.resolve(row)
    if not stopped:
        _undo_sites(run, [r for r in rows if r.step["kind"] == "channel"])
    journal.set_order_status(
        order_id, "partially_undone" if unresolved(journal.actions(order_id)) else "undone")
    return errors


def _undo_sites(run: _UndoRun, rows: list[Action]) -> None:
    """Faza witryn: kanały wyłączone w naprawie włącza serwisant na ekranach otwieranych po kolei
    (pogrupowanych po przeglądarce). Najpierw odczyt każdego kanału: już włączony, wyłączony przed
    naprawą albo zniknięty — bez ekranu. Pominięty / przeterminowany krok zostaje „done”."""
    options = run.options
    by_package: dict[str, list[Action]] = {}
    for row in rows:  # dziennik zwraca wiersze w kolejności id
        by_package.setdefault(row.package, []).append(row)
    screens: list[tuple[Action, Step]] = []
    # Kilka wierszy na ten sam kanał (wspólny kanał Samsung Internet): jeden ekran dla wszystkich.
    same: dict[tuple[str, str], list[Action]] = {}
    for row in (r for group in by_package.values() for r in group):
        inverse = inverse_of(row)
        if row.status == "undone":
            continue
        if row.status == "failed" and (row.prev_state is None or inverse is None):
            continue  # krok nie zdążył niczego zmienić albo nie ma czego odwracać
        if options.should_stop():
            options.on_event({"type": "stopped"})
            return
        if row.prev_state is None:  # przerwane zlecenie: krok nie zdążył się zacząć
            run.resolve(row, "not_started")
            continue
        if inverse is None:  # kanał był wyłączony przed naprawą: nic nie zmieniliśmy
            run.resolve(row)
            continue
        if row.package in run.gone:  # przeglądarka nie wróciła w fazie automatycznej
            run.fail(row, "skipped")  # bez przeglądarki ekranu kanału nie otworzymy
            continue
        if run.app_missing(row, inverse):
            continue
        try:
            state = S.probe(run.adb, inverse)
        except ActionError as exc:
            if exc.uncertain:
                raise
            run.fail(row, exc.key)
            continue
        if state.get("importance") is None:
            # Przeglądarka usunęła kanał (np. wyczyszczone dane): zostaje instrukcja ręczna.
            run.journal.set_action_status(row.id, row.status, "channel_gone")
            run.fail(row, "channel_gone")
            continue
        if S.is_applied(inverse, state):
            run.resolve(row)  # już włączony (klient sam włączył albo naprawa go nie wyłączyła)
            continue
        if row.error == "channel_gone":  # kanał wrócił: nieaktualny błąd z poprzedniego cofania
            run.journal.set_action_status(row.id, row.status, None)
        key = (row.package, inverse.params["channel_id"])
        if key in same:
            same[key].append(row)
            continue
        same[key] = [row]
        screens.append((row, inverse))
    if not screens:
        return
    options.on_event({"type": "undo_sites",
                      "sites": [{"action_id": row.id, "package": row.package} for row, _ in screens]})
    timeouts = 0
    for row, inverse in screens:
        if options.should_stop():
            options.on_event({"type": "stopped"})
            return
        _emit(options, "undo", row, "running")
        try:
            result = _wait_for_user(run.adb, run.journal, row, inverse, options, ask=False)
        except ActionError as exc:
            if exc.uncertain:
                raise
            for each in same[(row.package, inverse.params["channel_id"])]:
                run.fail(each, exc.key)
            continue
        if result == "stopped":
            options.on_event({"type": "stopped"})
            return
        for each in same[(row.package, inverse.params["channel_id"])]:
            if result == "done":
                # ten sam kanał: odczyt w oczekiwaniu potwierdził włączenie
                run.resolve(each, via_screen=True)
            else:
                run.fail(each, "site_timeout" if result == "timeout" else "site_skipped")
        if result == "done" and len(screens) == 1:
            _open_site(run.adb, inverse)  # przy jednej witrynie nic jej potem nie zasłoni
        timeouts = timeouts + 1 if result == "timeout" else 0
        if timeouts >= SITE_TIMEOUTS_IN_A_ROW:
            options.on_event({"type": "stopped"})  # jak „Wstrzymaj”: reszta do włączenia z historii
            return


def _open_site(adb: AdbTransport, step: Step) -> None:
    """Strona po włączeniu kanału musi się zapisać od nowa (Chrome wypisuje ją przy cofnięciu zgody).
    Nieudane otwarcie nie jest błędem cofania — kanał już jest włączony."""
    try:
        S.open_site(adb, step)
    except ActionError as exc:
        log.warning("open site after undo failed: %s %s", exc.key, exc)


def verify(adb: AdbTransport, journal: Journal, order_id: int) -> dict[str, list[str]]:
    """Ponowny odczyt stanu po wykonaniu: które kroki nie trzymają (np. aplikacja cofnęła zmianę)."""
    rows = [a for a in journal.actions(order_id)
            if a.status == "done" and a.step["kind"] in VERIFIED_KINDS]
    removed = {a.package for a in rows
               if a.step["kind"] == "installed" and a.step["params"].get("installed") == "0"}
    problems: dict[str, list[str]] = {}
    for row in rows:
        if row.package in removed and row.step["kind"] != "installed":
            continue  # usuniętej aplikacji nie da się odpytać o appops — liczy się samo usunięcie
        step = Step.from_dict(row.step)
        try:
            holds = S.is_applied(step, S.probe(adb, step))
        except ActionError as exc:
            if exc.uncertain:
                raise
            holds = False
        if not holds:
            problems.setdefault(row.package, []).append(step.kind)
    return problems
