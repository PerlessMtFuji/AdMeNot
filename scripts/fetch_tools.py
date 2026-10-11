"""Pobiera dołączone narzędzia do src/admenot/assets/tools/ (Plan 6b, spec §3.1).

    .venv\\Scripts\\python scripts\\fetch_tools.py

scrcpy dla Windows x64 razem z adb.exe. Program i scrcpy używają tego samego adb, więc
dwa serwery adb w różnych wersjach się nie ubijają. Wersja i SHA-256 są przypięte:
przy niezgodności sumy nic nie jest rozpakowywane. Katalog jest poza gitem, a instalator
(Plan 7) zabiera go razem z `assets/`.

Zweryfikowane archiwum zostaje w build/tools-cache. Przy każdym uruchomieniu (także w buildzie
wydania) każdy plik katalogu jest porównywany z archiwum o przypiętej sumie: sam plik VERSION
nie wystarcza — podmieniony adb.exe albo DLL w pamięci podręcznej trafiłby do instalatora
(audyt 2026-10-11, REL-02).
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "admenot" / "assets" / "tools" / "scrcpy"
VERSION = "4.1"
ARCHIVE = f"scrcpy-win64-v{VERSION}.zip"
URL = f"https://github.com/Genymobile/scrcpy/releases/download/v{VERSION}/{ARCHIVE}"
SHA256 = "5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db"
REQUIRED = ("scrcpy.exe", "scrcpy-server", "adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll",
            "LICENSE.txt")
CACHED_ARCHIVE = ROOT / "build" / "tools-cache" / ARCHIVE  # poza assets/: nie trafia do paczki


class FetchError(Exception):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=120) as response, dest.open("wb") as fh:
        shutil.copyfileobj(response, fh)


def _extract(archive: Path, into: Path) -> Path:
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts:
                raise FetchError(f"unsafe path in archive: {info.filename}")
        z.extractall(into)
    entries = list(into.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise FetchError("unexpected archive layout: expected one top-level directory")
    return entries[0]


def problems(target: Path, archive: Path, expected: str = SHA256,
             version: str = VERSION) -> list[str]:
    """Różnice między katalogiem narzędzi a archiwum o przypiętej sumie (pusta lista = zgodne)."""
    if not archive.is_file() or sha256(archive) != expected:
        return [f"brak zweryfikowanego archiwum {archive.name}"]
    version_file = target / "VERSION"
    if not version_file.is_file() or version_file.read_text("utf-8").strip() != version:
        return [f"inna wersja niż {version}"]
    found: list[str] = []
    expected_files: set[str] = {"VERSION"}
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            parts = PurePosixPath(info.filename).parts[1:]  # bez katalogu głównego archiwum
            if not parts:
                continue
            relative = "/".join(parts)
            expected_files.add(relative)
            path = target.joinpath(*parts)
            if not path.is_file():
                found.append(f"brak {relative}")
            elif sha256(path) != hashlib.sha256(z.read(info)).hexdigest():
                found.append(f"zmieniony {relative}")
    extra = sorted(p.relative_to(target).as_posix() for p in target.rglob("*")
                   if p.is_file() and p.relative_to(target).as_posix() not in expected_files)
    found += [f"obcy plik {name}" for name in extra]
    return found


def install(archive: Path, target: Path, expected: str = SHA256, version: str = VERSION) -> Path:
    actual = sha256(archive)
    if actual != expected:
        raise FetchError(f"SHA-256 mismatch: {actual} != {expected}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        root = _extract(archive, Path(tmp))
        missing = [name for name in REQUIRED if not (root / name).is_file()]
        if missing:
            raise FetchError(f"missing in archive: {', '.join(missing)}")
        (root / "VERSION").write_text(f"{version}\n", "utf-8")
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(root), str(target))
    return target


def main() -> int:
    found = problems(TARGET, CACHED_ARCHIVE)
    if not found:
        print(f"scrcpy {VERSION} już jest (pliki zgodne z archiwum): {TARGET}")
        return 0
    print("Katalog narzędzi do odtworzenia: " + "; ".join(found[:5]))
    try:
        if not CACHED_ARCHIVE.is_file() or sha256(CACHED_ARCHIVE) != SHA256:
            CACHED_ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
            part = CACHED_ARCHIVE.with_name(ARCHIVE + ".part")
            print(f"Pobieranie {URL}")
            download(URL, part)
            part.replace(CACHED_ARCHIVE)
        install(CACHED_ARCHIVE, TARGET)
        if found := problems(TARGET, CACHED_ARCHIVE):
            raise FetchError("po instalacji: " + "; ".join(found[:5]))
    except FetchError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"scrcpy {VERSION} → {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
