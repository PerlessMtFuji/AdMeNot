"""Pliki protokołu (spec §9.3): zlecenie z dziennika → reports\\ZS-….html i .pdf. Wspólne dla CLI i GUI."""

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
from admenot.engine.settings import load_service


@dataclass(frozen=True)
class ReportFiles:
    html: Path
    pdf: Path | None  # None: tylko HTML (na życzenie albo po błędzie PDF)
    pdf_error: str | None = None  # PdfError.key: no_browser | timeout | failed | locked


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
        protocol = build_protocol(journal, order.id, lang)
    html = render_html(protocol, load_service(), now())
    target = out.with_suffix(".pdf") if out else reports_dir() / f"{report_stem(order.number)}.pdf"
    html_path = target.with_suffix(".html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, "utf-8")  # OSError leci do wołającego
    if not pdf:
        return ReportFiles(html_path, None)
    try:
        html_to_pdf(html_path, target)
    except PdfError as exc:
        return ReportFiles(html_path, None, exc.key)
    return ReportFiles(html_path, target)
