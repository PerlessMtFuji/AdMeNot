"""Protokół przeniesienia → samodzielny HTML (Jinja2, wariant „Kafelki”). Jak `render.py`: bez zależności
od plików obok i sieci; ikony to inline SVG."""

from __future__ import annotations

from datetime import datetime

from admenot import __version__
from admenot.engine.report.render import _env, _footer, data_uri
from admenot.engine.report.texts import TRANSFER_TEXTS
from admenot.engine.report.transfer_model import TransferProtocol
from admenot.engine.settings import ServiceInfo

TEMPLATE = "transfer.html.j2"
MAX_PROBLEMS = 6  # dalsze problemy zlicza linia „i K innych” — strona zostaje jedna


def render_transfer_html(p: TransferProtocol, service: ServiceInfo, generated_at: datetime) -> str:
    t = TRANSFER_TEXTS[p.lang]
    fmt = t["date_format"]
    tiles = []
    for tile in p.tiles:
        big, _, rest = tile.count.partition(f" {t['of']} ")
        tiles.append({"key": tile.key, "name": t["tiles"][tile.key], "big": big,
                      "rest": f"{t['of']} {rest}" if rest else "", "state": tile.state, "tone": tile.tone})
    problems = p.apps_problems[:MAX_PROBLEMS]
    info = [t["info_login"] + " " + t["info_bank"]]
    if p.whatsapp == "on_phone":
        info.append(t["info_whatsapp"])
    return _env().get_template(TEMPLATE).render(
        p=p, t=t, service=service, footer=_footer(service.footer),
        logo=data_uri(service.logo) if service.logo else None,
        received=p.received.strftime(fmt), issued=p.issued.strftime(fmt),
        tiles=tiles, problems=problems, problems_more=len(p.apps_problems) - len(problems),
        percent=round(100 * p.apps_installed / p.apps_total) if p.apps_total else 0,
        names=", ".join(p.apps_named) + ("" if not p.apps_more else
                                         f" {t['names_more'].format(n=p.apps_more)}"),
        malicious=t["malicious_apps"].format(n=p.apps_malicious_skipped) if p.apps_malicious_skipped else None,
        info=info,
        copy_line=(t["copy_deleted"].format(date=p.copy_deleted.strftime(fmt)) if p.copy_deleted
                   else t["copy_until"].format(date=p.copy_until.strftime(fmt)) if p.copy_until else None),
        generated=t["generated"].format(version=__version__, date=generated_at.strftime(t["datetime_format"])),
    )
