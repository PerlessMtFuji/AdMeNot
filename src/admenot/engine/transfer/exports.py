"""Pliki eksportu kontaktów, SMS-ów i połączeń na starym telefonie (gdy provider odmawia odczytu).

Rozpoznajemy po zawartości, nie po nazwie czy folderze: `.vcf` zaczyna się od `BEGIN:VCARD`,
`.xml` ma korzeń `<smses` (SMS Backup & Restore) albo `<calls`. Skan niczego nie pobiera —
czyta tylko nagłówek (`head -c`, `HEAD_BYTES`) najnowszych `MAX_CANDIDATES` plików na rozszerzenie.
Dokładną liczbę rekordów daje dopiero `count_export` na pobranym pliku.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from admenot.engine.adb.transport import AdbError, AdbTransport

from .guard import HEAD_LIMIT, q
from .inventory import RemoteFile
from .telephony import _CONNECTION_KINDS

ExportKind = Literal["contacts", "sms", "calls"]
EXPORT_KINDS: tuple[ExportKind, ...] = ("contacts", "sms", "calls")
HEAD_BYTES = HEAD_LIMIT
MAX_CANDIDATES = 50
_BOM = b"\xef\xbb\xbf"
_XML_ROOTS: dict[str, ExportKind] = {"smses": "sms", "calls": "calls"}
_XML_ITEMS: dict[ExportKind, frozenset[str]] = {
    "sms": frozenset({"sms", "mms"}),
    "calls": frozenset({"call"}),
}
_PROLOG = re.compile(r"\s*(?:<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>)", re.DOTALL)
_ROOT = re.compile(r"\s*<(smses|calls)(?=[\s>/]|$)([^>]*)")
_COUNT_ATTR = re.compile(r"""\bcount\s*=\s*["'](\d+)["']""")
_VCARD_BEGIN = "BEGIN:VCARD"
_PROPAGATE_KINDS = _CONNECTION_KINDS | {"timeout"}


@dataclass(frozen=True)
class ExportFile:
    remote: str
    size: int
    mtime: int
    kind: ExportKind
    count: int | None  # None = nieznana bez pobrania pliku


class ExportFormatError(Exception):
    """Pobrany plik nie jest eksportem oczekiwanego rodzaju (albo jest uszkodzony)."""


def head_cmd(remote: str) -> str:
    """Polecenie czytające początek pliku — jedyna postać `head`, jaką przepuszcza strażnik."""
    return f"head -c {HEAD_BYTES} {q(remote)}"


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def detect_export(head: bytes, name: str, size: int) -> tuple[ExportKind, int | None] | None:
    """Rodzaj eksportu i liczba rekordów (None = nieznana) albo None, gdy to nie eksport.

    Rozszerzenie z `name` (bez rozróżniania wielkości liter) musi zgadzać się z zawartością."""
    ext = _extension(name)
    read = len(head)
    head = head.removeprefix(_BOM)
    if ext == "vcf":
        text = head.decode("utf-8", errors="replace").lstrip()
        if not text.startswith(_VCARD_BEGIN):
            return None
        if size > read:
            return "contacts", None  # plik większy niż nagłówek — nie znamy liczby
        return "contacts", sum(1 for ln in text.splitlines() if ln.strip() == _VCARD_BEGIN)
    if ext == "xml":
        text = head.decode("utf-8", errors="ignore")  # ucięty w środku znaku wielobajtowego
        pos = 0
        while m := _PROLOG.match(text, pos):
            pos = m.end()
        root = _ROOT.match(text, pos)
        if root is None:
            return None
        count = _COUNT_ATTR.search(root.group(2))
        return _XML_ROOTS[root.group(1)], int(count.group(1)) if count else None
    return None


def find_exports(adb: AdbTransport, files: list[RemoteFile], kinds: set[ExportKind],
                 should_stop: Callable[[], bool]) -> dict[ExportKind, list[ExportFile]]:
    """Pliki eksportu z `files` dla żądanych rodzajów, od najnowszego (mtime malejąco, potem ścieżka).

    Czyta nagłówki co najwyżej `MAX_CANDIDATES` najnowszych plików na rozszerzenie. Błąd połączenia
    przechodzi wyżej; inny błąd odczytu jednego pliku pomija ten plik."""
    wanted: set[str] = set()
    if "contacts" in kinds:
        wanted.add("vcf")
    if kinds & {"sms", "calls"}:
        wanted.add("xml")
    found: dict[ExportKind, list[ExportFile]] = {}
    for ext in sorted(wanted):
        candidates = sorted((f for f in files if _extension(f.remote) == ext),
                            key=lambda f: (-f.mtime, f.remote))[:MAX_CANDIDATES]
        for f in candidates:
            if should_stop():
                break
            try:
                head = adb.run_bytes(["exec-out", head_cmd(f.remote)])
            except AdbError as exc:
                if exc.kind in _PROPAGATE_KINDS:
                    raise
                continue
            hit = detect_export(head, f.remote.rsplit("/", 1)[-1], f.size)
            if hit is None or hit[0] not in kinds:
                continue
            found.setdefault(hit[0], []).append(ExportFile(f.remote, f.size, f.mtime, hit[0], hit[1]))
    for items in found.values():
        items.sort(key=lambda e: (-e.mtime, e.remote))
    return found


def count_export(path: Path, kind: ExportKind) -> int:
    """Dokładna liczba rekordów w pobranym pliku (wizytówki / `<sms>`+`<mms>` / `<call>`)."""
    if kind == "contacts":
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
        if not text.lstrip().startswith(_VCARD_BEGIN):
            raise ExportFormatError(f"To nie jest plik vCard: {path.name}")
        return sum(1 for ln in text.splitlines() if ln.strip() == _VCARD_BEGIN)
    items = _XML_ITEMS[kind]
    expected_root = "smses" if kind == "sms" else "calls"
    count = 0
    seen_root = False
    try:
        with path.open("rb") as fh:
            for event, elem in ET.iterparse(fh, events=("start", "end")):
                if not seen_root:
                    if event != "start" or elem.tag != expected_root:
                        raise ExportFormatError(f"Nieoczekiwany korzeń <{elem.tag}> w {path.name}")
                    seen_root = True
                elif event == "end" and elem.tag in items:
                    count += 1
                    elem.clear()
    except ET.ParseError as exc:
        raise ExportFormatError(f"Uszkodzony plik XML: {path.name}") from exc
    if not seen_root:
        raise ExportFormatError(f"Pusty plik XML: {path.name}")
    return count
