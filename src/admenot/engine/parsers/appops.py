from __future__ import annotations

import re
from dataclasses import dataclass

from admenot.engine.parsers.common import parse_duration

_OP = re.compile(r"^(Uid mode: )?([A-Z][A-Z0-9_]+): ([a-z_]+)(.*)$")
_LEGACY_TIME = re.compile(r"(?<![A-Za-z])time=\+?([0-9dhms]+)")
_ACCESS_AGO = re.compile(r"\(-?([0-9dhms]+)\)")


@dataclass
class AppOpState:
    mode: str
    last_access_s: float | None = None

    def note_access(self, seconds: float | None) -> None:
        if seconds is None:
            return
        if self.last_access_s is None or seconds < self.last_access_s:
            self.last_access_s = seconds


def parse_appops(text: str) -> dict[str, AppOpState]:
    ops: dict[str, AppOpState] = {}
    package_modes: set[str] = set()
    current: AppOpState | None = None

    for raw in text.splitlines():
        if not raw.strip():
            continue
        if not raw.startswith(" "):
            m = _OP.match(raw.strip())
            if not m:
                current = None
                continue
            is_uid_mode, name, mode, rest = bool(m.group(1)), m.group(2), m.group(3), m.group(4)
            state = ops.setdefault(name, AppOpState(mode))
            if not is_uid_mode:
                state.mode = mode
                package_modes.add(name)
            elif name not in package_modes:
                state.mode = mode
            if t := _LEGACY_TIME.search(rest):
                state.note_access(parse_duration(t.group(1)))
            current = state
        elif current is not None and raw.strip().startswith("Access:"):
            if m := _ACCESS_AGO.search(raw):
                current.note_access(parse_duration(m.group(1)))
    return ops
