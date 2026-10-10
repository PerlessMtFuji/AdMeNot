"""Buduje wydanie: dist/release/AdMeNot-<wersja>-setup.exe (spec: 2026-10-04-release-build-design.md).

    .venv\\Scripts\\python scripts\\build_release.py [--allow-dirty] [--device] [--iscc ŚCIEŻKA]

Kroki: warunki wstępne → bramki jakości → dane (narzędzia, baza telefonów, UI) → PyInstaller →
selfcheck → wykaz licencji → Inno Setup → SHA-256 → VirusTotal (gdy VT_API_KEY) → notatki do wydania.
Podpis: ADMENOT_SIGN_CMD z `{file}` w miejscu ścieżki; bez niej wydanie jest niepodpisane.

Bramki (audyt 2026-10-11, REL-01, REL-03): środowisko zgodne z packaging/requirements-release.lock,
pełne testy Python/UI/Workera, Ruff, kontrole typów i skan historii pod kątem sekretów. Wynik
każdej bramki trafia do notatek obok SHA-256 instalatora. `--skip-gates` tylko z `--allow-dirty`
(wynik -dirty to nie wydanie).
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
import release_env
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
WEBVIEW2_PUBLISHER = "O=Microsoft Corporation"
LICENSE_DECISIONS = ROOT / "packaging" / "license-decisions.txt"
PHONE_SOURCE = Path(r"F:\Szklodo")  # prywatny katalog autora (scripts/build_phone_db.py)
PHONE_DB = ROOT / "src" / "admenot" / "assets" / "phones.db"
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
                  vt: virustotal.VtResult | None, passed: Sequence[str] | None = None,
                  extra: Sequence[str] = ()) -> str:
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
    if passed is None:
        lines.append("- Bramki jakości: POMINIĘTE (--skip-gates) — to nie jest wydanie")
    else:
        lines.append("- Bramki jakości: " + "; ".join(passed))
    lines += [f"- {line}" for line in extra]
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


def verify_authenticode(path: Path, publisher: str, runner=subprocess.run) -> str:
    """Ważny podpis Authenticode wskazanego wydawcy; zwraca podmiot certyfikatu (REL-02)."""
    quoted = str(path).replace("'", "''")
    script = (f"$s = Get-AuthenticodeSignature -LiteralPath '{quoted}'; "
              "Write-Output ($s.Status.ToString() + '|' + $s.SignerCertificate.Subject)")
    out = run(f"podpis {path.name}", ["powershell", "-NoProfile", "-Command", script], runner).strip()
    status, _, subject = out.partition("|")
    if status != "Valid" or publisher not in subject:
        raise BuildError(f"podpis {path.name}", str(path),
                         f"Oczekiwano ważnego podpisu „{publisher}”, jest: {out or 'brak'}")
    return subject


def webview2_bootstrapper(runner=subprocess.run) -> str:
    """Bootstrapper WebView2 z ważnym podpisem Microsoftu (z pamięci podręcznej albo pobrany
    na nowo); zwraca linię do notatek wydania z jego SHA-256."""
    for attempt in range(2):
        if not WEBVIEW2_SETUP.is_file():
            download(WEBVIEW2_URL, WEBVIEW2_SETUP)
        try:
            subject = verify_authenticode(WEBVIEW2_SETUP, WEBVIEW2_PUBLISHER, runner)
        except BuildError:
            WEBVIEW2_SETUP.unlink(missing_ok=True)  # podmieniony albo uszkodzony plik z cache
            if attempt:
                raise
            continue
        digest = hashlib.sha256(WEBVIEW2_SETUP.read_bytes()).hexdigest()
        return f"WebView2 bootstrapper: SHA-256 {digest}, podpis: {subject}"
    raise AssertionError("unreachable")


def license_decisions(path: Path | None = None) -> dict[str, str]:
    """Rozstrzygnięcia autora dla składników bez jasnej licencji: „nazwa | decyzja” w linii."""
    path = path or LICENSE_DECISIONS
    if not path.is_file():
        return {}
    decisions = {}
    for line in path.read_text("utf-8").splitlines():
        name, sep, decision = line.partition("|")
        if sep and not line.lstrip().startswith("#") and decision.strip():
            decisions[name.strip()] = decision.strip()
    return decisions


def check_licenses(missing: Sequence[str], allow_dirty: bool) -> list[str]:
    """Składnik bez licencji albo bez podstawy redystrybucji blokuje wydanie, dopóki autor nie
    zapisze decyzji w packaging/license-decisions.txt (audyt 2026-10-11, REL-04)."""
    decisions = license_decisions()
    open_items = [name for name in missing if name not in decisions]
    if open_items and not allow_dirty:
        raise BuildError("licencje", "THIRD_PARTY_NOTICES",
                         "Bez rozstrzygnięcia w packaging/license-decisions.txt:\n" + "\n".join(open_items))
    return [f"licencja: {name} — {decisions[name]}" for name in missing if name in decisions] + [
        f"brak licencji/podstawy (nierozstrzygnięte): {name}" for name in open_items]


def gates(py: str, runner=subprocess.run) -> list[str]:
    """Bramki jakości przed budową; pierwszy błąd zatrzymuje wydanie (REL-01, REL-03)."""
    problems = release_env.check()
    if problems:
        raise BuildError("środowisko wydania", "scripts/release_env.py",
                         "Zainstalowane pakiety różnią się od packaging/requirements-release.lock:\n"
                         + "\n".join(problems))
    passed = ["środowisko = requirements-release.lock"]
    steps: list[tuple[str, list[object], Path]] = [
        ("testy Python", [py, "-m", "pytest", "-q", "-p", "no:cacheprovider"], ROOT),
        ("Ruff", [py, "-m", "ruff", "check", "."], ROOT),
        ("skan historii (sekrety)", [py, ROOT / "scripts" / "scan_history.py"], ROOT),
        ("UI: typy", ["npm.cmd", "run", "check"], ROOT / "ui"),
        ("UI: testy", ["npm.cmd", "run", "test"], ROOT / "ui"),
        ("Worker: typy", ["npm.cmd", "run", "check"], ROOT / "server"),
        ("Worker: testy", ["npm.cmd", "run", "test"], ROOT / "server"),
    ]
    env = {**os.environ, "WRANGLER_SEND_METRICS": "false"}
    for step, command, cwd in steps:
        run(step, command, runner, cwd=cwd, env=env)
        passed.append(step)
    return passed


def sign(path: Path, template: str, runner=subprocess.run) -> None:
    run(f"podpis {path.name}", template.replace("{file}", f'"{path}"'), runner, shell=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="build_release", description=__doc__.splitlines()[0])
    parser.add_argument("--allow-dirty", action="store_true",
                        help="buduj mimo niezatwierdzonych zmian (nazwa wyniku dostaje -dirty)")
    parser.add_argument("--device", action="store_true",
                        help="porównaj skan z paczki ze skanem deweloperskim na podłączonym telefonie")
    parser.add_argument("--iscc", type=Path, help=f"ISCC.exe (domyślnie {DEFAULT_ISCC})")
    parser.add_argument("--skip-gates", action="store_true",
                        help="bez testów i kontroli środowiska (tylko z --allow-dirty)")
    args = parser.parse_args(argv)
    if args.skip_gates and not args.allow_dirty:
        parser.error("--skip-gates wymaga --allow-dirty: wydanie zawsze przechodzi bramki")
    return args


def build(args: argparse.Namespace, runner=subprocess.run) -> list[str]:
    version = read_version()
    dirty = check_clean(args.allow_dirty, runner)
    check_release_deps()
    iscc = find_iscc(args.iscc)
    sign_cmd = os.environ.get("ADMENOT_SIGN_CMD")
    stop_processes_in(BUNDLE, runner)
    py = sys.executable
    passed = None if args.skip_gates else gates(py, runner)
    run("narzędzia (scrcpy, adb)", [py, ROOT / "scripts" / "fetch_tools.py"], runner)
    early: list[str] = []
    if PHONE_SOURCE.is_dir():
        run("baza telefonów", [py, ROOT / "scripts" / "build_phone_db.py", "--source", PHONE_SOURCE],
            runner)
    elif PHONE_DB.is_file():
        # Build bez prywatnego katalogu: zostaje zbudowana wcześniej baza; jej skrót jest w
        # THIRD_PARTY_NOTICES, więc wiadomo, która wersja trafiła do paczki (REL-04).
        early.append(f"baza telefonów: użyta istniejąca {PHONE_DB.name} (brak {PHONE_SOURCE})")
    else:
        raise BuildError("baza telefonów", str(PHONE_SOURCE),
                         "Brak katalogu źródłowego i zbudowanej bazy telefonów.")
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
    warnings = early + check_licenses(missing, args.allow_dirty)
    webview2 = webview2_bootstrapper(runner)
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
    components = RELEASE / f"{name.removesuffix('-setup')}-components.txt"
    components.write_text(release_env.inventory(), "utf-8")
    notes.write_text(release_notes(version, setup, digest, bool(sign_cmd), vt, passed,
                                   [webview2, f"Komponenty Python: `{components.name}`"]), "utf-8")
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
