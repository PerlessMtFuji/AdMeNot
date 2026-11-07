"""„Miejsca” eksploratora: znane foldery telefonu (aparat, zrzuty, pobrane…) i liczenie plików w tle."""

from __future__ import annotations

import stat
from dataclasses import dataclass

from admenot.engine.adb.transport import AdbError
from admenot.engine.explorer.guard import ExplorerAdb
from admenot.engine.explorer.listing import LIST_TIMEOUT, ListError, list_error
from admenot.engine.transfer.guard import STAT_TAIL, q

__all__ = ["Place", "count_place", "find_places", "scan_place"]

_ROOT = "/sdcard"
_CUT_SHORT = "Argument list too long"
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
    try:
        out = adb.shell(cmd)
    except AdbError as exc:
        raise list_error(exc) from exc
    for line in out.split("\n"):
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


def _visible(root: str, path: str) -> bool:
    """Plik poza ukrytymi folderami i sam nieukryty (żaden segment pod korzeniem miejsca nie zaczyna się od `.`)."""
    return not any(seg.startswith(".") for seg in path[len(root):].split("/"))


def _refuse_if_denied(found: int, out: str) -> None:
    """Pusto i odmowa: miejsce bez dostępu, a nie puste (ta sama odmowa dalej w drzewie niczego nie kasuje)."""
    if not found and "permission denied" in out.lower():
        raise ListError("denied")


def count_place(adb: ExplorerAdb, place: Place) -> int:
    """Liczba widocznych plików miejsca, rekurencyjnie, jednym `find` (powolne — wołać w tle). Folder bez dostępu
    po drodze pomija tylko siebie (`STAT_TAIL`: błędy trafiają na stdout, a reszta wyniku zostaje)."""
    root = place.path.rstrip("/") + "/"
    try:
        out = adb.shell(f"find {q(root)} -type f{STAT_TAIL}", timeout=LIST_TIMEOUT)
    except AdbError as exc:
        raise list_error(exc) from exc
    files = [line for line in out.split("\n") if line.startswith(root)]
    _refuse_if_denied(len(files), out)
    return sum(_visible(root, line) for line in files)


def scan_place(adb: ExplorerAdb, place: Place) -> tuple[int, int]:
    """(liczba widocznych plików, bajty wszystkich plików) miejsca jednym przejściem `find`: ukryte pliki nie wchodzą
    do liczby, ale zajmują miejsce. Powolne — wołać w tle.

    Toybox przy dużym drzewie potrafi przerwać `-exec … +` („Argument list too long”) i zostawić urwany wynik:
    wtedy liczba idzie z `count_place`, a rozmiar jest dolną granicą (reszta wchodzi do „inne”)."""
    root = place.path.rstrip("/") + "/"
    try:
        out = adb.shell(f"find {q(root)} -type f -exec stat -c '%s|%n' {{}} +{STAT_TAIL}", timeout=LIST_TIMEOUT)
    except AdbError as exc:
        raise list_error(exc) from exc
    files = count = size = 0
    for line in out.split("\n"):
        bytes_, _, path = line.partition("|")
        if not bytes_.isdigit() or not path.startswith(root):  # błąd `find` albo ciąg dalszy nazwy z nową linią
            continue
        files += 1
        size += int(bytes_)
        count += _visible(root, path)
    _refuse_if_denied(files, out)
    return (count_place(adb, place) if _CUT_SHORT in out else count), size
