"""Czytnik XLSX: części pliku pisane ręcznie — przypadki, których openpyxl sam nie zapisze."""

from __future__ import annotations

import io
import zipfile

import pytest

from admenot.engine.explorer.sheets import MAX_COLS, SheetError, read_book

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' \
     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _book(sheet_xml: str, *, shared: str | None = None, styles: str | None = None, date1904: bool = False,
          chart: bool = False) -> bytes:
    rels = [f'<Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>']
    sheets = '<sheet name="Dane" sheetId="1" r:id="rId1"/>'
    if chart:
        rels.append(f'<Relationship Id="rId9" Type="{REL}/chartsheet" Target="/xl/chartsheets/sheet1.xml"/>')
        sheets = '<sheet name="Wykres" sheetId="2" r:id="rId9"/>' + sheets
    if shared is not None:
        rels.append(f'<Relationship Id="rId2" Type="{REL}/sharedStrings" Target="sharedStrings.xml"/>')
    if styles is not None:
        rels.append(f'<Relationship Id="rId3" Type="{REL}/styles" Target="styles.xml"/>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("_rels/.rels", f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    f'<Relationship Id="r" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        zf.writestr("xl/workbook.xml", f'<workbook {NS}><workbookPr{" date1904=\"1\"" if date1904 else ""}/>'
                    f"<sheets>{sheets}</sheets></workbook>")
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    + "".join(rels) + "</Relationships>")
        zf.writestr("xl/worksheets/sheet1.xml", f"<worksheet {NS}><sheetData>{sheet_xml}</sheetData></worksheet>")
        if chart:
            zf.writestr("xl/chartsheets/sheet1.xml", f"<chartsheet {NS}/>")
        if shared is not None:
            zf.writestr("xl/sharedStrings.xml", f"<sst {NS}>{shared}</sst>")
        if styles is not None:
            zf.writestr("xl/styles.xml", f"<styleSheet {NS}>{styles}</styleSheet>")
    return out.getvalue()


def test_shared_rich_and_inline_strings_skip_phonetics():
    shared = ('<si><t>Łódź</t></si>'
              '<si><r><t>Gru</t></r><r><rPr><b/></rPr><t>ba </t></r><r><t>czcionka</t></r><rPh><t>x</t></rPh></si>')
    xml = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
           '<c r="C1" t="inlineStr"><is><t>wprost</t></is></c><c r="D1" t="str"><v>wynik</v></c>'
           '<c r="E1" t="e"><v>#DIV/0!</v></c><c r="F1" t="b"><v>0</v></c><c r="G1" t="s"><v>99</v></c></row>')
    book = read_book(_book(xml, shared=shared))
    assert book.sheets[0].rows == [["Łódź", "Gruba czcionka", "wprost", "wynik", "#DIV/0!", "FALSE"]]


def test_gaps_in_rows_and_columns_and_missing_refs():
    xml = ('<row r="2"><c r="C2"><v>1</v></c></row>'
           '<row><c><v>2</v></c><c><v>3</v></c></row>'  # bez r: kolejny wiersz, kolejne kolumny
           '<row r="5"><c r="B5"><v>4</v></c><c r="A5"><v>5</v></c></row>')  # cofnięta komórka idzie na koniec
    assert read_book(_book(xml)).sheets[0].rows == [[], ["", "", "1"], ["2", "3"], [], ["", "4", "5"]]


STYLES = ('<numFmts count="2"><numFmt numFmtId="164" formatCode="dd&quot;.&quot;mm&quot;.&quot;yyyy"/>'
          '<numFmt numFmtId="165" formatCode="[h]:mm"/><numFmt numFmtId="166" formatCode="0.00&quot; zł&quot;"/>'
          '</numFmts><cellXfs count="6"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/>'
          '<xf numFmtId="165"/><xf numFmtId="20"/><xf numFmtId="166"/></cellXfs>')


def test_dates_from_builtin_and_custom_formats_but_not_durations_or_money():
    xml = ('<row r="1"><c r="A1"><v>45352</v></c><c r="B1" s="1"><v>45352</v></c><c r="C1" s="2"><v>45352.5</v></c>'
           '<c r="D1" s="3"><v>1.25</v></c><c r="E1" s="4"><v>0.6041666666666666</v></c>'
           '<c r="F1" s="5"><v>12.5</v></c><c r="G1" t="d"><v>2024-03-01T10:00:00</v></c></row>')
    row = read_book(_book(xml, styles=STYLES)).sheets[0].rows[0]
    assert row == ["45352", "2024-03-01", "2024-03-01 12:00", "1.25", "14:30:00", "12.5", "2024-03-01T10:00:00"]


def test_1904_date_system():
    xml = '<row r="1"><c r="A1" s="1"><v>0</v></c><c r="B1" s="1"><v>1461</v></c></row>'
    assert read_book(_book(xml, styles=STYLES, date1904=True)).sheets[0].rows == [["00:00:00", "1908-01-01"]]


def test_chart_sheets_are_skipped():
    book = read_book(_book('<row r="1"><c r="A1"><v>1</v></c></row>', chart=True))
    assert book.names == ["Dane"] and book.sheets[0].rows == [["1"]]


def test_far_columns_mark_the_sheet_truncated():
    xml = f'<row r="1"><c r="A1"><v>1</v></c><c r="{"ZZZ"}1"><v>2</v></c></row>'
    sheet = read_book(_book(xml)).sheets[0]
    assert sheet.rows == [["1"]] and sheet.truncated and MAX_COLS < 18_000


def test_dtd_in_a_part_is_refused():
    bomb = ('<!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
            '<row r="1"><c r="A1" t="inlineStr"><is><t>&b;</t></is></c></row>')
    data = _book("")
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            body = src.read(item)
            if item.filename == "xl/worksheets/sheet1.xml":
                body = bomb.encode()
            dst.writestr(item, body)
    with pytest.raises(SheetError) as err:
        read_book(out.getvalue())
    assert err.value.kind == "unreadable"


def test_missing_workbook_part_is_unreadable():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("word/document.xml", "<w/>")  # DOCX przemianowany na .xlsx
    with pytest.raises(SheetError) as err:
        read_book(out.getvalue())
    assert err.value.kind == "unreadable"
