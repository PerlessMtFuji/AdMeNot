"""`dumpsys alarm`, sekcja „Alarm Stats:” — liczniki od startu telefonu, per pakiet."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Czas w formacie Androida: +1d2h3m4s567ms (dni/godziny/minuty/sekundy/ms).
# uid u<N>a<M> to profil N (aplikacyjny appId M); samo uid liczbowe koduje profil jako uid // 100000.
HEADER = re.compile(r"^  (?:u(\d+)a\d+|(\d+)):([A-Za-z][\w.]*) \+[0-9dhms]+ running, (\d+) wakeups:$")
LINE = re.compile(r"^    \+[0-9dhms]+ (\d+) wakes (\d+) alarms, last [-+]?[0-9dhms]+:$")
SECTION = "  Alarm Stats:"
PER_USER_RANGE = 100000  # uid = użytkownik * 100000 + appId


@dataclass
class AlarmStats:
    wakeups: int = 0
    alarms: int = 0


def parse_alarm_stats(text: str) -> dict[str, AlarmStats] | None:
    stats: dict[str, AlarmStats] = {}
    in_section = False
    current: AlarmStats | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line == SECTION:
            in_section = True
            continue
        if not in_section or not line.strip():
            continue
        if m := HEADER.match(line):
            user = int(m.group(1)) if m.group(1) is not None else int(m.group(2)) // PER_USER_RANGE
            if user != 0:
                current = None  # inny profil — nie mieszamy z aplikacją użytkownika 0
                continue
            current = stats.setdefault(m.group(3), AlarmStats())
            current.wakeups += int(m.group(4))
        elif m := LINE.match(line):
            if current is not None:
                current.alarms += int(m.group(2))
        elif len(line) - len(line.lstrip(" ")) <= 2:
            break  # następna sekcja (np. „Alarm manager stats:”)
    return stats if in_section else None
