"""Pobranie, uruchomienie i sprzątanie instalatora aktualizacji (spec aktualizacji §6).

O autentyczności pliku świadczy SHA-256 i rozmiar z podpisanego manifestu, nie adres po
przekierowaniu. Plik ma końcówkę `.part`, dopóki nie przejdzie sprawdzenia.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from admenot import __version__
from admenot.engine.paths import updates_dir
from admenot.net import client
from admenot.net.update import Manifest, parse_version

SETUP_ARGS = ("/SILENT", "/NORESTART", "/UPDATE=1")
_NAME = re.compile(r"AdMeNot-(\d+\.\d+\.\d+)-setup\.exe(\.part)?")


class Corrupt(Exception):
    """Rozmiar albo SHA-256 pobranego pliku nie zgadza się z podpisanym manifestem."""


def setup_path(version: str, directory: Path | None = None) -> Path:
    return (directory or updates_dir()) / f"AdMeNot-{version}-setup.exe"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(manifest: Manifest, on_progress: Callable[[int, int | None], None] | None = None,
             cancelled: Callable[[], bool] = lambda: False,
             directory: Path | None = None) -> Path:
    final = setup_path(manifest.latest, directory)
    part = final.with_name(final.name + ".part")
    try:
        client.download(manifest.url, part, on_progress, cancelled, max_bytes=manifest.size)
    except client.TooLarge:
        raise Corrupt(manifest.latest) from None
    try:
        if part.stat().st_size != manifest.size or _sha256(part) != manifest.sha256:
            raise Corrupt(manifest.latest)
        os.replace(part, final)
    except BaseException:
        with contextlib.suppress(OSError):  # sprzątanie nie może zasłonić pierwotnego błędu
            part.unlink(missing_ok=True)
        raise
    return final


def launch(setup: Path, popen: Callable[..., object] = subprocess.Popen) -> None:
    """Instalator w osobnym procesie — program zaraz się zamyka, a Inno go podmienia."""
    flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))  # stałe istnieją tylko na Windows
    popen([str(setup), *SETUP_ARGS], creationflags=flags, close_fds=True)


def cleanup(version: str = __version__, directory: Path | None = None) -> None:
    """Usuwa `.part` i instalatory wersji ≤ bieżącej (spec §6.5); nowsze zostają."""
    directory = directory or updates_dir()
    try:
        files = list(directory.iterdir())
    except OSError:
        return
    current = parse_version(version)
    for path in files:
        match = _NAME.fullmatch(path.name)
        if match is None:
            continue
        if match.group(2) or parse_version(match.group(1)) <= current:
            try:
                path.unlink()
            except OSError:
                pass  # np. plik jeszcze otwarty przez antywirusa — spróbujemy przy następnym starcie
