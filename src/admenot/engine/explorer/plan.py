"""Plan zadania eksploratora: rozwinięcie zaznaczenia, nazwy docelowe, konflikty, miejsce, FAT32, długie ścieżki.

Plan niczego nie kopiuje ani nie zapisuje. Problemy są zbierane (może być kilka naraz), a o starcie
decyduje wywołujący. `check_hash` = ta sama nazwa i rozmiar — czy to ten sam plik, rozstrzyga suma kontrolna.
"""

from __future__ import annotations

import os
import posixpath
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from admenot.engine.explorer import hostfs
from admenot.engine.explorer.guard import ExplorerAdb, is_tmp_name
from admenot.engine.explorer.listing import ListError, list_dir
from admenot.engine.transfer.guard import safe_target
from admenot.engine.transfer.winpath import sanitize_component

__all__ = [
    "FAT32_MAX_FILE",
    "PHONE_MAX_PATH",
    "Item",
    "Problem",
    "TaskPlan",
    "phone_free_bytes",
    "plan_to_pc",
    "plan_to_phone",
    "side_name",
]

FAT32_MAX_FILE = 4294967295  # największy plik na FAT32 (4 GiB - 1 B)
PHONE_MAX_PATH = 4095  # PATH_MAX Androida (bajty UTF-8)

Action = Literal["copy", "skip_same", "renamed", "check_hash"]
Suffix = Literal["z komputera", "z telefonu"]


@dataclass(frozen=True)
class Item:
    src: str
    dst: str
    size: int
    mtime: int
    action: Action


@dataclass(frozen=True)
class Problem:
    key: Literal["no_space", "read_only", "fat32_big", "path_too_long", "denied"]
    detail: dict[str, Any]


@dataclass(frozen=True)
class TaskPlan:
    kind: Literal["to_pc", "to_phone"]
    items: list[Item]
    dirs: list[str]  # foldery docelowe do utworzenia (nadrzędne przed podrzędnymi)
    bytes: int  # suma rozmiarów wszystkich pozycji (górne ograniczenie ilości do przesłania)
    problems: list[Problem]
    skipped: int = 0  # elementy pominięte: nazwy z nową linią, dowiązania, zniknięte zaznaczenia


def side_name(name: str, taken: set[str], suffix: Suffix) -> str:
    """`a.jpg` -> `a (z telefonu).jpg`, potem `a (z telefonu 2).jpg`; przed ostatnią kropką (`a.tar (z telefonu).gz`).

    `taken` porównujemy bez względu na wielkość liter (Windows i /sdcard ich nie rozróżniają)."""
    stem, ext = os.path.splitext(name)
    low = {t.casefold() for t in taken}
    n = 1
    while True:
        tag = suffix if n == 1 else f"{suffix} {n}"
        cand = f"{stem} ({tag}){ext}"
        if cand.casefold() not in low:
            return cand
        n += 1


class _Dir:
    """Jeden folder docelowy: co już w nim jest (`existing`: casefold -> (czy folder, rozmiar)) i co zaplanowano."""

    def __init__(self, existing: dict[str, tuple[bool, int]], names: set[str], is_new: bool) -> None:
        self.existing = existing
        self.names = names  # oryginalne nazwy istniejące + zaplanowane (dla `side_name`)
        self.planned: set[str] = set()
        self.is_new = is_new

    def allocate(self, name: str, is_dir: bool, size: int, suffix: Suffix) -> tuple[str, Action, bool]:
        """(nazwa końcowa, akcja, czy folder już istnieje i zostaje scalony)."""
        key = name.casefold()
        final, action, merged = name, "copy", False
        if key in self.planned:
            final, action = side_name(name, self.names, suffix), "renamed"
        elif key in self.existing:
            ex_dir, ex_size = self.existing[key]
            if is_dir and ex_dir:
                merged = True
            elif not is_dir and not ex_dir and ex_size == size:
                action = "check_hash"
            else:
                final, action = side_name(name, self.names, suffix), "renamed"
        self.planned.add(final.casefold())
        self.names.add(final)
        return final, action, merged


# ---------------------------------------------------------------------------------------------
# telefon -> komputer


