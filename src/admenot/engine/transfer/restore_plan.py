"""Plan wgrywania kopii na nowy telefon: co, dokąd i czy się zmieści (spec Etapu 2 §4.2, §4.3, §8a).

Port `plan()` i `alt_name` ze skryptu adb-backup (`restore.py`). Gwarancje:
* cel = ta sama ścieżka pod `/sdcard/` co na starym telefonie; „już jest” = ten sam rozmiar
  i `|mtime telefonu − mtime kopii| ≤ 2 s` — taki plik nie jest wgrywany;
* inny plik pod tą ścieżką → zapis obok jako `nazwa (z kopii).ext`, `(z kopii 2)`…; nazwa
  zastępcza jest na pewno wolna na telefonie („No such file”) i nie jest celem żadnego innego
  pliku tego planu — nigdy nie nadpisujemy cudzego pliku. Bez odpowiedzi `stat` (dwa razy
  przekroczony czas, brak linii o ścieżce) plan się nie buduje: nie zgadujemy;
* pliki brakujące w kopii na PC (albo o innym rozmiarze niż w stanie) pomijamy i liczymy w `missing`;
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
from .backup import _cmd_batches
from .guard import STAT_TAIL, q, safe_target
from .state import FileRow, State
from .store import CopyDir
from .telephony import Stopped

UPLOAD_GROUPS = ("photos", "videos", "downloads", "whatsapp")  # oraz "other:<folder>" z kopii
VIDEO_EXT = frozenset({".mp4", ".mov", ".3gp", ".3g2", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".mts",
                       ".m2ts", ".wmv", ".flv"})
GiB = 1024 ** 3
MTIME_TOLERANCE = 2  # s
ALT_ROUND = 5  # nazwy zastępcze sprawdzane jednym `stat` na plik i rundę
ALT_MAX = 100
STAT_TIMEOUT = 120  # s na paczkę; przekroczony dwa razy z rzędu → `AdbError`
_ERR_PREFIX = "stat: '"

Action = Literal["push", "exists", "rename"]
Answer = tuple[int, int] | Literal["gone", "denied"]  # (rozmiar, mtime) albo czego nie ma / czego nie wolno


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
    missing: int = 0  # pliki kopii, których nie ma na PC (albo mają inny rozmiar) — poza `files`

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
    """`dir/nazwa (z kopii).ext`, od `n == 2`: `dir/nazwa (z kopii n).ext`; rozszerzenie = część
    po ostatniej kropce (`a.tar.gz` → `a.tar (z kopii).gz`). Bez rozszerzenia, także plik z jedną
    kropką na początku (`.nomedia`) — sufiks na końcu; `.foo.txt` → `.foo (z kopii).txt`."""
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


def _same(answer: Answer | None, row: FileRow) -> bool:
    return isinstance(answer, tuple) and answer[0] == row.size and abs(answer[1] - row.mtime) <= MTIME_TOLERANCE


def _stat_batch(adb: AdbTransport, batch: list[str]) -> str:
    """Jedna paczka `stat … STAT_TAIL` (kod zawsze 0, błędy jako linie wyniku). Przekroczony czas —
    jedna powtórka, potem `AdbError` idzie wyżej."""
    cmd = "stat -c " + q("%s|%Y|%n") + " " + " ".join(q(r) for r in batch) + STAT_TAIL
    try:
        return adb.shell(cmd, timeout=STAT_TIMEOUT)
    except AdbError as exc:
        if exc.kind != "timeout":
            raise
    return adb.shell(cmd, timeout=STAT_TIMEOUT)


def stat_all(adb: AdbTransport, remotes: list[str], should_stop: Callable[[], bool]) -> dict[str, Answer]:
    """Odpowiedź telefonu o każdą ścieżkę: (rozmiar, mtime), `gone` („No such file”) albo `denied`
    (każdy inny błąd, np. „Permission denied”). Ścieżka bez żadnej linii → `AdbError` (nie zgadujemy)."""
    answers: dict[str, Answer] = {}
    for batch in _cmd_batches(remotes):
        _check(should_stop)
        for raw in _stat_batch(adb, batch).split("\n"):
            line = raw.removesuffix("\r")
            if line.startswith(_ERR_PREFIX):
                path, sep, msg = line[len(_ERR_PREFIX):].rpartition("': ")
                if sep:
                    answers[path] = "gone" if "no such file" in msg.lower() else "denied"
                continue
            bits = line.split("|", 2)
            if len(bits) == 3 and bits[0].isdigit() and bits[1].lstrip("-").isdigit():
                answers[bits[2]] = (int(bits[0]), int(bits[1]))
        unanswered = sum(1 for r in batch if r not in answers)
        if unanswered:
            raise AdbError("command_failed", f"stat: no answer for {unanswered} paths")
    return answers


def _done_rows(copy: CopyDir) -> list[FileRow]:
    state = State(copy.state_path)
    try:
        return state.by_status("done")
    finally:
        state.close()


def _resolve_conflicts(adb: AdbTransport, conflicts: list[FileRow], used: set[str],
                       should_stop: Callable[[], bool]) -> dict[str, tuple[Action, str]]:
    """Nazwa zastępcza dla każdego konfliktu: pierwsza na pewno wolna na telefonie (`gone`) i w planie
    (`used`, casefold — /sdcard nie rozróżnia wielkości liter). Nazwa `denied` liczy się jako zajęta.
    Identyczny plik pod nazwą zastępczą (stan wgrywania utracony) → „już jest”."""
    decided: dict[str, tuple[Action, str]] = {}
    pending = conflicts
    n = 1
    while pending:
        if n > ALT_MAX:
            raise AdbError("command_failed", f"no free name after {ALT_MAX} tries")
        cands = {r.remote: [alt_name(r.remote, k) for k in range(n, n + ALT_ROUND)] for r in pending}
        answers = stat_all(adb, [c for names in cands.values() for c in names], should_stop)
        left: list[FileRow] = []
        for r in pending:
            choice: tuple[Action, str] | None = None
            for c in cands[r.remote]:
                if c.casefold() in used:
                    continue
                if _same(answers[c], r):
                    choice = ("exists", c)
                    break
                if answers[c] == "gone":
                    choice = ("rename", c)
                    break
            if choice is None:
                left.append(r)
                continue
            decided[r.remote] = choice
            used.add(choice[1].casefold())
        pending = left
        n += ALT_ROUND
    return decided


def _local_rows(copy: CopyDir, rows: list[FileRow]) -> tuple[list[tuple[FileRow, Path]], int]:
    """(wiersze z plikiem w kopii, liczba brakujących): plik usunięty z PC (np. przez antywirus)
    albo o innym rozmiarze niż w stanie nie jest wgrywany."""
    files_dir = copy.files_dir.absolute()
    present: list[tuple[FileRow, Path]] = []
    for r in rows:
        local = files_dir.joinpath(*r.local_rel.split("/"))
        try:
            ok = local.stat().st_size == r.size
        except OSError:
            ok = False
        if ok:
            present.append((r, local))
    return present, len(rows) - len(present)


def build_plan(adb: AdbTransport, copy: CopyDir, should_stop: Callable[[], bool],
               taken_alts: dict[str, str] | None = None) -> RestorePlan:
    """Plan wgrywania plików kopii (wiersze `done`) na telefon `adb`. `should_stop` → `Stopped`;
    telefon bez odpowiedzi o którąś ścieżkę → `AdbError`."""
    taken = taken_alts or {}
    present, missing = _local_rows(copy, _done_rows(copy))
    rows = [r for r, _ in present]
    local = {r.remote: path for r, path in present}
    targets = {r.remote: safe_target(taken.get(r.remote, r.remote)) for r in rows}
    answers = stat_all(adb, list(targets.values()), should_stop)

    decided: dict[str, tuple[Action, str]] = {}
    conflicts: list[FileRow] = []
    for r in rows:
        tgt = targets[r.remote]
        answer = answers[tgt]
        if _same(answer, r):
            decided[r.remote] = ("exists", tgt)
        # `denied`: FUSE, który odmawia `stat`, odmawia też zapisu — `push` zostanie odrzucony
        # (silnik: `denied`) i niczego nie nadpisze; bez szukania nazwy zastępczej.
        elif answer in ("gone", "denied") or r.remote in taken:
            decided[r.remote] = ("push" if tgt == r.remote else "rename", tgt)
        else:  # cudzy plik pod tą ścieżką
            conflicts.append(r)
    used = {t.casefold() for t in targets.values()}
    decided.update(_resolve_conflicts(adb, conflicts, used, should_stop))

    apk_files = [(r.remote, local[r.remote]) for r in rows if r.remote.lower().endswith((".apk", *BUNDLE_EXT))]
    checks = {c.remote: c for c in load_or_check(copy, apk_files)} if apk_files else {}
    unchecked = {remote for remote, _ in apk_files} - set(checks)  # zniknął z PC w trakcie: nie bez oceny
    if unchecked:
        rows = [r for r in rows if r.remote not in unchecked]
        missing += len(unchecked)
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
    return RestorePlan(files, groups, space, reserve(space), missing)


