"""Dołączone narzędzia (Plan 6b, spec §3.2): który adb i który scrcpy.

Kolejność adb: ścieżka z Ustawień → dołączony (`assets/tools/scrcpy/adb.exe`) → PATH.
scrcpy jest tylko dołączony (`scripts/fetch_tools.py`). Program i scrcpy muszą używać tego
samego adb, bo dwa serwery adb w różnych wersjach wzajemnie się ubijają.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from admenot.engine.paths import assets_dir

AdbSource = Literal["settings", "bundled", "path", "missing"]


def tools_dir() -> Path:
    return assets_dir() / "tools" / "scrcpy"


@dataclass(frozen=True)
class ToolPath:
    path: str | None
    source: AdbSource


def resolve_adb(configured: str | None = None) -> ToolPath:
    if configured and configured.strip():
        return ToolPath(configured.strip(), "settings")
    bundled = tools_dir() / "adb.exe"
    if bundled.is_file():
        return ToolPath(str(bundled), "bundled")
    found = shutil.which("adb")
    return ToolPath(found, "path") if found else ToolPath(None, "missing")


def resolve_scrcpy() -> Path | None:
    exe = tools_dir() / "scrcpy.exe"
    return exe if exe.is_file() and (tools_dir() / "scrcpy-server").is_file() else None
