"""Arkusze do podglądu: XLSX/XLSM, XLS, CSV/TSV — wartości, limity, pliki wrogie i zabezpieczone."""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from admenot.engine.explorer import sheets
from admenot.engine.explorer.sheets import SheetError, read_book

FIXTURES = Path(__file__).parent / "fixtures" / "sheets"


def _xlsx(build) -> bytes:
    wb = Workbook()
    build(wb)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _invoices(wb: Workbook) -> None:
    ws = wb.active
    ws.title = "Faktury"
    ws.append(["Nr", "Klient", "Kwota", "Data", "Zapłacono", "Godzina"])
    ws.append(["F/1", "Łódź Sp. z o.o.", 1234.5, dt.datetime(2024, 3, 1), True, dt.datetime(2024, 3, 1, 14, 30)])
    ws.append(["F/2", None, 10.0, None, False])
    ws["H5"] = "=SUM(C2:C3)"  # bez zapisanego wyniku: openpyxl nie liczy formuł, wartość pusta
    other = wb.create_sheet("Ukryty")
    other.sheet_state = "hidden"
    other["B3"] = "zażółć"


def test_xlsx_values_as_text_and_sheets():
    book = read_book(_xlsx(_invoices))
    assert book.names == ["Faktury", "Ukryty"]
    first, hidden = book.sheets
    assert first.rows[:3] == [
        ["Nr", "Klient", "Kwota", "Data", "Zapłacono", "Godzina"],
        ["F/1", "Łódź Sp. z o.o.", "1234.5", "2024-03-01", "TRUE", "2024-03-01 14:30"],
        ["F/2", "", "10", "", "FALSE"],
    ]
    assert not first.truncated and not first.hidden
    assert hidden.hidden and hidden.rows == [[], [], ["", "zażółć"]]


def test_xlsm_from_excel_keeps_formula_results():
    book = read_book((FIXTURES / "makro.xlsm").read_bytes())  # zapisany przez Excel: wynik formuły w pliku
    assert book.names == ["Dane"] and book.sheets[0].rows == [["makro", "5"]]


def test_head_reads_first_sheet_only_but_names_all():
    book = read_book(_xlsx(_invoices), rows=2, cols=3, first_only=True)
    assert book.names == ["Faktury", "Ukryty"] and len(book.sheets) == 1
    assert book.sheets[0].rows == [["Nr", "Klient", "Kwota"], ["F/1", "Łódź Sp. z o.o.", "1234.5"]]
    assert book.sheets[0].truncated


def test_xls():
    book = read_book((FIXTURES / "faktury.xls").read_bytes())
    assert book.names == ["Faktury", "Notatki"]
    assert book.sheets[0].rows == [
        ["Nr", "Klient", "Kwota", "Data", "Zapłacono"],
        ["F/1", "Łódź Sp. z o.o.", "1234.5", "2024-03-01", "TRUE"],
        ["F/2", "Gęś", "10", "2024-03-02", "FALSE"],
    ]
    assert book.sheets[1].rows == [["zażółć"], [], ["", "po pustym wierszu"]]


@pytest.mark.parametrize(("body", "delimiter"), [
    ("a;b;c\n1;2,5;3\n", ";"),
    ("a,b,c\n1,\"2,5\",3\n", ","),
    ("a\tb\tc\n1\t2,5\t3\n", "\t"),
])
def test_csv_delimiter_is_detected(body, delimiter):
    book = read_book(body.encode())
    assert book.delimiter == delimiter and book.names == [""]
    assert book.sheets[0].rows == [["a", "b", "c"], ["1", "2,5", "3"]]


def test_csv_cp1250_and_quoted_newlines():
    book = read_book("Klient;Uwagi\r\nŁódź;\"dwie\r\nlinie\"\r\n".encode("cp1250"))
    assert book.encoding == "cp1250"
    assert book.sheets[0].rows == [["Klient", "Uwagi"], ["Łódź", "dwie\r\nlinie"]]


def test_bank_xls_that_is_tab_text():
    book = read_book("Data\tKwota\n2024-01-01\t-12,50\n".encode("cp1250"))
    assert book.sheets[0].rows[1] == ["2024-01-01", "-12,50"]


@pytest.mark.parametrize("data", [b"<html><table><tr><td>1</td></tr></table></html>", b"PK\x03\x04garbage",
                                  sheets._OLE + b"\x00" * 600, b"\x00\x01\x02binary"])
def test_unreadable(data):
    with pytest.raises(SheetError) as err:
        read_book(data)
    assert err.value.kind == "unreadable"


@pytest.mark.parametrize("name", ["haslo.xlsx", "haslo.xls"])
def test_password_protected_files_from_excel(name):
    with pytest.raises(SheetError) as err:
        read_book((FIXTURES / name).read_bytes())
    assert err.value.kind == "encrypted"


def test_password_protected_xlsx_is_encrypted():
    # XLSX z hasłem to kontener OLE ze strumieniem „EncryptedPackage” (nazwy wpisów w UTF-16).
    data = sheets._OLE + b"\x00" * 500 + "EncryptedPackage".encode("utf-16-le") + b"\x00" * 100
    with pytest.raises(SheetError) as err:
        read_book(data)
    assert err.value.kind == "encrypted"


def test_zip_bomb_is_refused(monkeypatch):
    monkeypatch.setattr(sheets, "_UNZIPPED", 1000)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/sharedStrings.xml", "a" * 5000)
    with pytest.raises(SheetError) as err:
        read_book(out.getvalue())
    assert err.value.kind == "too_big"


def test_cell_limits_cut_the_sheet_and_the_book(monkeypatch):
    monkeypatch.setattr(sheets, "SHEET_CELLS", 10)
    monkeypatch.setattr(sheets, "BOOK_CELLS", 14)
    body = "\n".join("a;b;c" for _ in range(10)).encode()
    first = read_book(body).sheets[0]
    assert len(first.rows) == 3 and first.truncated

    def two(wb: Workbook) -> None:
        for name in ("A", "B"):
            ws = wb.create_sheet(name)
            for _ in range(5):
                ws.append([1, 2, 3])
        del wb["Sheet"]

    a, b = read_book(_xlsx(two)).sheets
    assert (len(a.rows), a.truncated) == (3, True)  # 9 komórek z 10 na arkusz
    assert (len(b.rows), b.truncated) == (1, True)  # zostało 5 z 14 na plik


def test_columns_are_capped(monkeypatch):
    monkeypatch.setattr(sheets, "MAX_COLS", 3)
    sheet = read_book(b"1,2,3,4,5\n6,7\n").sheets[0]
    assert sheet.rows == [["1", "2", "3"], ["6", "7"]] and sheet.truncated


def test_long_run_of_empty_rows_ends_the_sheet(monkeypatch):
    monkeypatch.setattr(sheets, "_EMPTY_RUN", 3)
    sheet = read_book(b"a\n\n\n\n\nb\n").sheets[0]
    assert sheet.rows == [["a"]]


def test_trailing_empty_rows_are_dropped():
    assert read_book(b"a,b\n,\n\n").sheets[0].rows == [["a", "b"]]
