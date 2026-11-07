"""Strumieniowy czytnik XLSX/XLSM do podglądu: tylko wartości komórek, jedno przejście przez arkusz.

openpyxl w trybie tylko-do-odczytu czyta cały arkusz dwa razy, gdy plik nie podaje wymiarów (wiele eksportów
z aplikacji): 5 MB to 4–6 s nawet dla dymka z 30 wierszami. Tu arkusz płynie z archiwum ZIP przez `iterparse`
i kończy się na limicie wywołującego. Wartości jak w Excelu po ostatnim przeliczeniu (zapisany wynik formuły).
Pliki z telefonu mogą być wrogie: części XML z DTD odrzucamy (encje), rozmiar po rozpakowaniu sprawdza `sheets.py`."""

from __future__ import annotations

import datetime as dt
import posixpath
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO
from xml.etree.ElementTree import Element, iterparse

__all__ = ["XlsxBook", "XlsxSheet", "open_xlsx"]

_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_REL_ID_STRICT = "{http://purl.oclc.org/ooxml/officeDocument/relationships}id"
# Wbudowane formaty dat i czasu (ECMA-376, 18.8.30), także chińskie/japońskie/koreańskie.
_DATE_IDS = frozenset({*range(14, 23), *range(27, 37), 45, 46, 47, *range(50, 59)})
_FORMAT_NOISE = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]|_.|\*.')
_COL = re.compile(r"[A-Z]+")


@dataclass
class XlsxSheet:
    name: str
    path: str
    hidden: bool


@dataclass
class XlsxBook:
    zf: zipfile.ZipFile
    sheets: list[XlsxSheet]
    shared: list[str]
    dates: frozenset[int]  # indeksy stylów komórek z formatem daty
    epoch: dt.datetime

    def rows(self, sheet: XlsxSheet, max_cols: int) -> Iterator[list[object]]:
        """Wiersze po kolei (luki jako puste wiersze), najwyżej `max_cols` kolumn — dalsze dają wiersz o długości
        `max_cols + 1`, żeby wywołujący wiedział o obcięciu."""
        expected = 0
        with _part(self.zf, sheet.path) as f:
            for row_no, cells in _sheet_rows(f, max_cols):
                index = expected if row_no is None else row_no
                while expected < index:
                    yield []
                    expected += 1
                yield [self._value(c) for c in cells]
                expected = index + 1

    def _value(self, cell: tuple[str | None, str | None, str | None] | None) -> object:
        if cell is None:
            return None
        kind, style, v = cell
        if v is None:
            return None
        if kind == "s":
            i = int(v)
            return self.shared[i] if 0 <= i < len(self.shared) else ""
        if kind in ("str", "inlineStr", "e", "d"):
            return v
        if kind == "b":
            return v == "1"
        number = float(v)
        if style is not None and int(style) in self.dates:
            # dzień to ułamek doby: 14:30 zapisane jako 0.6041666… dałoby 14:29:59.999 — zaokrąglamy do milisekund
            try:
                when = dt.timedelta(milliseconds=round(number * 86_400_000))
                if 0 <= number < 1:  # sama godzina
                    return (dt.datetime.min + when).time()
                return self.epoch + when
            except OverflowError:
                return number
        return number


def open_xlsx(zf: zipfile.ZipFile) -> XlsxBook:
    workbook = _office_document(zf)
    base = posixpath.dirname(workbook)
    rels = _relationships(zf, _rels_path(workbook))
    root = _parse(zf, workbook)
    epoch = dt.datetime(1899, 12, 30)
    sheets: list[XlsxSheet] = []
    for el in root.iter():
        name = _local(el.tag)
        if name == "workbookPr" and el.get("date1904") in ("1", "true"):
            epoch = dt.datetime(1904, 1, 1)
        elif name == "sheet":
            target = rels.get(el.get(_REL_ID) or el.get(_REL_ID_STRICT) or "")
            if target and target[1].endswith("/worksheet"):  # arkusze wykresów i makr XLM bez komórek pomijamy
                sheets.append(XlsxSheet(el.get("name") or "", _resolve(base, target[0]),
                                        el.get("state", "visible") != "visible"))
    by_type = {kind.rsplit("/", 1)[-1]: path for path, kind in rels.values()}
    shared = _shared_strings(zf, _resolve(base, by_type["sharedStrings"])) if "sharedStrings" in by_type else []
    dates = _date_styles(zf, _resolve(base, by_type["styles"])) if "styles" in by_type else frozenset()
    return XlsxBook(zf, sheets, shared, dates, epoch)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class _part:
    """Część archiwum do strumieniowego czytania; z DTD — odmowa (encje to bomba albo wyciek)."""

    def __init__(self, zf: zipfile.ZipFile, path: str) -> None:
        self.f = zf.open(path)
        if b"<!DOCTYPE" in self.f.peek(4096)[:4096]:
            self.f.close()
            raise ValueError("DTD in part")

    def __enter__(self) -> IO[bytes]:
        return self.f

    def __exit__(self, *exc: object) -> None:
        self.f.close()


