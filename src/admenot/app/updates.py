"""Aktualizacje w GUI: wątek sprawdzania i widok dla UI (spec aktualizacji §4.3, §7).

Sprawdzanie niczego nie blokuje: błąd sieci zostawia stan z pamięci podręcznej, zły manifest
trafia do logu. Wyłączone ustawienie = zero zapytań; zapisany manifest działa dalej.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import Any

from admenot import __version__
from admenot.app.errors import log_exception
from admenot.net import client, update

FIRST_DELAY = 10.0  # s po starcie: bez spowalniania startu i wykrywania telefonu
INTERVAL = 6 * 3600.0


class UpdateService:
    def __init__(self, on_change: Callable[[], None], enabled: Callable[[], bool], *,
                 fetch: Callable[[], update.Manifest] = update.fetch,
                 version: str = __version__, first_delay: float = FIRST_DELAY,
                 interval: float = INTERVAL) -> None:
        self._on_change = on_change
        self._enabled = enabled
        self._fetch = fetch
        self._version = version
        self._first_delay = first_delay
        self._interval = interval
        self._lock = threading.Lock()
        self._state = update.state(update.cached(), version)
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def state(self) -> update.UpdateState:
        with self._lock:
            return self._state

    def check_now(self) -> update.UpdateState:
        try:
            update.store(self._fetch())
        except client.BackendError:
            pass  # offline, 404 przed pierwszym wydaniem, portal Wi-Fi — zostaje stan z pamięci
        except update.ManifestError as exc:
            log_exception(exc)
        new = update.state(update.cached(), self._version)
        with self._lock:
            changed = new != self._state
            self._state = new
        if changed:
            self._on_change()
        return new

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="admenot-updates")
            self._thread.start()

    def poke(self) -> None:
        """Sprawdź od razu (np. po włączeniu ustawienia)."""
        self._wake.set()

    def stop(self) -> None:
        self._stopped.set()
        self._wake.set()

    def _run(self) -> None:
        delay = self._first_delay
        while True:
            self._wake.wait(delay)
            self._wake.clear()
            if self._stopped.is_set():
                return
            try:
                if self._enabled():
                    self.check_now()
            except Exception as exc:  # noqa: BLE001 — wątek tła nie może zginąć (np. pełny dysk)
                with contextlib.suppress(Exception):  # sam log też może paść
                    log_exception(exc)
            delay = self._interval


def update_view(st: update.UpdateState, lang: str, *, dismissed: str | None,
                updated_to: str | None, installable: bool) -> dict[str, Any]:
    m = st.manifest
    available = None
    if st.available and m is not None:
        available = {"version": m.latest, "notes": m.notes_for(lang), "size": m.size}
    retired = None
    if st.retired and m is not None:
        retired = {"min_supported": m.min_supported, "reason": m.reason_for(lang)}
    notes = m.notes_for(lang) if updated_to and m is not None and m.latest == updated_to else None
    return {"available": available,
            "dismissed": available is not None and dismissed == available["version"],
            "retired": retired, "updated_to": updated_to, "updated_notes": notes,
            "installable": installable}
