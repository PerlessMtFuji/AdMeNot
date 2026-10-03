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
from admenot.engine.journal.db import MAX_REPORT_SCREENSHOTS, Action, Journal, Order
from admenot.engine.phones.build import IMAGES_DIR
from admenot.engine.phones.provider import SILHOUETTE

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
    image: Path
    photo: str  # exact | approximate | none


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


def _outcome(actions: list[Action], still_active: bool) -> str:
    statuses = {a.status for a in actions}
    if "pending" in statuses:
        return "interrupted"
    if "undone" in statuses:  # cofnięcie wygrywa z (nieaktualną) weryfikacją
        return "partially_undone" if "done" in statuses else "undone"
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
    image = Path(phone["image"]) if phone.get("image") else SILHOUETTE
    if not image.is_file():
        # Ścieżka z migawki jest bezwzględna i może wskazywać katalog, którego już nie ma (program
        # przeniesiony/przeinstalowany) — spróbuj tej samej nazwy pliku pod bieżącymi zasobami,
        # tym samym układem co provider.py (`assets_dir()/phones/<slug>.webp`).
        relocated = (paths.assets_dir() / IMAGES_DIR / image.name) if phone.get("slug") else None
        image = relocated if relocated is not None and relocated.is_file() else SILHOUETTE
    confidence = phone.get("confidence") or "none"
    if phone.get("name") and confidence in ("manual", "exact"):
        name = phone["name"]
    else:
        brand = (dev.get("brand") or "").capitalize()
        name = (dev.get("market_name") or f"{brand} {dev.get('model') or ''}".strip()
                or order.device_model or order.device_serial)
    if image == SILHOUETTE:
        photo = "none"
    elif confidence == "approximate":
        photo = "approximate"
    else:
        photo = "exact"
    return DeviceBlock(
        name=name,
        model=dev.get("model") or order.device_model,
        android=dev.get("android_release") or None,
        serial=dev.get("serial") or order.device_serial,
        security_patch=dev.get("security_patch") or None,
        image=image,
        photo=photo,
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

    by_package: dict[str, list[Action]] = {}
    for action in journal.actions(order_id):
        by_package.setdefault(action.package, []).append(action)

    rows = [_row(package, scanned.get(package), lang, actions[0].level,
                 _outcome(actions, package in verification))
            for package, actions in by_package.items()]
    # Aplikacje bez uwag (safe) z oceną niepełną nie są wierszami — trafiają do zakresu skanu.
    untouched = {p: a for p, a in scanned.items() if p not in by_package}
    rows += [_row(package, app, lang, None, "none")
             for package, app in untouched.items() if app.get("verdict") != "safe"]

    device = device_block(snap or {}, order)
    scope, clean = None, None
    if snap is not None:
        hidden = [a for a in untouched.values() if a.get("verdict") == "safe"]
        incomplete_apps = sum(1 for a in hidden if a.get("incomplete"))
        scope = _scope(snap, incomplete_apps)
        if "app_count" in snap:
            in_rows = len(scanned) - len(hidden)
            clean = snap["app_count"] - in_rows - incomplete_apps
    return Protocol(order.number, order.created_at, order.client_name, device, rows, clean,
                    _recommendations(rows, device, order.created_at, scope), snap is not None,
                    lang, scope, _screenshots(journal, order_id))
