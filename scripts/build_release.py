"""Buduje wydanie: dist/release/AdMeNot-<wersja>-setup.exe (spec: 2026-10-04-release-build-design.md).

    .venv\\Scripts\\python scripts\\build_release.py [--allow-dirty] [--device] [--iscc ŚCIEŻKA]

Kroki: warunki wstępne → dane (narzędzia, baza telefonów, UI) → PyInstaller → selfcheck →
wykaz licencji → Inno Setup → SHA-256 → VirusTotal (gdy VT_API_KEY) → notatki do wydania.
Podpis: ADMENOT_SIGN_CMD z `{file}` w miejscu ścieżki; bez niej wydanie jest niepodpisane.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # moduły obok skryptu
import third_party_notices
import virustotal

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUNDLE = DIST / "AdMeNot"
RELEASE = DIST / "release"
BUILD = ROOT / "build"
TOOLS = ROOT / "src" / "admenot" / "assets" / "tools" / "scrcpy"
SPEC = ROOT / "packaging" / "admenot.spec"
ISS = ROOT / "packaging" / "admenot.iss"
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"  # bootstrapper Evergreen
WEBVIEW2_SETUP = BUILD / "MicrosoftEdgeWebview2Setup.exe"
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


def check_release_deps() -> None:
    missing = [name for name in ("PyInstaller", "webview") if importlib.util.find_spec(name) is None]
    if missing:
        raise BuildError("zależności", "import " + ", ".join(missing),
                         '.venv\\Scripts\\pip install -e ".[dev,gui,release]"')


def download(url: str, dest: Path) -> None:
    print(f"==> pobieranie {dest.name}", flush=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, part.open("wb") as fh:
        shutil.copyfileobj(response, fh)
    os.replace(part, dest)


def sign(path: Path, template: str, runner=subprocess.run) -> None:
    run(f"podpis {path.name}", template.replace("{file}", f'"{path}"'), runner, shell=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="build_release", description=__doc__.splitlines()[0])
    parser.add_argument("--allow-dirty", action="store_true",
                        help="buduj mimo niezatwierdzonych zmian (nazwa wyniku dostaje -dirty)")
    parser.add_argument("--device", action="store_true",
                        help="porównaj skan z paczki ze skanem deweloperskim na podłączonym telefonie")
    parser.add_argument("--iscc", type=Path, help=f"ISCC.exe (domyślnie {DEFAULT_ISCC})")
    return parser.parse_args(argv)


def build(args: argparse.Namespace, runner=subprocess.run) -> list[str]:
    version = read_version()
    dirty = check_clean(args.allow_dirty, runner)
    check_release_deps()
    iscc = find_iscc(args.iscc)
    sign_cmd = os.environ.get("ADMENOT_SIGN_CMD")
    stop_processes_in(BUNDLE, runner)
    py = sys.executable
    run("narzędzia (scrcpy, adb)", [py, ROOT / "scripts" / "fetch_tools.py"], runner)
    run("baza telefonów", [py, ROOT / "scripts" / "build_phone_db.py"], runner)
    run("UI", ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               ROOT / "scripts" / "build_ui.ps1"], runner)
    reference = None
    if args.device:
        reference = BUILD / "scan-reference.txt"
        reference.parent.mkdir(parents=True, exist_ok=True)
        text = run("skan referencyjny (.venv)", [py, "-m", "admenot.cli.main", "scan", "--apk", "--all"],
                   runner)
        reference.write_text(text, "utf-8")
    run("PyInstaller", [py, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", BUNDLE.parent,
                        "--workpath", BUILD / "pyinstaller", SPEC],
        runner, env={**os.environ, "ADMENOT_VERSION": version})
    if sign_cmd:
        for exe in ("AdMeNot.exe", "admenot-cli.exe"):
            sign(BUNDLE / exe, sign_cmd, runner)
    cli = BUNDLE / "admenot-cli.exe"
    run("selfcheck", [cli, "selfcheck"], runner)
    device_line = "selfcheck --device: pominięty (bez --device)"
    if reference is not None:
        try:
            run("selfcheck --device", [cli, "selfcheck", "--device", "--reference", reference], runner)
        finally:
            stop_processes_in(BUNDLE, runner)  # adb z paczki blokowałby pliki przy następnym buildzie
        device_line = "selfcheck --device: skan z paczki = skan deweloperski"
    notices, missing = third_party_notices.build(TOOLS, ROOT / "ui")
    (BUNDLE / "THIRD_PARTY_NOTICES.txt").write_text(notices, "utf-8")
    shutil.copyfile(ROOT / "LICENSE", BUNDLE / "LICENSE.txt")
    warnings = [f"brak licencji w metadanych: {name}" for name in missing]
    if not WEBVIEW2_SETUP.is_file():
        download(WEBVIEW2_URL, WEBVIEW2_SETUP)
    name = setup_name(version, dirty)
    command = [iscc, f"/DAppVersion={version}", f"/DWinVersion={windows_version(version)}",
               f"/DSourceDir={BUNDLE}", f"/DWebView2Setup={WEBVIEW2_SETUP}", f"/O{RELEASE}", f"/F{name}"]
    if sign_cmd:
        command += ["/DSign", f"/Sadmenot={sign_cmd.replace('{file}', '$f')}"]
    run("Inno Setup", [*command, ISS], runner)
    setup = RELEASE / f"{name}.exe"
    digest = write_sha256(setup)
    vt = None
    key = os.environ.get("VT_API_KEY")
    if key:
        print("==> VirusTotal", flush=True)
        try:
            vt = virustotal.scan(setup, key)
        except virustotal.VtError as exc:
            warnings.append(f"VirusTotal: {exc}")
    else:
        warnings.append("VirusTotal: pominięty (brak VT_API_KEY)")
    notes = RELEASE / f"{name.removesuffix('-setup')}-release-notes.md"
    notes.write_text(release_notes(version, setup, digest, bool(sign_cmd), vt), "utf-8")
    vt_line = f"VirusTotal: {vt.detections}/{vt.engines} — {vt.link}" if vt else "VirusTotal: nie sprawdzono"
    return [f"Instalator: {setup}", f"SHA-256: {digest}", f"Notatki: {notes}", device_line, vt_line,
            *(f"UWAGA: {w}" for w in warnings), "Podpisane" if sign_cmd else UNSIGNED]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # konsola Windows (cp1250)
        stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        summary = build(parse_args(argv))
    except BuildError as exc:
        print(f"BŁĄD {exc}", file=sys.stderr)
        return 1
    print("\n".join(["", *summary]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
