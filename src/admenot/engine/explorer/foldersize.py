"""Liczba plików i łączny rozmiar folderu (z podfolderami) dla kafelków eksploratora.

Dwa polecenia z allowlisty strażnika: `find '<folder>/' -type f` (jedna ścieżka na linię — liczba plików) i
`du -sb '<folder>/'` (rzeczywiste bajty, jak przy kopiowaniu). Ukryte pliki się liczą: kopia folderu też je bierze.
Toybox bez `du -b` (starsze Androidy) — bloki 1 KiB z `du -sk` i wynik oznaczony jako przybliżony. Podfolder bez
dostępu nie przerywa liczenia, tylko oznacza wynik jako niepełny."""

from __future__ import annotations

import re
from dataclasses import dataclass

from admenot.engine.explorer.guard import ExplorerAdb
from admenot.engine.transfer.guard import STAT_TAIL, q

__all__ = ["FOLDER_TIMEOUT", "FolderStats", "folder_stats"]

FOLDER_TIMEOUT = 60.0  # s na jedno polecenie; dłużej — folder bez liczb, reszta liczy się dalej
_DU = re.compile(r"(\d+)\s")


@dataclass(frozen=True)
class FolderStats:
    files: int
    bytes: int
    partial: bool  # część podfolderów bez dostępu — liczby są dolną granicą
    approx: bool  # rozmiar z bloków dysku (toybox bez `du -b`)

    def view(self) -> dict[str, int | bool]:
        return {"files": self.files, "bytes": self.bytes, "partial": self.partial, "approx": self.approx}


def folder_stats(adb: ExplorerAdb, path: str) -> FolderStats:
    """Rzuca `AdbError` (odłączenie, limit czasu); odmowa dostępu to `partial`, nie błąd."""
    root = path.rstrip("/") + "/"
    out = adb.shell(f"find {q(root)} -type f{STAT_TAIL}", timeout=FOLDER_TIMEOUT)
    files, partial = 0, False
    for line in out.split("\n"):
        if line.startswith(root):
            files += 1
        elif line.startswith("find:"):
            partial = True
    approx = False
    size, denied = _du(adb, root, "-sb")
    if size is None:  # toybox bez `-b` odpowiada błędem opcji
        approx = True
        size, denied = _du(adb, root, "-sk")
        size = None if size is None else size * 1024
    if files == 0 and not (partial or denied):
        size = 0  # `du -b` liczy też wpisy samych folderów (3–7 KB): pusty folder ma pokazać 0 B
    return FolderStats(files, size or 0, partial or denied, approx)


def _du(adb: ExplorerAdb, root: str, flag: str) -> tuple[int | None, bool]:
    """(suma dla `root` albo None, czy były błędy dostępu)."""
    out = adb.shell(f"du {flag} {q(root)}{STAT_TAIL}", timeout=FOLDER_TIMEOUT)
    size: int | None = None
    denied = False
    for line in out.splitlines():
        m = _DU.match(line)
        if m and line.rstrip("/").endswith(root.rstrip("/")):
            size = int(m.group(1))
        elif "denied" in line.lower():
            denied = True
    return size, denied
