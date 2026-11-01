"""Inwentarz starego telefonu: co da się skopiować (liczby, pliki, aplikacje) — ekran wyboru kopii.

Port `scan_device` ze skryptu adb-backup. Wszystko tylko do odczytu (`find`/`ls`/`df`/`content query`).
Ograniczenie: `adb shell` zwraca błąd przy niezerowym kodzie wyjścia `find` (np. brak dostępu do
jednego katalogu), a wtedy tracimy cały wynik — dlatego po błędzie skanujemy korzenie osobno,
a korzeń, który mimo to zawodzi, liczymy do „nieczytelnych”.
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.scoring import AppResult
from admenot.engine.session import ScanReport

from .exports import EXPORT_KINDS, ExportFile, find_exports
from .guard import q
from .mms import mms_stats
from .telephony import _CONNECTION_KINDS, ContentQueryError, Stopped, count_rows
from .winpath import REMOTE_BASE, remote_rel

FILE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "media": ("DCIM", "Pictures", "Movies", "Screenshots"),
    "downloads": ("Download", "Documents"),
    "whatsapp": (
        "Android/media/com.whatsapp/WhatsApp",
        "WhatsApp",
        "Android/media/com.whatsapp.w4b/WhatsApp Business",
        "WhatsApp Business",
    ),
}

VIDEO_EXT = frozenset({".mp4", ".mov", ".3gp", ".3g2", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".mts",
                       ".m2ts", ".wmv", ".flv"})


def upload_group(category: str, remote: str) -> str:
    """Kategoria kopii → grupa wgrywania; `media` dzielone po rozszerzeniu (nieznane → zdjęcia)."""
    if category == "media":
        return "videos" if posixpath.splitext(remote)[1].lower() in VIDEO_EXT else "photos"
    return category


JUNK_DIRS = (".thumbnails", ".Thumbnails", ".Trash", ".trash", ".Statuses", ".cache")
JUNK_PREFIXES = (".trashed-", ".pending-")
EXCLUDED_TOP = {"Android"}

_WA_DB_DIRS = (
    f"{REMOTE_BASE}/Android/media/com.whatsapp/WhatsApp/Databases",
    f"{REMOTE_BASE}/WhatsApp/Databases",
)
# Błąd połączenia albo przekroczenie czasu przechodzi wyżej (kopia czeka na telefon / pokazuje błąd).
_PROPAGATE_KINDS = _CONNECTION_KINDS | {"timeout"}


@dataclass(frozen=True)
class RemoteFile:
    remote: str
    size: int
    mtime: int
    category: str  # klucz z FILE_CATEGORIES albo "other:<folder>"


@dataclass(frozen=True)
class AppEntry:
    package: str
    label: str
    version_code: int | None
    verdict: str
    default_on: bool


@dataclass
class Inventory:
    contacts: int | None
    sms: int | None
    mms: int | None
    mms_bytes: int
    calls: int | None
    files: list[RemoteFile]
    others: dict[str, tuple[int, int]]
    apps: list[AppEntry]
    skipped_apps: list[AppEntry]
    whatsapp_backup: datetime | None
    storage: tuple[int, int] | None  # (zajęte, razem) w bajtach
    unreadable: int  # nieczytelne nazwy plików + całe korzenie, których nie udało się przeskanować
    denied: frozenset[str] = frozenset()  # kategorie (contacts/sms/calls), które telefon odmówił oddać
    # pliki eksportu (najnowszy pierwszy) — tylko dla kategorii, których provider nie oddał
    exports: dict[str, list[ExportFile]] = field(default_factory=dict)


def _check(should_stop: Callable[[], bool]) -> None:
    if should_stop():
        raise Stopped()


def _ls(adb: AdbTransport, path: str, required: bool = False) -> set[str] | None:
    """Nazwy w katalogu albo None, gdy katalogu nie ma / nie da się go odczytać (chyba że `required`)."""
    try:
        out = adb.shell(f"ls -1 {q(path)}")
    except AdbError as exc:
        if required or exc.kind in _PROPAGATE_KINDS:
            raise
        return None
    return {line for line in out.split("\n") if line}


def _find(adb: AdbTransport, roots: list[str]) -> str:
    parts = ["find", "-H", *(q(r) for r in roots)]
    for name in JUNK_DIRS:
        parts += ["-name", q(name), "-prune", "-o"]
    parts += ["-type", "f", "-exec", "stat", "-c", q("%s|%Y|%n"), "{}", "+"]
    return adb.shell(" ".join(parts), timeout=600)


def scan_files(
    adb: AdbTransport, should_stop: Callable[[], bool]
) -> tuple[list[RemoteFile], dict[str, tuple[int, int]], int]:
    """Pliki do skopiowania, podsumowanie folderów spoza znanych kategorii i liczba nieczytelnych.

    `others`: folder -> (pliki, bajty); klucz "" = luźne pliki w głównym folderze telefonu.
    Trzeci element (`unreadable`) to nieczytelne nazwy plus całe korzenie, które zawiodły przy
    skanowaniu osobno (po błędzie wspólnego `find`). Błąd odczytu samego /sdcard przechodzi wyżej.
    """
    top = _ls(adb, REMOTE_BASE, required=True) or set()
    # korzeń -> kategoria; korzenie znanych kategorii istnieją tylko, jeśli widać je w katalogu nadrzędnym
    roots: dict[str, str] = {}
    listings: dict[str, set[str] | None] = {REMOTE_BASE: top}
    for cat, rels in FILE_CATEGORIES.items():
        for rel in rels:
            parent, _, name = f"{REMOTE_BASE}/{rel}".rpartition("/")
            if parent not in listings:
                listings[parent] = _ls(adb, parent)
            if name in (listings[parent] or ()):
                roots[f"{parent}/{name}"] = cat
    known_tops = {rel.split("/")[0] for rels in FILE_CATEGORIES.values() for rel in rels}
    # Luźne pliki w głównym folderze (nie katalogi) trafiają do wpisu „other:” (pusta nazwa folderu).
    loose_out = adb.shell(f"find -H {q(REMOTE_BASE)} -maxdepth 1 -type f "
                          f"-exec stat -c {q('%s|%Y|%n')} {{}} +", timeout=120)
    loose_names = {ln.split("|", 2)[2].rsplit("/", 1)[-1] for ln in loose_out.split("\n")
                   if ln.count("|") >= 2}
    for name in sorted(top - loose_names):
        if name in known_tops or name in EXCLUDED_TOP or name.startswith("."):
            continue
        roots[f"{REMOTE_BASE}/{name}"] = f"other:{name}"
    _check(should_stop)
    if not roots and not loose_names:
        return [], {}, 0

    # Do find idą tylko korzenie niezagnieżdżone w innych.
    outer = [r for r in roots if not any(o != r and r.startswith(o + "/") for o in roots)]
    unreadable = 0
    outputs = [loose_out]
    try:
        outputs.append(_find(adb, outer) if outer else "")
    except AdbError as exc:
        if exc.kind in _PROPAGATE_KINDS:
            raise
        outputs = [loose_out]
        for root in outer:
            _check(should_stop)
            try:
                outputs.append(_find(adb, [root]))
            except AdbError as exc2:
                if exc2.kind in _PROPAGATE_KINDS:
                    raise
                unreadable += 1
    _check(should_stop)

    by_len = sorted(roots, key=len, reverse=True)
    files: list[RemoteFile] = []
    others: dict[str, tuple[int, int]] = {}
    seen: set[str] = set()
    for line in "\n".join(outputs).split("\n"):
        if not line:
            continue
        bits = line.split("|", 2)
        if len(bits) != 3 or not bits[0].isdigit() or not bits[1].lstrip("-").isdigit():
            unreadable += 1
            continue
        size, mtime, path = int(bits[0]), int(bits[1]), bits[2].replace("//", "/")
        if path in seen:
            continue
        seen.add(path)
        if "�" in path:
            unreadable += 1
            continue
        if remote_rel(path).rsplit("/", 1)[-1].startswith(JUNK_PREFIXES):
            continue
        root = next((r for r in by_len if path.startswith(r + "/")), None)
        if root is None:
            if path.rsplit("/", 1)[0] != REMOTE_BASE or path.rsplit("/", 1)[1].startswith("."):
                continue
            category = "other:"
        else:
            category = roots[root]
        files.append(RemoteFile(path, size, mtime, category))
        if category.startswith("other:"):
            n, total = others.get(category[6:], (0, 0))
            others[category[6:]] = (n + 1, total + size)
    return files, others, unreadable


def whatsapp_backup_time(adb: AdbTransport) -> datetime | None:
    """Czas najnowszej lokalnej kopii czatów WhatsApp (`msgstore*.db.crypt*`)."""
    newest: int | None = None
    for directory in _WA_DB_DIRS:
        cmd = (f"find -H {q(directory)} -name {q('msgstore*.db.crypt*')} -type f "
               f"-exec stat -c {q('%s|%Y|%n')} {{}} +")
        try:
            out = adb.shell(cmd)
        except AdbError as exc:
            if exc.kind in _PROPAGATE_KINDS:
                raise
            continue
        for line in out.split("\n"):
            bits = line.split("|", 2)
            if len(bits) == 3 and bits[1].lstrip("-").isdigit():
                m = int(bits[1])
                newest = m if newest is None else max(newest, m)
    return datetime.fromtimestamp(newest) if newest is not None else None


def classify_apps(report: ScanReport) -> tuple[list[AppEntry], list[AppEntry]]:
    """(do kopii, pominięte): tylko aplikacje użytkownika; złośliwe pomijamy, podejrzane domyślnie wyłączone."""
    copy: list[AppEntry] = []
    skipped: list[AppEntry] = []
    for r in report.results:
        f = r.facts
        if f.is_system:
            continue
        entry = _entry(r)
        if r.verdict == "malicious":
            skipped.append(entry)
        else:
            copy.append(entry)
    return copy, skipped


def _entry(r: AppResult) -> AppEntry:
    f = r.facts
    return AppEntry(f.package, f.label or f.package, f.version_code, r.verdict,
                    default_on=r.verdict != "suspicious")


def _count(fn: Callable[[], int]) -> tuple[int | None, bool]:
    """(liczba, odmowa): `None` gdy provider nie odpowiada; `odmowa` tylko przy braku uprawnień."""
    try:
        return fn(), False
    except ContentQueryError as exc:
        return None, exc.denied


def _storage(adb: AdbTransport) -> tuple[int, int] | None:
    try:
        out = adb.shell(f"df -k {q(REMOTE_BASE + '/')}")
        last = [ln for ln in out.splitlines() if ln.strip()][-1].split()
        return int(last[2]) * 1024, int(last[1]) * 1024
    except AdbError as exc:
        if exc.kind in _PROPAGATE_KINDS:
            raise
    except (IndexError, ValueError):
        pass
    return None


def build_inventory(adb: AdbTransport, report: ScanReport, should_stop: Callable[[], bool]) -> Inventory:
    apps, skipped = classify_apps(report)
    return _build(adb, apps, skipped, should_stop)


def refresh_inventory(
    adb: AdbTransport, previous: Inventory, should_stop: Callable[[], bool]
) -> Inventory:
    """Ponowny odczyt telefonu (po nadaniu uprawnień / skopiowaniu plików eksportu): bez raportu
    skanu — aplikacje i pominięte bierzemy z poprzedniego inwentarza."""
    return _build(adb, previous.apps, previous.skipped_apps, should_stop)


def _build(
    adb: AdbTransport, apps: list[AppEntry], skipped: list[AppEntry], should_stop: Callable[[], bool]
) -> Inventory:
    counts: dict[str, int | None] = {}
    denied: set[str] = set()
    for key, uri in (("contacts", "content://com.android.contacts/contacts"),
                     ("sms", "content://sms"), ("calls", "content://call_log/calls")):
        _check(should_stop)
        counts[key], refused = _count(lambda uri=uri: count_rows(adb, uri))
        if refused:
            denied.add(key)
    _check(should_stop)
    mms: int | None = None
    mms_bytes = 0
    try:
        mms, mms_bytes = mms_stats(adb)
    except ContentQueryError:
        pass
    files, others, unreadable = scan_files(adb, should_stop)
    _check(should_stop)
    wa = whatsapp_backup_time(adb)
    # Pliki eksportu proponujemy tylko dla kategorii, której provider nie oddał (odmowa albo inny błąd).
    missing = {k for k in EXPORT_KINDS if counts[k] is None}
    exports = find_exports(adb, files, missing, should_stop) if missing else {}
    return Inventory(counts["contacts"], counts["sms"], mms, mms_bytes, counts["calls"], files, others,
                     apps, skipped, wa, _storage(adb), unreadable, frozenset(denied), exports)
