"""Pliki protokołu (spec §9.3): zlecenie z dziennika → reports\\ZS-….html i .pdf. Wspólne dla CLI i GUI.

PDF trafia do folderu z ustawienia `report_pdf_dir`, gdy jest ustawiony (archiwum serwisu — usunięcie
zlecenia go nie sprząta); HTML roboczy zostaje zawsze w `reports_dir()`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from admenot.engine.journal.db import Journal
from admenot.engine.paths import journal_path, reports_dir
from admenot.engine.report.model import build_protocol
from admenot.engine.report.pdf import PdfError, html_to_pdf
from admenot.engine.report.render import render_html
from admenot.engine.report.transfer_model import build_transfer_protocol
from admenot.engine.report.transfer_render import render_transfer_html
from admenot.engine.settings import load_service, load_settings


@dataclass(frozen=True)
class ReportFiles:
    html: Path
    pdf: Path | None  # None: tylko HTML (na życzenie albo po błędzie PDF)
    pdf_error: str | None = None  # PdfError.key: no_browser | timeout | failed | locked | folder
    pdf_target: Path | None = None  # gdzie miał trafić PDF (także po błędzie: „locked”, „folder”)


class UnknownOrder(LookupError):
    """W dzienniku nie ma zlecenia o tym numerze."""


def report_stem(number: str) -> str:
    return number.replace("/", "-")


def write_report(number: str, lang: str, *, out: Path | None = None, pdf: bool = True,
                 now: Callable[[], datetime] = datetime.now) -> ReportFiles:
    with Journal(journal_path()) as journal:
        order = journal.order_by_number(number)
        if order is None:
            raise UnknownOrder(number)
        if order.kind == "transfer":
            moment = now()
            html = render_transfer_html(build_transfer_protocol(journal, order.id, lang, moment),
                                        load_service(), moment)
        else:
            html = render_html(build_protocol(journal, order.id, lang), load_service(), now())
    stem = report_stem(order.number)
    if out:
        html_path, target = out.with_suffix(".html"), out.with_suffix(".pdf")
    else:
        custom = load_settings().report_pdf_dir
        html_path = reports_dir() / f"{stem}.html"
        target = (Path(custom) if custom else reports_dir()) / f"{stem}.pdf"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, "utf-8")  # OSError leci do wołającego
    if not pdf:
        return ReportFiles(html_path, None)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:  # wybrany folder niedostępny (dysk sieciowy, odłączony pendrive, brak praw)
        return ReportFiles(html_path, None, "folder", target)
    try:
        html_to_pdf(html_path, target)
    except PdfError as exc:
        return ReportFiles(html_path, None, exc.key, target)
    return ReportFiles(html_path, target, None, target)
