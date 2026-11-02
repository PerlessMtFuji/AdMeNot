"""„Miejsca” eksploratora: znane foldery telefonu (aparat, zrzuty, pobrane…) i liczenie plików w tle."""

from __future__ import annotations

import stat
from dataclasses import dataclass

from admenot.engine.explorer.guard import ExplorerAdb
from admenot.engine.explorer.listing import ListError, list_dir
from admenot.engine.transfer.guard import STAT_TAIL, q

__all__ = ["Place", "count_place", "find_places"]

_ROOT = "/sdcard"
# (klucz, ikona, kandydaci — pierwszy istniejący wygrywa)
_PLACES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("camera", "camera", ("/sdcard/DCIM/Camera",)),
    ("screenshots", "screenshot", ("/sdcard/Pictures/Screenshots", "/sdcard/DCIM/Screenshots")),
    ("downloads", "download", ("/sdcard/Download",)),
    ("whatsapp", "chat", ("/sdcard/Android/media/com.whatsapp/WhatsApp/Media", "/sdcard/WhatsApp/Media")),
    ("movies", "film", ("/sdcard/Movies",)),
    ("music", "music", ("/sdcard/Music",)),
    ("documents", "document", ("/sdcard/Documents",)),
)


@dataclass(frozen=True)
class Place:
    key: str
    path: str
    count: int | None
    icon: str


def _existing_dirs(adb: ExplorerAdb, paths: list[str]) -> set[str]:
    """Które z `paths` są folderami: jedno `stat` (błędy brakujących jako linie, kod 0)."""
    cmd = "stat -c '%f|%s|%Y|%n' " + " ".join(q(p + "/") for p in paths) + STAT_TAIL
    found: set[str] = set()
    for line in adb.shell(cmd).split("\n"):
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        try:
            is_dir = stat.S_ISDIR(int(parts[0], 16))
        except ValueError:
            continue
        if is_dir and parts[3].rstrip("/") in paths:
            found.add(parts[3].rstrip("/"))
    return found


def find_places(adb: ExplorerAdb) -> list[Place]:
    """Istniejące miejsca (bez liczby plików, jedno szybkie wywołanie); „Wszystkie pliki” zawsze."""
    existing = _existing_dirs(adb, [p for _, _, paths in _PLACES for p in paths])
    places = [Place(key, path, None, icon)
              for key, icon, paths in _PLACES
              if (path := next((p for p in paths if p in existing), None)) is not None]
    return [*places, Place("all", _ROOT, None, "phone")]


def count_place(adb: ExplorerAdb, place: Place) -> int:
    """Liczba widocznych plików w miejscu, rekurencyjnie (powolne — wołać w tle).

    Idzie po folderach tym samym zapytaniem co `list_dir`; foldery bez dostępu są pomijane."""
    total = 0
    pending = [place.path]
    while pending:
        try:
            result = list_dir(adb, pending.pop())
        except ListError as exc:
            if exc.kind == "offline":
                raise
            continue
        for entry in result.entries:
            if entry.kind == "dir":
                pending.append(entry.path)
            else:
                total += 1
    return total
