"""Pobiera dołączone narzędzia do src/demalware/assets/tools/ (Plan 6b, spec §3.1).

    .venv\\Scripts\\python scripts\\fetch_tools.py

scrcpy dla Windows x64 razem z adb.exe. Program i scrcpy używają tego samego adb, więc
dwa serwery adb w różnych wersjach się nie ubijają. Wersja i SHA-256 są przypięte:
przy niezgodności sumy nic nie jest rozpakowywane. Katalog jest poza gitem, a instalator
(Plan 7) zabiera go razem z `assets/`.
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
TARGET = ROOT / "src" / "demalware" / "assets" / "tools" / "scrcpy"
VERSION = "4.1"
ARCHIVE = f"scrcpy-win64-v{VERSION}.zip"
URL = f"https://github.com/Genymobile/scrcpy/releases/download/v{VERSION}/{ARCHIVE}"
SHA256 = "5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db"
REQUIRED = ("scrcpy.exe", "scrcpy-server", "adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll",
            "LICENSE.txt")


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
    version_file = TARGET / "VERSION"
    if version_file.is_file() and version_file.read_text("utf-8").strip() == VERSION:
        print(f"scrcpy {VERSION} już jest: {TARGET}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / ARCHIVE
        print(f"Pobieranie {URL}")
        download(URL, archive)
        try:
            install(archive, TARGET)
        except FetchError as exc:
            print(exc, file=sys.stderr)
            return 1
    print(f"scrcpy {VERSION} → {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
