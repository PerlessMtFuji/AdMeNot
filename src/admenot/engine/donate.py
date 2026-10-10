"""Przypomnienie o wsparciu projektu (spec kroku J §4).

Pierwsze po `FIRST` udanym zleceniu, potem co `EVERY` udanych zleceń, nie częściej niż raz na
`MIN_DAYS` dni. Stan w kluczach wewnętrznych `donate_*` w `settings.json`. Błąd zapisu nigdy
nie psuje naprawy: wtedy przypomnienia po prostu nie ma.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from admenot.engine.settings import Settings, SettingsTooNew, load_settings, save_internal

if TYPE_CHECKING:
    from admenot.engine.workflow import OrderResult

FIRST = 1
EVERY = 5
MIN_DAYS = 14


def succeeded(result: OrderResult) -> bool:
    # Po `resume` `apps` to tylko dokończona część; o całym zleceniu mówi jego status w dzienniku.
    return (not result.stopped and result.order.status == "done" and bool(result.apps)
            and all(a.status == "ok" for a in result.apps))


def _shown(settings: Settings, today: date) -> date | None:
    """Dzień ostatniego przypomnienia; data z przyszłości (cofnięty zegar) albo zła = brak."""
    if settings.donate_shown_at is None:
        return None
    try:
        shown = date.fromisoformat(settings.donate_shown_at)
    except ValueError:
        return None
    return None if shown > today else shown


def _due(settings: Settings, count: int, today: date) -> bool:
    if settings.donate_off:
        return False
    shown = _shown(settings, today)
    if shown is None:
        return count >= FIRST
    return count >= EVERY and (today - shown).days >= MIN_DAYS


def _save(changes: dict[str, Any]) -> bool:
    try:
        save_internal(changes)
    except (OSError, SettingsTooNew):
        return False
    return True


def note_success(now: datetime) -> bool:
    """Udane zlecenie w GUI: True = pokaż przypomnienie (licznik zerowany, data zapisana)."""
    settings = load_settings()
    today = now.date()
    count = settings.donate_count + 1
    if _due(settings, count, today):
        return _save({"donate_count": 0, "donate_shown_at": today.isoformat()})
    _save({"donate_count": count})
    return False


def count_success() -> None:
    """Udane zlecenie w CLI: tylko licznik — przypomnienie pokazuje GUI."""
    _save({"donate_count": load_settings().donate_count + 1})


def set_reminders(on: bool) -> Settings:
    return save_internal({"donate_off": not on})
