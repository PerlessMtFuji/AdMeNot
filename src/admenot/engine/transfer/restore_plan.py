"""Plan wgrywania kopii na nowy telefon: co, dokąd i czy się zmieści (spec Etapu 2 §4.2, §4.3, §8a).

Port `plan()` i `alt_name` ze skryptu adb-backup (`restore.py`). Gwarancje:
* cel = ta sama ścieżka pod `/sdcard/` co na starym telefonie; „już jest” = ten sam rozmiar
  i `|mtime telefonu − mtime kopii| ≤ 2 s` — taki plik nie jest wgrywany;
* inny plik pod tą ścieżką → zapis obok jako `nazwa (z kopii).ext`, `(z kopii 2)`…; nazwa
  zastępcza jest wolna na telefonie i nie jest celem żadnego innego pliku tego planu. Ścieżka,
  o którą `stat` nie umiał odpowiedzieć (np. brak dostępu), liczy się jako zajęta — nigdy nie
  nadpisujemy cudzego pliku;
* `taken_alts` (cele z poprzedniego podejścia) mają pierwszeństwo: ten plik jest nasz, więc bez
  ponownego szukania nazwy (silnik nadpisuje go tylko w stanie `pushing`).

Na telefon idą wyłącznie odczyty (`stat`, `df`); wołający podaje `guard.AppendOnlyAdb`.
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from admenot.engine.adb.transport import AdbError, AdbTransport

from .apkcheck import BUNDLE_EXT, ApkCheck, load_or_check
from .backup import restat
from .guard import q, safe_target
from .state import FileRow, State
from .store import CopyDir
from .telephony import Stopped

UPLOAD_GROUPS = ("photos", "videos", "downloads", "whatsapp")  # oraz "other:<folder>" z kopii
VIDEO_EXT = frozenset({".mp4", ".mov", ".3gp", ".3g2", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".mts",
                       ".m2ts", ".wmv", ".flv"})
GiB = 1024 ** 3
MTIME_TOLERANCE = 2  # s
ALT_ROUND = 5  # nazwy zastępcze sprawdzane jednym `stat` na plik i rundę
ALT_MAX = 1000

Action = Literal["push", "exists", "rename"]


@dataclass(frozen=True)
class PlanFile:
    remote: str  # ścieżka na starym telefonie (klucz w kopii)
    local: Path  # bezwzględna ścieżka pliku w kopii
    size: int
    mtime: int
    group: str
    action: Action
    target: str  # `remote` albo nazwa zastępcza
    apk: ApkCheck | None


@dataclass(frozen=True)
class PhoneSpace:
    free: int
    total: int | None  # None = nie udało się odczytać


@dataclass(frozen=True)
class GroupTotals:
    files: int  # wszystkie pliki grupy w kopii
    bytes: int  # do wgrania (bez „już jest”), APK wg domyślnego wyboru
    exists: int
    rename: int


def reserve(space: PhoneSpace) -> int:
    """Zapas, którego nie zapełniamy: max(1 GiB, 5% pamięci); pamięć nieznana — 1 GiB."""
    return GiB if space.total is None else max(GiB, space.total // 20)


def _apk_selected(apk: ApkCheck | None, apk_on: set[str]) -> bool:
    """Szkodliwy nigdy; podejrzany tylko zaznaczony przez serwisanta; reszta wg `default_on`."""
    return apk is None or (apk.outcome != "malicious" and (apk.default_on or apk.remote in apk_on))


@dataclass
class RestorePlan:
    files: list[PlanFile]
    groups: dict[str, GroupTotals]
    space: PhoneSpace
    reserve: int

    def need(self, groups: set[str], apk_on: set[str]) -> int:
        """Bajty do wgrania w wybranych grupach; zapis obok liczy się w pełnym rozmiarze."""
        return sum(f.size for f in self.files
                   if f.group in groups and f.action != "exists" and _apk_selected(f.apk, apk_on))

    def fits(self, groups: set[str], apk_on: set[str]) -> bool:
        return self.need(groups, apk_on) + self.reserve <= self.space.free


def upload_group(category: str, remote: str) -> str:
    """Kategoria kopii → grupa wgrywania; `media` dzielone po rozszerzeniu (nieznane → zdjęcia)."""
    if category == "media":
        return "videos" if posixpath.splitext(remote)[1].lower() in VIDEO_EXT else "photos"
    return category


def alt_name(target: str, n: int) -> str:
    """`dir/nazwa (z kopii).ext`, od `n == 2`: `dir/nazwa (z kopii n).ext`. Bez rozszerzenia
    (także `.nomedia`) — sufiks na końcu."""
    d, name = target.rsplit("/", 1)
    stem, ext = posixpath.splitext(name)
    suffix = " (z kopii)" if n == 1 else f" (z kopii {n})"
    return f"{d}/{stem}{suffix}{ext}"


def read_space(adb: AdbTransport) -> PhoneSpace:
    """`df -k /sdcard/`: całość z kolumny 1K-blocks, wolne z Available. Nieczytelne → `AdbError`."""
    out = adb.shell(f"df -k {q('/sdcard/')}")
    for line in reversed(out.splitlines()):
        cols = line.split()
        if len(cols) >= 4 and cols[3].isdigit():
            return PhoneSpace(int(cols[3]) * 1024, int(cols[1]) * 1024 if cols[1].isdigit() else None)
    raise AdbError("command_failed", f"df: unreadable output: {out[:120]!r}")


def _check(should_stop: Callable[[], bool]) -> None:
    if should_stop():
        raise Stopped()


def _same(st: tuple[int, int], row: FileRow) -> bool:
    return st[0] == row.size and abs(st[1] - row.mtime) <= MTIME_TOLERANCE


def _done_rows(copy: CopyDir) -> list[FileRow]:
    state = State(copy.state_path)
    try:
        return state.by_status("done")
    finally:
        state.close()


def _resolve_conflicts(adb: AdbTransport, conflicts: list[FileRow], used: set[str],
                       should_stop: Callable[[], bool]) -> dict[str, tuple[Action, str]]:
    """Nazwa zastępcza dla każdego konfliktu: pierwsza wolna na telefonie i w planie (`used`,
    casefold). Identyczny plik pod nazwą zastępczą (stan wgrywania utracony) → „już jest”.
    Runda, w której telefon nie odpowiedział o żadnej nazwie (np. brak dostępu do folderu), bierze
    pierwszą z nich: `stat` odmówiony = zapis też, więc nic nie zostanie nadpisane."""
    decided: dict[str, tuple[Action, str]] = {}
    pending = conflicts
    n = 1
    while pending:
        _check(should_stop)
        if n > ALT_MAX:
            raise AdbError("command_failed", f"no free name after {ALT_MAX} tries")
        cands = {r.remote: [alt_name(r.remote, k) for k in range(n, n + ALT_ROUND)] for r in pending}
        stats, gone = restat(adb, [c for names in cands.values() for c in names])
        left: list[FileRow] = []
        for r in pending:
            choice: tuple[Action, str] | None = None
            unknown: str | None = None
            known = False
            for c in cands[r.remote]:
                if c.casefold() in used:
                    continue
                if c in stats:
                    if _same(stats[c], r):
                        choice = ("exists", c)
                        break
                    known = True
                elif c in gone:
                    choice = ("rename", c)
                    break
                elif unknown is None:
                    unknown = c
            if choice is None and not known and unknown is not None:
                choice = ("rename", unknown)
            if choice is None:
                left.append(r)
                continue
            decided[r.remote] = choice
            used.add(choice[1].casefold())
        pending = left
        n += ALT_ROUND
    return decided


def build_plan(adb: AdbTransport, copy: CopyDir, should_stop: Callable[[], bool],
               taken_alts: dict[str, str] | None = None) -> RestorePlan:
    """Plan wgrywania plików kopii (wiersze `done`) na telefon `adb`. `should_stop` → `Stopped`."""
    taken = taken_alts or {}
    rows = _done_rows(copy)
    _check(should_stop)
    targets = {r.remote: safe_target(taken.get(r.remote, r.remote)) for r in rows}
    stats, gone = restat(adb, list(targets.values()))
    _check(should_stop)

    decided: dict[str, tuple[Action, str]] = {}
    conflicts: list[FileRow] = []
    for r in rows:
        tgt = targets[r.remote]
        if tgt in stats and _same(stats[tgt], r):
            decided[r.remote] = ("exists", tgt)
        elif tgt in gone or r.remote in taken:
            decided[r.remote] = ("push" if tgt == r.remote else "rename", tgt)
        else:  # cudzy plik albo `stat` bez odpowiedzi
            conflicts.append(r)
    used = {t.casefold() for t in targets.values()}
    decided.update(_resolve_conflicts(adb, conflicts, used, should_stop))

    files_dir = copy.files_dir.absolute()
    local = {r.remote: files_dir.joinpath(*r.local_rel.split("/")) for r in rows}
    apk_files = [(r.remote, local[r.remote]) for r in rows if r.remote.lower().endswith((".apk", *BUNDLE_EXT))]
    checks = {c.remote: c for c in load_or_check(copy, apk_files)} if apk_files else {}
    _check(should_stop)

    files = [PlanFile(r.remote, local[r.remote], r.size, r.mtime, upload_group(r.root, r.remote),
                      decided[r.remote][0], decided[r.remote][1], checks.get(r.remote)) for r in rows]
    groups: dict[str, GroupTotals] = {}
    for f in files:
        g = groups.get(f.group, GroupTotals(0, 0, 0, 0))
        counted = f.action != "exists" and _apk_selected(f.apk, set())
        groups[f.group] = GroupTotals(g.files + 1, g.bytes + (f.size if counted else 0),
                                      g.exists + (f.action == "exists"), g.rename + (f.action == "rename"))
    space = read_space(adb)
    return RestorePlan(files, groups, space, reserve(space))
