"""Oś czasu incydentu: kto rysował ekran i kto wysłał powiadomienie, gdy klient zgłosił reklamę.

Ocena 2026-10-01 §7.4. „Nie odczytano” (None) nigdy nie znaczy „nic nie było”.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.collectors.behavior import NOTIFICATIONS
from admenot.engine.foreground import read_foreground
from admenot.engine.parsers.common import UnrecognizedOutput
from admenot.engine.parsers.notifications import parse_notifications

KIND_ORDER = ("overlay", "new_notification", "foreground")
# Nagranie starsze niż doba nie opisuje już stanu telefonu przy następnym skanie.
INCIDENT_MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True)
class Sample:
    t: float
    resumed: str | None
    overlays: list[str] | None
    notif_active: dict[str, int] | None
    errors: list[str]


@dataclass
class Timeline:
    samples: list[Sample] = field(default_factory=list)
    marks: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class Attribution:
    mark: float
    package: str
    kind: str
    over: str | None
    sample_t: float


def _sample(adb: AdbTransport, t: float) -> Sample:
    fg = read_foreground(adb)
    errors = list(fg.errors)
    notif: dict[str, int] | None
    try:
        notif = {p: s.active for p, s in parse_notifications(adb.shell(NOTIFICATIONS, timeout=30)).items()}
    except AdbError as exc:
        notif = None
        errors.append(f"notifications: {exc.message}")
    except UnrecognizedOutput as exc:
        notif = None
        errors.append(f"notifications: {exc}")
    return Sample(t, fg.resumed, fg.overlays, notif, errors)


def record(adb: AdbTransport, duration_s: float, interval_s: float, *,
           clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
           poll_mark: Callable[[], bool] = lambda: False) -> Timeline:
    start = clock()
    timeline = Timeline()
    try:
        while (now := clock() - start) < duration_s:
            timeline.samples.append(_sample(adb, now))
            if poll_mark():
                timeline.marks.append(now)
            sleep(interval_s)
    except KeyboardInterrupt:
        return timeline  # Ctrl+C kończy nagranie wcześniej — zebrane próbki zostają
    if timeline.samples and poll_mark():  # Enter w ostatnim odstępie: przy ostatniej próbce
        timeline.marks.append(timeline.samples[-1].t + interval_s)
    return timeline


def attribute(timeline: Timeline, window_s: float = 3.0) -> list[Attribution]:
    found: list[Attribution] = []
    samples = timeline.samples
    for mark in timeline.marks:
        near = [(i, s) for i, s in enumerate(samples) if abs(s.t - mark) <= window_s]
        seen: set[tuple[str, str]] = set()
        for i, s in near:
            hits: list[tuple[str, str]] = [(pkg, "overlay") for pkg in s.overlays or ()]
            prev = samples[i - 1].notif_active if i > 0 else None
            if s.notif_active is not None and prev is not None:
                hits += [(p, "new_notification") for p, n in s.notif_active.items() if n > prev.get(p, 0)]
            if s.resumed:
                hits.append((s.resumed, "foreground"))
            for pkg, kind in hits:
                if (pkg, kind) not in seen:
                    seen.add((pkg, kind))
                    found.append(Attribution(mark, pkg, kind, s.resumed if kind == "overlay" else None, s.t))
    found.sort(key=lambda a: (a.mark, KIND_ORDER.index(a.kind)))
    return found


def incident_facts(attributions: list[Attribution]) -> dict[str, tuple[int, str | None]]:
    """Pakiet → (ile znaczników z jego nakładką, nad jaką aplikacją ostatnio)."""
    out: dict[str, tuple[int, str | None]] = {}
    for a in attributions:
        if a.kind != "overlay":
            continue
        count, _ = out.get(a.package, (0, None))
        out[a.package] = (count + 1, a.over)
    return out


def save_incident(path: Path, timeline: Timeline, recorded_at: datetime) -> bool:
    """Oś czasu i przypisania do pliku telefonu; następny `scan` ustawia z niego `incident_hits`.

    Bez znaczników nic nie zapisuje (False): nagranie bez zgłoszenia nie zastępuje wcześniejszego.
    Gdy przy którymś znaczniku nic nie odczytano, fakty są „nie ustalono” (`facts: null`).
    """
    if not timeline.marks:
        return False
    attributions = attribute(timeline)
    unread = any(not any(a.mark == m for a in attributions) for m in timeline.marks)
    data = {
        "version": 1,
        "recorded_at": recorded_at.isoformat(),
        "timeline": asdict(timeline),
        "attributions": [asdict(a) for a in attributions],
        "facts": None if unread else {p: list(v) for p, v in incident_facts(attributions).items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return True


def load_incident(path: Path, now: datetime,
                  max_age: timedelta = INCIDENT_MAX_AGE) -> dict[str, tuple[int, str | None]] | None:
    """Fakty incydentu z nagrania albo None (brak, uszkodzone, za stare = nie było nagrania)."""
    try:
        data = json.loads(Path(path).read_text("utf-8"))
        recorded_at = datetime.fromisoformat(data["recorded_at"])
        if not timedelta(0) <= now - recorded_at <= max_age or data["facts"] is None:
            return None
        return {str(p): (int(n), over if isinstance(over, str) else None)
                for p, (n, over) in data["facts"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return None