class _PcSide:
    """Foldery docelowe na komputerze (`str` ścieżki, długie z `\\\\?\\`)."""

    def __init__(self) -> None:
        self.dirs: dict[str, _Dir] = {}

    def folder(self, path: str, is_new: bool) -> _Dir:
        d = self.dirs.get(path)
        if d is None:
            existing: dict[str, tuple[bool, int]] = {}
            names: set[str] = set()
            if not is_new:
                try:
                    with os.scandir(hostfs.long_path(path)) as it:
                        for e in it:
                            is_dir = e.is_dir(follow_symlinks=False)
                            existing[e.name.casefold()] = (is_dir, 0 if is_dir else e.stat().st_size)
                            names.add(e.name)
                except (OSError, ValueError):  # brak folderu albo ścieżka ponad limit Win32 — i tak oznaczona jako path_too_long
                    pass
            d = self.dirs[path] = _Dir(existing, names, is_new)
        return d


def plan_to_pc(adb: ExplorerAdb, paths: list[str], dest: Path, *,
               free_bytes: Callable[[Path], int] = hostfs.free_bytes,
               filesystem: Callable[[Path], str] = hostfs.filesystem,
               writable: Callable[[Path], bool] = hostfs.writable,
               exclude: Collection[str] = ()) -> TaskPlan:
    """Plan kopii zaznaczenia z telefonu do folderu `dest`: foldery rozwijane rekurencyjnie (z ukrytymi plikami),
    struktura zachowana pod `dest/<nazwa zaznaczenia>/…`, każdy element nazwy przez `sanitize_component`.
    `exclude` — ścieżki plików i folderów, które serwisant pominął w oknie problemów."""
    items: list[Item] = []
    dirs: list[str] = []
    problems: list[Problem] = []
    skipped = 0
    denied: list[str] = []
    side = _PcSide()
    dest_s = str(dest)

    def join(parent: str, name: str) -> str:
        return os.path.join(parent, name)

    def add_file(parent: str, name: str, src: str, size: int, mtime: int) -> None:
        final, action, _ = side.folder(parent, False).allocate(sanitize_component(name), False, size, "z telefonu")
        items.append(Item(src, hostfs.long_path(join(parent, final)), size, mtime, action))

    def add_dir(parent: str, parent_new: bool, name: str) -> tuple[str, bool]:
        final, _, merged = side.folder(parent, parent_new).allocate(sanitize_component(name), True, 0, "z telefonu")
        child = join(parent, final)
        dirs.append(hostfs.long_path(child))
        return child, not merged

    def walk(remote: str, local: str, is_new: bool) -> None:
        nonlocal skipped
        try:
            res = list_dir(adb, remote, include_hidden=True)
        except ListError as exc:
            if exc.kind == "denied":
                denied.append(remote)
                return
            raise
        skipped += res.skipped
        for e in res.entries:
            if is_tmp_name(e.name) or e.path in exclude:
                continue
            if e.kind == "dir":
                child, child_new = add_dir(local, is_new, e.name)
                walk(e.path, child, child_new)
            else:
                add_file(local, e.name, e.path, e.size, e.mtime)

    parents: dict[str, dict[str, Any]] = {}
    for p in paths:
        if p.rstrip("/") in exclude:
            continue
        parent = posixpath.dirname(p.rstrip("/"))
        if parent not in parents:
            parents[parent] = {e.path: e for e in list_dir(adb, parent, include_hidden=True).entries}
        e = parents[parent].get(p.rstrip("/"))
        if e is None:
            skipped += 1
        elif e.kind == "file":
            add_file(dest_s, e.name, e.path, e.size, e.mtime)
        else:
            child, child_new = add_dir(dest_s, False, e.name)
            walk(e.path, child, child_new)

    total = sum(i.size for i in items)
    if denied:
        problems.append(Problem("denied", {"paths": denied}))
    if not writable(dest):
        problems.append(Problem("read_only", {"path": dest_s}))
    free = free_bytes(dest)
    if total > free:
        problems.append(Problem("no_space", {"need": total, "free": free, "missing": total - free}))
    if filesystem(dest).upper() == "FAT32":
        big = [i.src for i in items if i.size > FAT32_MAX_FILE]
        if big:
            problems.append(Problem("fat32_big", {"names": [posixpath.basename(p) for p in big], "paths": big,
                                                  "max": FAT32_MAX_FILE}))
    too_long = [i.dst for i in items if len(i.dst.removeprefix("\\\\?\\")) > hostfs.MAX_LONG_PATH]
    if too_long:
        problems.append(Problem("path_too_long", {"count": len(too_long), "limit": hostfs.MAX_LONG_PATH}))
    return TaskPlan("to_pc", items, dirs, total, problems, skipped)


# ---------------------------------------------------------------------------------------------
# komputer -> telefon


