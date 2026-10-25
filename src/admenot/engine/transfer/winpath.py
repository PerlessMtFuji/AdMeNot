"""Mapowanie ścieżek z telefonu na bezpieczne ścieżki lokalne.

Zawsze stosujemy reguły Windows (NTFS/exFAT), także poza Windows – kopia ma się dać
później bez niespodzianek skopiować na dowolny dysk.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

REMOTE_BASE = "/sdcard"
_REMOTE_ALIASES = (REMOTE_BASE, "/storage/emulated/0")
LONG_DIR = "_dlugie_sciezki"


def sanitize_component(name: str) -> str:
    """Jeden element ścieżki -> nazwa dozwolona w Windows."""
    s = _INVALID.sub("_", name)
    if s.endswith((" ", ".")):
        s = s.rstrip(" .") + "_"
    if not s:
        s = "_"
    if s.split(".")[0].upper() in _RESERVED:
        s = "_" + s
    return s


def remote_rel(path: str) -> str:
    """'/sdcard/DCIM/a.jpg' (lub '/storage/emulated/0/DCIM/a.jpg') -> 'DCIM/a.jpg'."""
    r = posixpath.normpath(path)
    for base in _REMOTE_ALIASES:
        if r.startswith(base + "/"):
            return r[len(base) + 1 :]
    return r.lstrip("/")


def _with_suffix(name: str, n: int) -> str:
    stem, ext = os.path.splitext(name)
    return f"{stem} ({n}){ext}"


class PathPlanner:
    """Wyznacza unikalne (bez względu na wielkość liter) ścieżki lokalne pod `files/`.

    `taken` mapuje zajęty klucz (casefold ścieżki względnej) na ścieżkę zdalną, która go
    zajęła – pozwala wznowić planowanie po przerwaniu kopii.
    """

    def __init__(self, max_path: int = 240, taken: dict[str, str] | None = None):
        self.max_path = max_path
        self.taken: dict[str, str] = dict(taken or {})
        self.renamed: dict[str, str] = {}

    def local_rel(self, remote: str, base_len: int) -> str:
        """Ścieżka względna ('/' jako separator) pod `files/`; `base_len` = długość katalogu `files/`."""
        parts = remote_rel(remote).split("/")
        orig_name = parts[-1]
        safe = [sanitize_component(p) for p in parts]
        rel = "/".join(safe)

        if base_len + 1 + len(rel) > self.max_path:
            h = hashlib.sha1(remote.encode("utf-8", "surrogatepass")).hexdigest()[:10]
            stem, ext = os.path.splitext(safe[-1])
            rel = f"{LONG_DIR}/{h}_{stem[:40]}{ext[:12]}"

        base_rel = rel
        n = 2
        while rel.casefold() in self.taken and self.taken[rel.casefold()] != remote:
            d, f = posixpath.split(base_rel)
            rel = posixpath.join(d, _with_suffix(f, n)) if d else _with_suffix(f, n)
            n += 1
        self.taken[rel.casefold()] = remote
        if posixpath.basename(rel) != orig_name:
            self.renamed[remote] = rel
        return rel
