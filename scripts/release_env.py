"""Środowisko Python wydania: zgodność z zamrożoną listą i wykaz komponentów (audyt 2026-10-11, REL-01).

    .venv\\Scripts\\python scripts\\release_env.py            # sprawdza zgodność z lockiem

`check()` porównuje zainstalowane dystrybucje z `packaging/requirements-release.lock`;
`inventory()` to wykaz do notatek wydania: nazwa, wersja i SHA-256 pliku RECORD (spis plików
dystrybucji z ich skrótami), żeby było wiadomo, co dokładnie trafiło do paczki.
"""

from __future__ import annotations

import hashlib
import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "packaging" / "requirements-release.lock"
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;#]+)")
# Projekt (instalowany w trybie edytowalnym) i sam instalator pakietów nie trafiają do paczki.
IGNORED = frozenset({"admenot", "pip"})


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_lock(path: Path = LOCK) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _PIN.match(line)
        if m is None:
            raise ValueError(f"{path.name}: nie przypięta linia {line!r}")
        pins[_norm(m.group(1))] = m.group(2)
    return pins


def installed() -> dict[str, str]:
    return {_norm(d.metadata["Name"]): d.version for d in metadata.distributions()
            if _norm(d.metadata["Name"]) not in IGNORED}


def check(lock: dict[str, str] | None = None, have: dict[str, str] | None = None) -> list[str]:
    """Rozbieżności: brak, inna wersja albo pakiet spoza listy."""
    lock = read_lock() if lock is None else lock
    have = installed() if have is None else have
    problems = [f"brak {name}=={want}" for name, want in sorted(lock.items()) if name not in have]
    problems += [f"{name}: {have[name]} zamiast {want}" for name, want in sorted(lock.items())
                 if name in have and have[name] != want]
    problems += [f"spoza listy: {name}=={version}" for name, version in sorted(have.items())
                 if name not in lock]
    return problems


def inventory() -> str:
    lines = []
    for dist in sorted(metadata.distributions(), key=lambda d: _norm(d.metadata["Name"])):
        name = _norm(dist.metadata["Name"])
        if name in IGNORED:
            continue
        record = dist.read_text("RECORD") or ""
        digest = hashlib.sha256(record.encode("utf-8")).hexdigest() if record else "-"
        lines.append(f"{name}=={dist.version}  RECORD-sha256={digest}")
    return "\n".join(lines) + "\n"


def main() -> int:
    problems = check()
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
