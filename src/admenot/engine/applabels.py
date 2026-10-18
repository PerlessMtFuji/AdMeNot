"""Nazwy aplikacji z telefonu bez pobierania APK (tryb ręczny): `scrcpy --list-apps`.

scrcpy-server pyta PackageManager o etykiety w języku telefonu (~3 s na OPPO CPH2271). Lista
obejmuje tylko aplikacje z ikoną w menu — reszta zostaje przy nazwie pakietu, aż do analizy APK,
której etykieta ma pierwszeństwo. Wyjście scrcpy 4.1: tests/fixtures/scrcpy/list-apps-*.txt,
wiersz ` * Etykieta<spacje>pakiet` (`*` systemowa, `-` użytkownika). Błąd albo brak scrcpy = {}.

Po `TIMEOUT_S` albo po `stop` scrcpy ginie razem z procesami adb (`kill_tree`): to one trzymają
rurę wyjścia, więc czekanie na koniec samego scrcpy.exe mogłoby trwać w nieskończoność.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from admenot.engine.apk.analyze import clean_label
from admenot.engine.tools import kill_tree, resolve_scrcpy, scrcpy_env, spawn_scrcpy

TIMEOUT_S = 30.0
KILL_WAIT_S = 5.0  # po zabiciu drzewa procesów rura zamyka się od razu; to tylko bezpiecznik
_ROW = re.compile(r"^ [*-] (?P<label>.*?)\s+(?P<package>[A-Za-z][\w.]*)\s*$")


@dataclass(frozen=True)
class PhoneLabel:
    label: str
    padded: bool  # zaczyna się od niewidocznych znaków (sztuczka „na górę listy”, reguła DM-LABEL-02)


def parse_list_apps(output: str) -> dict[str, PhoneLabel]:
    labels: dict[str, PhoneLabel] = {}
    for line in output.splitlines():
        row = _ROW.match(line)
        if row:
            label, padded = clean_label(row["label"])
            if label:
                labels[row["package"]] = PhoneLabel(label, padded)
    return labels


def _read(proc: Any, lines: list[str], on_line: Callable[[str], None]) -> None:
    for raw in proc.stdout or ():
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        lines.append(line)
        if not _ROW.match(line):  # do logu komunikaty scrcpy, nie setki wierszy listy
            on_line(line)


def list_apps(serial: str, adb: str | None, stop: threading.Event,
              on_line: Callable[[str], None] = lambda line: None, *,
              spawn: Callable[[list[str], dict[str, str]], Any] = spawn_scrcpy,
              kill: Callable[[Any], None] = kill_tree,
              timeout: float = TIMEOUT_S) -> dict[str, PhoneLabel]:
    exe = resolve_scrcpy()
    if exe is None:
        return {}
    on_line(f"--list-apps (nazwy aplikacji, {serial})")
    try:
        proc = spawn([str(exe), "--serial", serial, "--list-apps"], scrcpy_env(adb))
    except OSError as exc:
        on_line(f"--list-apps: {exc}")
        return {}
    lines: list[str] = []
    reader = threading.Thread(target=_read, args=(proc, lines, on_line), daemon=True,
                              name="admenot-labels-read")
    reader.start()
    deadline = time.monotonic() + timeout
    while reader.is_alive():  # koniec czytania = rurę zamknęli wszyscy, także procesy adb
        if stop.is_set() or time.monotonic() >= deadline:
            kill(proc)
            reader.join(KILL_WAIT_S)
            if not stop.is_set():
                on_line(f"--list-apps: brak odpowiedzi po {timeout:.0f} s, przerwano")
            return {}
        reader.join(0.1)
    labels = parse_list_apps("\n".join(lines))
    on_line(f"--list-apps: {len(labels)} nazw")
    return labels


class LabelFetch:
    """`fetch` na osobnym wątku, równolegle ze skanem; `cancel()` przerywa scrcpy.

    Wyjątek z `fetch` trafia do `on_error` (log błędów), a wynik jest wtedy pusty.
    """

    def __init__(self, fetch: Callable[[threading.Event], dict[str, PhoneLabel]],
                 on_error: Callable[[Exception], None]) -> None:
        self._fetch, self._on_error = fetch, on_error
        self._stop = threading.Event()
        self._found: dict[str, PhoneLabel] = {}
        self._thread = threading.Thread(target=self._run, daemon=True, name="admenot-labels")
        self._thread.start()

    def _run(self) -> None:
        try:
            self._found = self._fetch(self._stop)
        except Exception as exc:  # noqa: BLE001 — same nazwy nie mogą przerwać skanu
            self._on_error(exc)

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def wait(self, check: Callable[[], None] = lambda: None,
             timeout: float | None = None) -> dict[str, PhoneLabel]:
        """Czeka na wynik; `check` co chwilę (zatrzymanie zadania), `timeout` = najwyżej tyle."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._thread.is_alive() and (deadline is None or time.monotonic() < deadline):
            check()
            self._thread.join(0.2)
        return {} if self._thread.is_alive() else dict(self._found)

    def cancel(self) -> None:
        self._stop.set()
