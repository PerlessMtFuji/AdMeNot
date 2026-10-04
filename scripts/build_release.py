"""Buduje wydanie: dist/release/AdMeNot-<wersja>-setup.exe (spec: 2026-10-04-release-build-design.md).

    .venv\\Scripts\\python scripts\\build_release.py [--allow-dirty] [--device] [--iscc ŚCIEŻKA]

Kroki: warunki wstępne → dane (narzędzia, baza telefonów, UI) → PyInstaller → selfcheck →
wykaz licencji → Inno Setup → SHA-256 → VirusTotal (gdy VT_API_KEY) → notatki do wydania.
Podpis: ADMENOT_SIGN_CMD z `{file}` w miejscu ścieżki; bez niej wydanie jest niepodpisane.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))  # moduły obok skryptu
import virustotal

DIST = ROOT / "dist"
BUNDLE = DIST / "AdMeNot"
RELEASE = DIST / "release"
BUILD = ROOT / "build"
TOOLS = ROOT / "src" / "admenot" / "assets" / "tools" / "scrcpy"
DEFAULT_ISCC = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
UNSIGNED = "NIEPODPISANE — Windows SmartScreen pokaże ostrzeżenie"
TAIL_LINES = 30


class BuildError(Exception):
    def __init__(self, step: str, command: Sequence[object] | str, output: str = "") -> None:
        shown = command if isinstance(command, str) else " ".join(map(str, command))
        tail = "\n".join(output.splitlines()[-TAIL_LINES:])
        super().__init__(f"[{step}] {shown}\n{tail}".rstrip())
        self.step = step


def run(step: str, command: Sequence[object] | str, runner=subprocess.run, **kw) -> str:
    """Uruchamia krok i zwraca jego stdout; błąd = BuildError z końcówką wyjścia."""
    print(f"==> {step}", flush=True)
    args = command if isinstance(command, str) else [str(part) for part in command]
    result = runner(args, cwd=kw.pop("cwd", ROOT), capture_output=True, text=True,
                    encoding="utf-8", errors="replace", **kw)
    if result.returncode != 0:
        raise BuildError(step, command, (result.stdout or "") + (result.stderr or ""))
    return result.stdout or ""


def read_version(init: Path = ROOT / "src" / "admenot" / "__init__.py") -> str:
    match = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"$', init.read_text("utf-8"), re.MULTILINE)
    if not match:
        raise BuildError("wersja", str(init), 'brak __version__ = "x.y.z"')
    return match.group(1)


def windows_version(version: str) -> str:
    return f"{version}.0"


def setup_name(version: str, dirty: bool) -> str:
    return f"AdMeNot-{version}{'-dirty' if dirty else ''}-setup"


def check_clean(allow_dirty: bool, runner=subprocess.run) -> bool:
    dirty = bool(run("git", ["git", "status", "--porcelain"], runner).strip())
    if dirty and not allow_dirty:
        raise BuildError("git", "git status --porcelain",
                         "Drzewo gita ma niezatwierdzone zmiany — zatwierdź je albo użyj --allow-dirty.")
    return dirty


def find_iscc(explicit: Path | None) -> Path:
    path = explicit or DEFAULT_ISCC
    if not path.is_file():
        raise BuildError("iscc", str(path), "Nie znaleziono ISCC.exe (Inno Setup 6) — "
                                            "zainstaluj go albo wskaż --iscc.")
    return path


def stop_processes_in(directory: Path, runner=subprocess.run) -> None:
    """Kończy tylko procesy uruchomione z `directory` (adb z poprzedniej paczki blokuje pliki)."""
    pattern = (str(directory.resolve()) + "\\*").replace("'", "''")
    script = f"Get-Process | Where-Object {{ $_.Path -like '{pattern}' }} | Stop-Process -Force"
    run("zatrzymanie procesów paczki", ["powershell", "-NoProfile", "-Command", script], runner)


def write_sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(path.name + ".sha256").write_text(f"{digest} *{path.name}\n", "utf-8")
    return digest


def release_notes(version: str, setup: Path, digest: str, signed: bool,
                  vt: virustotal.VtResult | None) -> str:
    size = setup.stat().st_size / 1024**2
    lines = [f"# AdMeNot {version}", "",
             f"- Plik: `{setup.name}` ({size:.1f} MB)",
             f"- SHA-256: `{digest}`",
             f"- Podpis: {'podpisany' if signed else UNSIGNED}"]
    if vt is None:
        lines.append("- VirusTotal: nie sprawdzono")
    else:
        lines.append(f"- VirusTotal: {vt.detections}/{vt.engines} — {vt.link}")
        if vt.flagged:
            lines.append(f"  - zgłosiły: {', '.join(vt.flagged)}")
    lines += ["", "## Uwagi", "",
              "(wynik listy kontrolnej z docs/release.md; czego nie sprawdzono — wprost)", ""]
    return "\n".join(lines)
