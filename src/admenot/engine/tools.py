"""Dołączone narzędzia (Plan 6b, spec §3.2): który adb i który scrcpy.

Kolejność adb: ścieżka z Ustawień → dołączony (`assets/tools/scrcpy/adb.exe`) → PATH.
scrcpy jest tylko dołączony (`scripts/fetch_tools.py`). Program i scrcpy muszą używać tego
samego adb, bo dwa serwery adb w różnych wersjach wzajemnie się ubijają.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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


CREATE_NO_WINDOW = 0x08000000


def scrcpy_env(adb: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if adb:
        env["ADB"] = adb  # ten sam adb co program (patrz wyżej)
    return env


def spawn_scrcpy(cmd: list[str], env: dict[str, str]) -> subprocess.Popen[bytes]:
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0  # bez konsoli; okno SDL zostaje
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=env, creationflags=flags)


def kill_tree(proc: Any) -> None:
    if sys.platform == "win32":
        # /T: razem z procesami adb uruchomionymi przez scrcpy — trzymają rurę wyjścia, więc samo
        # zabicie scrcpy.exe zostawiłoby czytającego na zawsze (serwer na telefonie sprząta sam)
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                       stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, check=False)
    else:
        proc.terminate()