def phone_free_bytes(adb: ExplorerAdb) -> int | None:
    """Wolne miejsce z `df -k /sdcard` (kolumna „Available”, KiB: token tuż przed kolumną `Use%`)."""
    lines = [ln for ln in adb.shell("df -k /sdcard").splitlines() if ln.strip()]
    for ln in reversed(lines):
        tokens = ln.split()
        for i, tok in enumerate(tokens):
            if i >= 2 and tok.endswith("%") and tokens[i - 1].isdigit():
                return int(tokens[i - 1]) * 1024
    return None


def _is_locked(locked: Callable[[str], bool] | Collection[str], path: str) -> bool:
    if callable(locked):
        return locked(path)
    p = path.rstrip("/")
    return any(p == k.rstrip("/") or p.startswith(k.rstrip("/") + "/") for k in locked)


def plan_to_phone(adb: ExplorerAdb, locals_: list[Path], remote_dir: str, *,
                  locked: Callable[[str], bool] | Collection[str] = ()) -> TaskPlan:
    """Plan wysłania plików/folderów z komputera do `remote_dir` na telefonie (pod `/sdcard/`).

    `locked` — foldery zablokowane przez Androida (zbiór ścieżek albo predykat), znane z sondy listowania;
    cel w takim folderze (lub pod nim) daje `Problem("denied")` jeszcze przed startem."""
    base = safe_target(remote_dir.rstrip("/") + "/x")[:-2]
    items: list[Item] = []
    dirs: list[str] = []
    problems: list[Problem] = []
    skipped = 0
    denied: list[str] = []
    cache: dict[str, _Dir] = {}

    def folder(path: str, is_new: bool) -> _Dir:
        d = cache.get(path)
        if d is None:
            existing: dict[str, tuple[bool, int]] = {}
            names: set[str] = set()
            if not is_new:
                try:
                    for e in list_dir(adb, path, include_hidden=True).entries:
                        existing[e.name.casefold()] = (e.kind == "dir", 0 if e.kind == "dir" else e.size)
                        names.add(e.name)
                except ListError as exc:
                    if exc.kind == "denied":
                        denied.append(path)
                    elif exc.kind != "missing":
                        raise
            d = cache[path] = _Dir(existing, names, is_new)
        return d

    def add_file(parent: str, parent_new: bool, p: Path | os.DirEntry[str]) -> None:
        st = p.stat()
        name = p.name
        final, action, _ = folder(parent, parent_new).allocate(name, False, st.st_size, "z komputera")
        items.append(Item(str(p.path if isinstance(p, os.DirEntry) else p), f"{parent}/{final}",
                          st.st_size, int(st.st_mtime), action))

    def add_dir(parent: str, parent_new: bool, name: str) -> tuple[str, bool]:
        final, _, merged = folder(parent, parent_new).allocate(name, True, 0, "z komputera")
        child = f"{parent}/{final}"
        dirs.append(child)
        return child, not merged

    def walk(local: str, remote: str, is_new: bool) -> None:
        nonlocal skipped
        try:
            with os.scandir(hostfs.long_path(local)) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            skipped += 1
            return
        for e in entries:
            if e.is_symlink() or "\n" in e.name:
                skipped += 1
            elif is_tmp_name(e.name):
                continue
            elif e.is_dir(follow_symlinks=False):
                child, child_new = add_dir(remote, is_new, e.name)
                walk(e.path, child, child_new)
            else:
                add_file(remote, is_new, e)

    if _is_locked(locked, base):
        denied.append(base)
    else:
        for p in locals_:
            try:
                is_dir = p.is_dir() and not p.is_symlink()
                if not is_dir and not p.is_file():
                    raise OSError
            except OSError:
                skipped += 1
                continue
            if "\n" in p.name:
                skipped += 1
            elif is_dir:
                child, child_new = add_dir(base, False, p.name)
                walk(str(p), child, child_new)
            else:
                add_file(base, False, p)

    total = sum(i.size for i in items)
    if denied:
        problems.append(Problem("denied", {"paths": denied}))
    free = phone_free_bytes(adb)
    if free is not None and total > free:
        problems.append(Problem("no_space", {"need": total, "free": free, "missing": total - free}))
    too_long = [i.dst for i in items if len(i.dst.encode("utf-8")) > PHONE_MAX_PATH]
    if too_long:
        problems.append(Problem("path_too_long", {"count": len(too_long), "limit": PHONE_MAX_PATH}))
    return TaskPlan("to_phone", items, dirs, total, problems, skipped)
