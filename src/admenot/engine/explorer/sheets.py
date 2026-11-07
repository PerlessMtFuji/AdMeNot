"""Arkusze do podglądu: XLSX/XLSM (własny czytnik `xlsx.py`), XLS (xlrd), CSV/TSV — tylko wartości komórek jako tekst.

Rodzaj pliku rozpoznaje zawartość, nie rozszerzenie: „.xls” z banku bywa zwykłym tekstem z tabulatorami, a „.xlsx”
zabezpieczony hasłem to kontener OLE. Limity trzymają okno przy życiu: plik z telefonu może być wrogi (bomba ZIP,
milion pustych wierszy z formatowaniem)."""

from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from admenot.engine.explorer.textview import decode_text
from admenot.engine.explorer.xlsx import open_xlsx

__all__ = ["HEAD_BYTES", "SHEET_BYTES", "SHEET_EXTS", "Book", "Sheet", "SheetError", "read_book"]

SHEET_EXTS = frozenset({"xlsx", "xlsm", "xls", "csv", "tsv"})
SHEET_BYTES = 40 * 1024 * 1024  # większego pliku nie czytamy w całości do pamięci
HEAD_BYTES = 8 * 1024 * 1024  # dymek przy najechaniu: XLSX trzeba pobrać cały, więc tylko mniejsze
SHEET_CELLS = 150_000  # komórek z jednego arkusza (z pustymi w środku wiersza)
BOOK_CELLS = 500_000  # komórek z całego pliku — więcej mostek do okna przenosi sekundami
MAX_COLS = 702  # do kolumny ZZ
_EMPTY_RUN = 5_000  # tyle pustych wierszy z rzędu kończy arkusz (formatowanie do końca arkusza)
_UNZIPPED = 512 * 1024 * 1024  # bomba ZIP: tyle najwyżej po rozpakowaniu
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_DELIMITERS = ";,\t|"
_ENCRYPTED_XLSX = "EncryptedPackage".encode("utf-16-le")  # nazwy wpisów OLE są w UTF-16


