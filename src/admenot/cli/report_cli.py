"""Polecenia CLI protokołu (spec §9.3): service | report. Oba działają bez telefonu."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from admenot.engine.report.files import UnknownOrder, write_report
from admenot.engine.settings import LogoError, ServiceInfo, check_logo, load_service, save_service

TEXTS: dict[str, dict[str, str]] = {
    "pl": {
        "service_empty": "Brak danych serwisu. Ustaw je: admenot service --name \"…\" "
                         "--address \"…\" --phone \"…\" --logo logo.png",
        "service": "Serwis: {name}\nAdres: {address}\nTelefon: {phone}\nLogo: {logo}",
        "logo_missing": "Nie ma pliku {path}.",
        "logo_type": "Logo musi być plikiem PNG, JPG, WebP albo SVG: {path}",
        "logo_size": "Logo jest za duże (limit 1 MB): {path}",
        "saved": "Protokół zapisany: {path}",
        "saved_html": "Protokół (HTML) zapisany: {path}",
        "unknown_order": "Nie znaleziono zlecenia {number}.",
        "write_failed": "Nie można zapisać protokołu w {path}: {error}",
        "pdf_no_browser": "Nie znaleziono przeglądarki Microsoft Edge, która tworzy PDF. "
                          "Otwórz protokół HTML i wydrukuj go do PDF: {html}",
        "pdf_timeout": "Tworzenie PDF trwało zbyt długo. Protokół HTML: {html}",
        "pdf_failed": "Nie udało się utworzyć PDF. Protokół HTML: {html}",
        "pdf_locked": "Plik {pdf} jest otwarty w innym programie — zamknij go i spróbuj "
                      "ponownie. Protokół HTML: {html}",
    },
    "en": {
        "service_empty": "No service details. Set them: admenot service --name \"…\" "
                         "--address \"…\" --phone \"…\" --logo logo.png",
        "service": "Service: {name}\nAddress: {address}\nPhone: {phone}\nLogo: {logo}",
        "logo_missing": "File {path} does not exist.",
        "logo_type": "The logo must be a PNG, JPG, WebP or SVG file: {path}",
        "logo_size": "The logo is too large (1 MB limit): {path}",
        "saved": "Report saved: {path}",
        "saved_html": "Report (HTML) saved: {path}",
        "unknown_order": "Order {number} not found.",
        "write_failed": "Cannot save the report to {path}: {error}",
        "pdf_no_browser": "Microsoft Edge, which creates the PDF, was not found. "
                          "Open the HTML report and print it to PDF: {html}",
        "pdf_timeout": "Creating the PDF took too long. HTML report: {html}",
        "pdf_failed": "Could not create the PDF. HTML report: {html}",
        "pdf_locked": "File {pdf} is open in another program — close it and try again. "
                      "HTML report: {html}",
    },
}


def _m(lang: str, key: str, **kw: Any) -> str:
    return TEXTS[lang][key].format(**kw)


def _print_service(info: ServiceInfo, lang: str) -> None:
    if info == ServiceInfo():
        print(_m(lang, "service_empty"))
        return
    print(_m(lang, "service", name=info.name or "—", address=info.address or "—",
             phone=info.phone or "—", logo=info.logo or "—"))


def cmd_service(args: argparse.Namespace, lang: str) -> int:
    info = load_service()
    changes: dict[str, Any] = {key: getattr(args, key).strip() or None
                               for key in ("name", "address", "phone")
                               if getattr(args, key) is not None}
    if args.logo is not None:
        try:
            changes["logo"] = check_logo(Path(args.logo))
        except LogoError as exc:
            print(_m(lang, f"logo_{exc.key}", path=args.logo), file=sys.stderr)
            return 2
    if args.clear_logo:
        changes["logo"] = None
    if changes:
        info = replace(info, **changes)
        save_service(info)
    _print_service(info, lang)
    return 0


def cmd_report(args: argparse.Namespace, lang: str) -> int:
    out = Path(args.out) if args.out else None
    try:
        files = write_report(args.order, lang, out=out, pdf=not args.html)
    except UnknownOrder:
        print(_m(lang, "unknown_order", number=args.order), file=sys.stderr)
        return 2
    except OSError as exc:
        print(_m(lang, "write_failed", path=exc.filename or out or "", error=exc), file=sys.stderr)
        return 6
    if args.html:
        print(_m(lang, "saved_html", path=files.html))
        return 0
    if files.pdf is None:
        pdf = files.html.with_suffix(".pdf")
        print(_m(lang, f"pdf_{files.pdf_error}", pdf=pdf, html=files.html), file=sys.stderr)
        return 6
    print(_m(lang, "saved", path=files.pdf))
    return 0