def _parse(zf: zipfile.ZipFile, path: str) -> Element:
    with _part(zf, path) as f:
        for _event, el in iterparse(f, events=("end",)):
            last = el
    return last


def _office_document(zf: zipfile.ZipFile) -> str:
    for path, kind in _relationships(zf, "_rels/.rels").values():
        if kind.endswith("/officeDocument"):
            return path.lstrip("/")
    return "xl/workbook.xml"


def _rels_path(part: str) -> str:
    folder, name = posixpath.split(part)
    return posixpath.join(folder, "_rels", name + ".rels")


def _relationships(zf: zipfile.ZipFile, path: str) -> dict[str, tuple[str, str]]:
    """Id → (cel, typ)."""
    try:
        zf.getinfo(path)
    except KeyError:
        return {}
    return {el.get("Id", ""): (el.get("Target", ""), el.get("Type", ""))
            for el in _parse(zf, path).iter() if _local(el.tag) == "Relationship"}


def _resolve(base: str, target: str) -> str:
    return target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base, target))


def _shared_strings(zf: zipfile.ZipFile, path: str) -> list[str]:
    out: list[str] = []
    with _part(zf, path) as f:
        for _event, el in iterparse(f, events=("end",)):
            if _local(el.tag) != "si":
                continue
            out.append(_text(el))
            el.clear()
    return out


def _text(el: Element) -> str:
    """Tekst `<si>` / `<is>`: `<t>` wprost albo w kawałkach `<r>`; wymowa (`<rPh>`) się nie liczy."""
    parts = []
    for child in el:
        name = _local(child.tag)
        if name == "t":
            parts.append(child.text or "")
        elif name == "r":
            parts.extend(t.text or "" for t in child if _local(t.tag) == "t")
    return "".join(parts)


def _date_styles(zf: zipfile.ZipFile, path: str) -> frozenset[int]:
    root = _parse(zf, path)
    custom: dict[int, str] = {}
    xfs: list[int] = []
    for el in root.iter():
        name = _local(el.tag)
        if name == "numFmt":
            custom[int(el.get("numFmtId", "-1"))] = el.get("formatCode", "")
        elif name == "cellXfs":
            xfs = [int(xf.get("numFmtId", "0")) for xf in el if _local(xf.tag) == "xf"]
    return frozenset(i for i, fmt in enumerate(xfs) if _is_date(fmt, custom.get(fmt)))


def _is_date(fmt: int, code: str | None) -> bool:
    if code is None:
        return fmt in _DATE_IDS
    bare = _FORMAT_NOISE.sub("", code)
    if "[h]" in code.lower() or "[m]" in code.lower() or "[s]" in code.lower():
        return False  # czas trwania (np. 30:15) — liczba godzin, nie data
    return re.search(r"[dmyhs]", bare, re.IGNORECASE) is not None and "general" not in bare.lower()


def _column(ref: str) -> int:
    letters = _COL.match(ref)
    n = 0
    for ch in letters.group() if letters else "":
        n = n * 26 + ord(ch) - 64
    return n - 1


def _sheet_rows(f: IO[bytes], max_cols: int) -> Iterator[tuple[int | None, list[tuple[str | None, str | None, str | None] | None]]]:
    """(numer wiersza od 0 albo None, komórki (typ, styl, wartość)) — komórki ustawione na swoich kolumnach."""
    # Komórki czytamy dopiero z gotowego <row>: pętla po zdarzeniach jest najdroższa, więc robi tylko porównanie tagu.
    names: dict[str, str] = {}

    for _event, el in iterparse(f, events=("end",)):
        tag = el.tag
        name = names.get(tag)
        if name is None:
            name = names[tag] = _local(tag)
        if name != "row":
            continue
        cells: list[tuple[str | None, str | None, str | None] | None] = []
        for c in el:
            if names.get(c.tag) != "c" and _local(c.tag) != "c":
                continue
            ref = c.get("r")
            # komórka „cofnięta” (plik niezgodny ze specyfikacją) idzie na koniec wiersza
            col = max(_column(ref) if ref else len(cells), len(cells))
            if col > max_cols:  # dalsze kolumny: wiersz o jedną dłuższy niż limit mówi o obcięciu
                cells.extend([None] * (max_cols + 1 - len(cells)))
                break
            value = None
            for child in c:
                part = names.get(child.tag) or _local(child.tag)
                if part == "v":
                    value = child.text
                elif part == "is":
                    value = _text(child)
            if col > len(cells):
                cells.extend([None] * (col - len(cells)))
            cells.append((c.get("t"), c.get("s"), value))
        r = el.get("r")
        yield (int(r) - 1 if r and r.isdigit() else None), cells
        el.clear()  # pusty <row> zostaje w drzewie (kilkadziesiąt bajtów), jego komórki nie

