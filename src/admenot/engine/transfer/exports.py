"""Pliki eksportu kontaktów, SMS-ów i połączeń na starym telefonie (gdy provider odmawia odczytu).

Rozpoznajemy po zawartości, nie po nazwie czy folderze: `.vcf` zaczyna się od `BEGIN:VCARD`,
`.xml` ma korzeń `<smses` (SMS Backup & Restore) albo `<calls`. Skan niczego nie pobiera —
czyta tylko nagłówek (`head -c`, `HEAD_BYTES`) najnowszych `MAX_CANDIDATES` plików na rozszerzenie.
Dokładną liczbę rekordów daje dopiero `count_export` na pobranym pliku.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Literal

from admenot.engine.adb.transport import AdbError, AdbTransport

from .guard import HEAD_LIMIT, q
from .telephony import _CONNECTION_KINDS

if TYPE_CHECKING:  # inventory.py importuje ten moduł, więc w czasie działania nie możemy odwrotnie
    from .inventory import RemoteFile

ExportKind = Literal["contacts", "sms", "calls"]
EXPORT_KINDS: tuple[ExportKind, ...] = ("contacts", "sms", "calls")
HEAD_BYTES = HEAD_LIMIT
MAX_CANDIDATES = 50
_BOM = b"\xef\xbb\xbf"
_XML_ROOTS: dict[str, ExportKind] = {"smses": "sms", "calls": "calls"}
_XML_TAGS: dict[ExportKind, re.Pattern[bytes]] = {
    "sms": re.compile(rb"<(?:sms|mms)[\s/>]"),
    "calls": re.compile(rb"<call[\s/>]"),
}
_XML_CLOSE: dict[ExportKind, bytes] = {"sms": b"</smses>", "calls": b"</calls>"}
_TAIL_BYTES = 256
_COUNT_CHUNK = 1 << 20
_MAX_TAG = 6  # najdłuższe dopasowanie wzorca: `<call>`
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
    """Polecenie czytające początek pliku — jedyna postać `head`, jaką przepuszcza strażnik.

    Na bardzo starym Androidzie (toolbox bez `head -c`) exec-out zwraca tekst błędu jako bajty,
    więc detekcja niczego nie znajdzie — kończy się bezpiecznie, bez fałszywych trafień."""
    return f"head -c {HEAD_BYTES} {q(remote)}"


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _xml_root(head: bytes) -> tuple[ExportKind, int | None] | None:
    """Rodzaj XML-a (`<smses` / `<calls`) i deklarowane `count` z nagłówka pliku albo None."""
    text = head.removeprefix(_BOM).decode("utf-8", errors="ignore")  # ucięty w środku znaku wielobajtowego
    pos = 0
    while m := _PROLOG.match(text, pos):
        pos = m.end()
    root = _ROOT.match(text, pos)
    if root is None:
        return None
    count = _COUNT_ATTR.search(root.group(2))
    return _XML_ROOTS[root.group(1)], int(count.group(1)) if count else None


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
        return _xml_root(head)
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
    with path.open("rb") as fh:
        root = _xml_root(fh.read(HEAD_BYTES))
        if root is None or root[0] != kind:
            raise ExportFormatError(f"Nieoczekiwany korzeń XML w {path.name}")
        size = fh.seek(0, 2)
        fh.seek(max(0, size - _TAIL_BYTES))
        if not fh.read().rstrip().endswith(_XML_CLOSE[kind]):  # brak zamknięcia = plik ucięty
            raise ExportFormatError(f"Plik XML jest ucięty: {path.name}")
        fh.seek(0)
        return _count_tags(fh, _XML_TAGS[kind])


def _count_tags(fh: BinaryIO, tag: re.Pattern[bytes]) -> int:
    """Liczy tagi otwierające bez parsowania XML-a (eksporty z emoji mają odwołania do znaków
    zastępczych, które expat odrzuca). W wartościach atrybutów `<` jest zapisane jako `&lt;`,
    więc surowe `<sms` występuje tylko jako tag. Dopasowania zaczynające się w ostatnich
    `_MAX_TAG - 1` bajtach bloku liczymy dopiero w następnym, więc tag na granicy bloków
    liczy się raz."""
    count = 0
    carry = b""
    while True:
        chunk = fh.read(_COUNT_CHUNK)
        buf = carry + chunk
        limit = len(buf) if not chunk else len(buf) - (_MAX_TAG - 1)
        count += sum(1 for m in tag.finditer(buf) if m.start() < limit)
        if not chunk:
            return count
        carry = buf[max(limit, 0):]