class SheetError(Exception):
    """`kind`: `too_big` | `encrypted` | `unreadable`."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass
class Sheet:
    name: str
    rows: list[list[str]] = field(default_factory=list)
    truncated: bool = False  # nie cały arkusz (limit wierszy, kolumn albo komórek)
    hidden: bool = False


@dataclass
class Book:
    sheets: list[Sheet]
    names: list[str]  # wszystkie arkusze, także te niewczytane (dymek czyta tylko pierwszy)
    delimiter: str | None = None  # CSV: wykryty separator
    encoding: str | None = None  # CSV: kodowanie


def read_book(data: bytes, *, rows: int | None = None, cols: int | None = None, first_only: bool = False) -> Book:
    """Arkusze z bajtów pliku. `rows`/`cols` — najwyżej tyle z arkusza (dymek), `first_only` — tylko pierwszy."""
    limit = _Limit(rows, min(cols or MAX_COLS, MAX_COLS), BOOK_CELLS)
    try:
        if data.startswith(b"PK"):
            return _xlsx(data, limit, first_only)
        if data.startswith(_OLE):
            return _xls(data, limit, first_only)
        return _text(data, limit)
    except SheetError:
        raise
    except Exception as exc:  # parser na uszkodzonym albo nietypowym pliku: każdy błąd to „nie do odczytania”
        raise SheetError("unreadable") from exc


@dataclass
class _Limit:
    rows: int | None
    cols: int
    left: int

    def take(self, name: str, source: Iterable[Iterable[Any]], cell: Any, hidden: bool = False) -> Sheet:
        """Wiersze arkusza jako tekst: bez pustych na końcu wiersza i arkusza, w granicach limitów."""
        sheet = Sheet(name, hidden=hidden)
        budget = min(SHEET_CELLS, self.left)
        used = empty = 0
        pending: list[list[str]] = []  # puste wiersze, które mogą jeszcze stać przed danymi
        for raw in source:
            if self.rows is not None and len(sheet.rows) + len(pending) >= self.rows:
                sheet.truncated = True
                break
            values = [cell(v) for _, v in zip(range(self.cols + 1), raw, strict=False)]
            if len(values) > self.cols:
                sheet.truncated = True
                values = values[: self.cols]
            while values and values[-1] == "":
                values.pop()
            if not values:
                empty += 1
                if empty >= _EMPTY_RUN:
                    break
                pending.append([])
                continue
            if used + len(values) > budget:
                sheet.truncated = True
                break
            empty = 0
            sheet.rows.extend(pending)
            pending.clear()
            sheet.rows.append(values)
            used += len(values)
        self.left -= used
        return sheet


def _number(v: float) -> str:
    if v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.15g}"


def _when(v: dt.datetime | dt.date | dt.time) -> str:
    if isinstance(v, dt.datetime):
        if v.time() == dt.time():
            return v.date().isoformat()
        return v.isoformat(sep=" ", timespec="seconds" if v.second or v.microsecond else "minutes")
    if isinstance(v, dt.time):
        return v.isoformat(timespec="seconds")
    return v.isoformat()


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return _number(v)
    if isinstance(v, dt.timedelta):
        return str(v)
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return _when(v)
    return str(v)


def _xlsx(data: bytes, limit: _Limit, first_only: bool) -> Book:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if sum(i.file_size for i in zf.infolist()) > _UNZIPPED:
            raise SheetError("too_big")
        wb = open_xlsx(zf)
        out = [limit.take(s.name, wb.rows(s, limit.cols), _cell, hidden=s.hidden)
               for s in (wb.sheets[:1] if first_only else wb.sheets)]
    return Book(out, [s.name for s in wb.sheets])


def _xls(data: bytes, limit: _Limit, first_only: bool) -> Book:
    import xlrd

    if _ENCRYPTED_XLSX in data:  # XLSX z hasłem: kontener OLE ze strumieniem „EncryptedPackage”
        raise SheetError("encrypted")
    try:
        wb = xlrd.open_workbook(file_contents=data, on_demand=True, logfile=io.StringIO())
    except xlrd.XLRDError as exc:
        if "encrypt" in str(exc).lower():  # XLS z hasłem (rekord FILEPASS)
            raise SheetError("encrypted") from exc
        raise
    try:
        def cell(c: Any) -> str:
            if c.ctype == xlrd.XL_CELL_DATE:
                try:
                    return _when(xlrd.xldate_as_datetime(c.value, wb.datemode))
                except (ValueError, OverflowError, xlrd.xldate.XLDateError):
                    return _number(c.value)
            if c.ctype == xlrd.XL_CELL_BOOLEAN:
                return _cell(bool(c.value))
            if c.ctype == xlrd.XL_CELL_ERROR:
                return xlrd.error_text_from_code.get(c.value, "#ERR")
            return _cell(c.value) if c.ctype != xlrd.XL_CELL_EMPTY else ""

        names = wb.sheet_names()
        out = []
        for i in range(1 if first_only else wb.nsheets):
            sh = wb.sheet_by_index(i)
            out.append(limit.take(sh.name, _xls_rows(sh), cell, hidden=sh.visibility != 0))
            wb.unload_sheet(i)
    finally:
        wb.release_resources()
    return Book(out, names)


def _xls_rows(sh: Any) -> Iterator[list[Any]]:
    for r in range(sh.nrows):
        yield sh.row(r)


def _text(data: bytes, limit: _Limit) -> Book:
    if len(data) > SHEET_BYTES:
        raise SheetError("too_big")
    text, encoding = decode_text(data)
    head = text.lstrip()[:1]
    if head == "<" or "\x00" in text[:4096]:  # HTML „xls” z banku albo plik binarny
        raise SheetError("unreadable")
    delimiter = _sniff(text[:65536])
    rows = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return Book([limit.take("", rows, _cell)], [""], delimiter=delimiter, encoding=encoding)


def _sniff(sample: str) -> str:
    """Separator: ten, który daje w pierwszych wierszach tę samą, największą liczbę pól."""
    lines = [ln for ln in sample.splitlines()[:20] if ln.strip()]
    if not lines:
        return ","
    best, score = ",", (0, 0)
    for d in _DELIMITERS:
        counts = [len(next(csv.reader([ln], delimiter=d))) for ln in lines]
        steady = sum(c == counts[0] for c in counts)
        if counts[0] > 1 and (steady, counts[0]) > score:
            best, score = d, (steady, counts[0])
    return best
