"""Nagrania testowe: publiczne (w gicie) i prywatne (ignorowane przez git, tylko u autora).

Prywatne nagranie (np. telefon właściciela, T2) nie może po cichu zmieniać wyniku zwykłego
`pytest` na jednym stanowisku — wtedy zielony przebieg znaczyłby co innego na świeżym klonie
(audyt 2026-10-11, QA-02). Włącza się je jawnie: ADMENOT_PRIVATE_FIXTURES=1.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
PRIVATE_ENV = "ADMENOT_PRIVATE_FIXTURES"


def is_private(directory: Path) -> bool:
    try:
        result = subprocess.run(["git", "check-ignore", "-q", str(directory)], cwd=FIXTURES,
                                capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def fixture_dirs(marker: str) -> list[Path]:
    """Katalogi nagrań z plikiem `marker`; prywatne tylko z ADMENOT_PRIVATE_FIXTURES=1."""
    found = sorted(p.parent for p in FIXTURES.glob(f"*/{marker}"))
    if os.environ.get(PRIVATE_ENV) == "1":
        return found
    return [d for d in found if not is_private(d)]
