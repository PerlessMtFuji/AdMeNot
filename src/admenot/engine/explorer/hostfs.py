"""Dysk komputera dla eksploratora: wolne miejsce, system plików (FAT32?), zapis, długie ścieżki Windows."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

__all__ = ["MAX_LONG_PATH", "filesystem", "free_bytes", "long_path", "writable"]

MAX_LONG_PATH = 32767  # limit ścieżki z prefiksem `\\?\`
_SHORT_LIMIT = 240  # od tej długości katalogi/pliki wymagają `\\?\` (limity 248/260)


def _existing(path: Path) -> Path:
    """Najbliższy istniejący przodek (albo sama ścieżka)."""
    p = Path(os.path.abspath(path))
    while not p.exists() and p.parent != p:
        p = p.parent
    return p


def long_path(path: str | Path) -> str:
    """Ścieżka gotowa dla Win32: długie (od 240 znaków) dostają prefiks `\\\\?\\`."""
    s = os.path.abspath(str(path)) if not str(path).startswith("\\\\?\\") else str(path)
    if os.name != "nt" or s.startswith("\\\\?\\") or len(s) < _SHORT_LIMIT:
        return s
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def free_bytes(path: Path) -> int:
    """Wolne miejsce na dysku, na którym leży (lub powstanie) `path`."""
    return shutil.disk_usage(_existing(path)).free


def filesystem(path: Path) -> str:
    """Nazwa systemu plików woluminu `path` (`"NTFS"`, `"FAT32"`, `"exFAT"`); pusta, gdy nieznana."""
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    target = str(_existing(path))
    root = ctypes.create_unicode_buffer(1024)
    if not kernel32.GetVolumePathNameW(wintypes.LPCWSTR(target), root, len(root)):
        return ""
    fs = ctypes.create_unicode_buffer(64)
    ok = kernel32.GetVolumeInformationW(wintypes.LPCWSTR(root.value), None, 0, None, None, None, fs, len(fs))
    return fs.value if ok else ""


def writable(path: Path) -> bool:
    """Czy da się utworzyć plik w `path` (lub w jego najbliższym istniejącym przodku). Sonda znika od razu."""
    folder = _existing(path)
    if not folder.is_dir():
        return False
    try:
        with tempfile.TemporaryFile(dir=folder):
            return True
    except OSError:
        return False
