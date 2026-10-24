"""Model protokołu (spec §9.3): zlecenie z dziennika + migawka skanu → wiersze, działania, zalecenia.

Czysta logika bez tekstów; teksty PL/EN dokłada render.py.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from admenot.engine import paths
from admenot.engine.actions.planner import FIX_LEVEL
from admenot.engine.journal.db import MAX_REPORT_SCREENSHOTS, Action, Journal, Order, unresolved

PATCH_MAX_AGE_DAYS = 365
UNFINISHED = frozenset({"failed", "interrupted", "still_active"})
FLAGGED = frozenset({"malicious", "suspicious", "review"})
MAX_NAMED = 3  # zalecenie „review_left” wymienia nazwy najwyżej tylu aplikacji


@dataclass(frozen=True)
class DeviceBlock:
    name: str
    model: str | None
    android: str | None
    serial: str
    security_patch: str | None
    imei: str | None = None  # w protokole zamiast numeru seryjnego, gdy dało się go odczytać


@dataclass(frozen=True)
class AppRow:
    package: str
    label: str | None
    verdict: str | None
    problems: list[str]
    level: str | None
    outcome: str  # done | still_active | failed | interrupted | undone | partially_undone | none
    incomplete: bool = False
    gaps: list[str] = field(default_factory=list)
    icon: str | None = None  # data URI z migawki; render przepuszcza tylko rozpoznane bitmapy


@dataclass(frozen=True)
class ScanScope:
    """Czego skan nie objął — protokół nie może mówić „bez uwag” ponad ten zakres."""

    other_profiles: list[int]
    profiles_known: bool
    low_behavior_data: bool
    usage_window_h: float | None
    incomplete_apps: int  # aplikacje `safe` z oceną niepełną (poza tabelą)

    @property
    def limited(self) -> bool:
        return (bool(self.other_profiles) or not self.profiles_known or self.low_behavior_data
                or self.incomplete_apps > 0)


@dataclass(frozen=True)
class Recommendation:
    key: str
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProtocolShot:
    image: Path  # kopia JPG (Plan 6b §5.1)
    taken_at: datetime
    context: dict[str, Any]


@dataclass(frozen=True)
class Consent:
    code: str
    shown_at: datetime
    confirmed_at: datetime


@dataclass(frozen=True)
class PhoneCheckRow:
    browser: str
    domain: str | None  # None = wszystkie witryny przeglądarki (wspólny kanał) albo nieodczytane
    before: str  # active | allowed | shared | unrecognized
    outcome: str  # done | failed | interrupted | undone | partially_undone | none


@dataclass(frozen=True)
class PhoneCheck:
    id: str
    state: str  # ok | review | unrecognized
    rows: list[PhoneCheckRow]


@dataclass(frozen=True)
class Protocol:
    number: str
    created_at: datetime
    client_name: str | None
    device: DeviceBlock
    rows: list[AppRow]
    clean_count: int | None
    recommendations: list[Recommendation]
    has_scan: bool
    lang: str
    scope: ScanScope | None = None
    screenshots: list[ProtocolShot] = field(default_factory=list)
    consent: Consent | None = None
    manual: bool = False  # tryb ręczny: bez nagłówka „czysto” i bez liczby aplikacji bez uwag
    phone_checks: list[PhoneCheck] = field(default_factory=list)  # „Stan telefonu”


def _outcome(actions: list[Action], still_active: bool) -> str:
    statuses = {a.status for a in actions}
    if "pending" in statuses:
        return "interrupted"
    if "undone" in statuses:  # cofnięcie wygrywa z (nieaktualną) weryfikacją
        # „failed” z zapisanym krokiem odwrotnym mógł zmienić telefon, a nie został cofnięty
        # (audyt 2026-10-11, BUG-09) — to cofnięcie częściowe, nie pełne.
        return "partially_undone" if unresolved(actions) else "undone"
    if "failed" in statuses:
        return "failed"
    return "still_active" if still_active else "done"


def _row(package: str, app: dict[str, Any] | None, lang: str, level: str | None,
         outcome: str) -> AppRow:
    app = app or {}
    problems = app.get("problems") or {}
    return AppRow(package, app.get("label"), app.get("verdict"),
                  list(problems.get(lang) or problems.get("pl") or []), level, outcome,
                  bool(app.get("incomplete")), list(app.get("gaps") or []), app.get("icon"))


def _consent(snap: dict[str, Any] | None) -> Consent | None:
    """Zgoda z migawki (spec plan-qr §5.4); uszkodzony wpis = brak linijki, nie błąd protokołu."""
    raw = (snap or {}).get("consent")
    if not isinstance(raw, dict) or not isinstance(raw.get("code"), str):
        return None
    try:
        return Consent(raw["code"], datetime.fromisoformat(raw["shown_at"]),
                       datetime.fromisoformat(raw["confirmed_at"]))
    except (KeyError, TypeError, ValueError):
        return None


def _scope(snap: dict[str, Any], incomplete_apps: int) -> ScanScope:
    scope = snap.get("scope") or {}
    profiles = scope.get("profiles") or {}
    scanned = profiles.get("scanned") or []
    present = profiles.get("present")
    return ScanScope(
        other_profiles=[u for u in (present or []) if u not in scanned],
        profiles_known=present is not None,
        low_behavior_data=bool(scope.get("low_behavior_data")),
        usage_window_h=scope.get("usage_window_h"),
        incomplete_apps=incomplete_apps,
    )


def device_block(snap: dict[str, Any], order: Order) -> DeviceBlock:
    dev = snap.get("device") or {}
    phone = snap.get("phone") or {}
    confidence = phone.get("confidence") or "none"
    if phone.get("name") and confidence in ("manual", "exact"):
        name = phone["name"]
    else:
        brand = (dev.get("brand") or "").capitalize()
        name = (dev.get("market_name") or f"{brand} {dev.get('model') or ''}".strip()
                or order.device_model or order.device_serial)
    return DeviceBlock(
        name=name,
        model=dev.get("model") or order.device_model,
        android=dev.get("android_release") or None,
        serial=dev.get("serial") or order.device_serial,
        security_patch=dev.get("security_patch") or None,
        imei=dev.get("imei") or None,
    )


def _names(rows: Iterable[AppRow]) -> str:
    return ", ".join(r.label or r.package for r in rows)


def _patch_is_old(patch: str | None, when: datetime) -> bool:
    try:
        day = date.fromisoformat(patch or "")
    except ValueError:
        return False
    return (when.date() - day).days > PATCH_MAX_AGE_DAYS


def _recommendations(rows: list[AppRow], device: DeviceBlock, created_at: datetime,
                     scope: ScanScope | None) -> list[Recommendation]:
    recs: list[Recommendation] = []
    unfinished = [r for r in rows if r.outcome in UNFINISHED]
    if unfinished:
        recs.append(Recommendation("unfinished", {"apps": _names(unfinished)}))
    # Aplikacja oznaczona do sprawdzenia, którą nie ruszano albo której cofnięcie (całe lub
    # częściowe) zostawiło na telefonie, wciąż wymaga uwagi klienta.
    left = [r for r in rows
            if r.outcome in ("none", "undone", "partially_undone") and r.verdict in FLAGGED]
    if len(left) > MAX_NAMED:  # długa lista nazw w zaleceniu dublowałaby tabelę i listę
        recs.append(Recommendation("review_left_many", {"count": str(len(left))}))
    elif left:
        recs.append(Recommendation("review_left", {"apps": _names(left)}))
    if (scope is not None and scope.limited) or any(r.incomplete for r in rows):
        recs.append(Recommendation("incomplete_scan"))
    done = {r.level for r in rows if r.outcome == "done"}
    if "remove" in done:
        recs.append(Recommendation("removed"))
    if "disable" in done:
        recs.append(Recommendation("disabled"))
    if _patch_is_old(device.security_patch, created_at):
        recs.append(Recommendation("old_patch", {"date": device.security_patch or ""}))
    recs.append(Recommendation("general"))
    return recs


def _fix_key(action: Action) -> tuple[str, str] | None:
    """(pakiet, klucz) poprawki, którą wykonuje krok: id kanału albo origin zgody Firefoksa."""
    params = action.step.get("params") or {}
    if action.step.get("kind") == "channel":
        return action.package, str(params.get("channel_id") or "")
    if action.step.get("kind") == "site_permission":
        return action.package, str(params.get("origin") or "")
    return None


def _fix_outcomes(actions: list[Action]) -> dict[tuple[str, str], str]:
    grouped: dict[tuple[str, str], list[Action]] = {}
    for action in actions:
        if action.level == FIX_LEVEL and (key := _fix_key(action)):
            grouped.setdefault(key, []).append(action)
    return {key: _outcome(group, False) for key, group in grouped.items()}


def _site_key(fix: str | None) -> str:
    """Klucz kroku z id poprawki: `site:<pkg>:<kanał>` i `site_perm:<pkg>:<origin>`."""
    parts = (fix or "").split(":", 2)
    return parts[2] if len(parts) == 3 else ""


def _browser_rows(b: dict[str, Any], outcomes: dict[tuple[str, str], str]) -> list[PhoneCheckRow]:
    package, name = b.get("package") or "", b.get("name") or b.get("package") or ""
    if b.get("read") in ("unrecognized", "unsupported"):  # nieodczytana albo nieobsługiwana: nie sprawdzono
        return [PhoneCheckRow(name, None, b["read"], "none")]
    rows, site_keys = [], set()
    for site in b.get("sites") or []:
        key = _site_key(site.get("fix"))
        site_keys.add(key)
        outcome = outcomes.get((package, key), "none")
        if site.get("blocked") and outcome == "none":
            continue  # wyłączone jeszcze przed zleceniem: nic do pokazania
        rows.append(PhoneCheckRow(name, site.get("host"),
                                  "active" if site.get("active") else "allowed", outcome))
    if b.get("read") == "partial" or b.get("all_fix"):  # wspólny kanał: krok nie należy do witryny
        shared = next((o for (pkg, key), o in outcomes.items()
                       if pkg == package and key not in site_keys), "none")
        rows.append(PhoneCheckRow(name, None, "shared", shared))
    return rows


def _phone_checks(snap: dict[str, Any] | None, actions: list[Action]) -> list[PhoneCheck]:
    """Kontrole „Stanu telefonu” z migawki + wynik poprawek z dziennika. Stara migawka bez klucza
    daje pustą listę (sekcji nie ma)."""
    outcomes = _fix_outcomes(actions)
    return [PhoneCheck(raw.get("id") or "", raw.get("state") or "unrecognized",
                       [row for b in raw.get("browsers") or [] for row in _browser_rows(b, outcomes)])
            for raw in (snap or {}).get("device_checks") or []]


def _screenshots(journal: Journal, order_id: int) -> list[ProtocolShot]:
    chosen = [s for s in journal.screenshots(order_id) if s.in_report][-MAX_REPORT_SCREENSHOTS:]
    shots = []
    for shot in chosen:
        _png, jpg = paths.screenshot_files(shot.id)
        if jpg.is_file():  # bez kopii (uszkodzony PNG) zrzut nie trafia do protokołu
            shots.append(ProtocolShot(jpg, shot.taken_at, shot.context))
    return shots


def build_protocol(journal: Journal, order_id: int, lang: str) -> Protocol:
    order = journal.order(order_id)
    snap = journal.scan(order_id)
    verification = journal.verification(order_id) or {}
    scanned = {a["package"]: a for a in (snap or {}).get("apps", [])}
    manual = (snap or {}).get("apk_mode") in ("manual", "partial")
    if manual:
        # Werdykt heurystyk aplikacji wybranej na ślepo był przed serwisantem ukryty: w protokole
        # bez oceny, problemów i zaleceń z niej (migawka zostaje nietknięta jako dowód).
        seen = set((snap or {}).get("on_demand") or [])
        scanned = {p: a if p in seen else {**a, "verdict": None, "problems": {}, "incomplete": False}
                   for p, a in scanned.items()}

    all_actions = journal.actions(order_id)
    by_package: dict[str, list[Action]] = {}
    for action in all_actions:
        if action.level != FIX_LEVEL:  # poprawki telefonu to nie wiersze aplikacji
            by_package.setdefault(action.package, []).append(action)

    rows = [_row(package, scanned.get(package), lang, actions[0].level,
                 _outcome(actions, package in verification))
            for package, actions in by_package.items()]
    # Aplikacje bez uwag (safe) z oceną niepełną nie są wierszami — trafiają do zakresu skanu.
    untouched = {p: a for p, a in scanned.items() if p not in by_package}
    rows += [_row(package, app, lang, None, "none")
             for package, app in untouched.items() if app.get("verdict") not in (None, "safe")]

    device = device_block(snap or {}, order)
    scope, clean = None, None
    if snap is not None:
        hidden = [a for a in untouched.values() if a.get("verdict") == "safe"]
        incomplete_apps = sum(1 for a in hidden if a.get("incomplete"))
        scope = _scope(snap, incomplete_apps)
        if "app_count" in snap and not manual:
            in_rows = len(scanned) - len(hidden)
            clean = snap["app_count"] - in_rows - incomplete_apps
    return Protocol(order.number, order.created_at, order.client_name, device, rows, clean,
                    _recommendations(rows, device, order.created_at, scope), snap is not None,
                    lang, scope, _screenshots(journal, order_id), consent=_consent(snap),
                    manual=manual, phone_checks=_phone_checks(snap, all_actions))
