"""Model protokołu przeniesienia danych (spec przenoszenia §6.2): zlecenie z dziennika → kafelki,
aplikacje, informacje dla klienta.

Budowany wyłącznie z dziennika (migawka źródła + zapisany wynik wgrywania) — nigdy z katalogu kopii,
bo protokół ma działać także po usunięciu kopii. Mówi tylko to, co zapisano.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

from admenot.engine.journal.db import Journal
from admenot.engine.report.model import DeviceBlock
from admenot.engine.report.texts import TRANSFER_TEXTS

APPS_NAMED = 8  # tyle nazw zainstalowanych aplikacji w akapicie; reszta jako „i K innych”
Tone = Literal["ok", "warn", "bad"]
_DONE_ROWS = frozenset({"installed", "exists"})


@dataclass(frozen=True)
class Tile:
    key: str
    count: str
    state: str
    tone: Tone


@dataclass(frozen=True)
class TransferProtocol:
    number: str
    lang: str
    client: str | None
    received: datetime
    issued: datetime
    source: DeviceBlock
    target: DeviceBlock | None
    tone: Tone
    headline: str
    tiles: list[Tile]
    apps_installed: int
    apps_total: int
    apps_named: list[str]
    apps_more: int
    apps_problems: list[tuple[str, str]]
    apps_malicious_skipped: int
    whatsapp: Literal["restored", "on_phone", "none"]
    copy_until: date | None
    copy_deleted: date | None


def num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _device(info: dict[str, Any], serial: str | None) -> DeviceBlock:
    maker = (info.get("manufacturer") or "").strip()
    market = (info.get("market_name") or "").strip()
    model = (info.get("model") or "").strip()
    maker = maker.title() if maker.islower() else maker
    base = market or model
    name = base if not maker or base.lower().startswith(maker.lower()) else f"{maker} {base}".strip()
    return DeviceBlock(name or "—", model or None, info.get("android") or None, serial or info.get("serial") or "",
                       None, info.get("imei") or None)


def _of(t: dict[str, Any], done: int, total: int) -> str:
    return f"{num(done)} {t['of']} {num(total)}"


def _missing(t: dict[str, Any], key: str, total: int) -> Tile:
    return Tile(key, _of(t, 0, total), t["state"]["missing"], "bad")


def _tel_tile(t: dict[str, Any], key: str, kinds: tuple[str, ...], counts: dict[str, int],
              tel: dict[str, Any] | None) -> Tile | None:
    total = sum(counts.get(k, 0) for k in kinds)
    if not any(k in counts for k in kinds):
        return None
    results = [(tel or {}).get("kinds", {}).get(k) for k in kinds if counts.get(k, 0)]
    if tel is None or any(r is None for r in results):
        return _missing(t, key, total)
    done = sum(r["written"] + r["existed"] for r in results)
    synced = sum(r["skipped_synced"] + r["skipped_messenger"] for r in results)
    failed = sum(r["failed"] for r in results)
    manual = sum(r["manual"] for r in results)
    count = _of(t, done, total)
    st = t["state"]
    if manual:
        return Tile(key, count, st["manual"], "warn")
    if failed:
        return Tile(key, count, st["failed"].format(n=failed), "warn")
    if done + synced < total:
        return Tile(key, count, st["remaining"].format(n=total - done - synced), "warn")
    if synced:
        return Tile(key, count, st["synced"].format(n=synced), "ok")
    return Tile(key, count, st["all"], "ok")


def _file_tile(t: dict[str, Any], key: str, groups: tuple[str, ...], counts: dict[str, int],
               files: dict[str, Any] | None, whatsapp_restored: bool) -> Tile | None:
    total = sum(counts.get(f"files_{g}", 0) for g in groups)
    if not total:
        return None
    if files is None:
        return _missing(t, key, total)
    per = [(files.get("groups") or {}).get(g) or {} for g in groups]
    done = sum(g.get("done", 0) + g.get("exists", 0) for g in per)
    failed = sum(g.get("failed", 0) for g in per)
    mal = files.get("apk_skipped", 0) if key == "downloads" else 0
    sus = files.get("apk_suspicious_skipped", 0) if key == "downloads" else 0
    count = _of(t, done, total)
    st = t["state"]
    gap = total - done
    if done == 0 and not mal and not sus and not failed:
        return _missing(t, key, total)
    if gap > 0:
        if not failed and mal and gap <= mal:
            return Tile(key, count, st["malicious"].format(n=mal), "warn")
        if not failed and not mal and sus and gap <= sus:
            return Tile(key, count, st["suspicious"].format(n=sus), "warn")
        return Tile(key, count, (st["failed"] if failed else st["remaining"]).format(n=failed or gap), "warn")
    if key == "whatsapp":
        return Tile(key, count, st["wa_restored"] if whatsapp_restored else st["wa_pending"], "ok")
    return Tile(key, count, st["all_checked"] if files.get("hashed") else st["all"], "ok")


def _tiles(t: dict[str, Any], source: dict[str, Any], result: dict[str, Any] | None,
           whatsapp_restored: bool) -> list[Tile]:
    counts = source.get("counts") or {}
    groups = set(source.get("selection_groups") or ())
    files = (result or {}).get("files")
    tel = (result or {}).get("tel")
    tiles: list[Tile | None] = []
    if "contacts_messages" in groups:
        tiles += [_tel_tile(t, "contacts", ("contacts",), counts, tel),
                  _tel_tile(t, "sms", ("sms", "mms"), counts, tel),
                  _tel_tile(t, "calls", ("calls",), counts, tel)]
    if "files" in groups:
        tiles += [_file_tile(t, key, members, counts, files, whatsapp_restored)
                  for key, members in (("photos", ("photos", "videos")), ("downloads", ("downloads",)),
                                       ("whatsapp", ("whatsapp",)), ("others", ("others",)))]
    return [x for x in tiles if x is not None]


def _reason(t: dict[str, Any], row: dict[str, Any]) -> str:
    reason = row.get("reason")
    reasons = t["reasons"]
    if row.get("status") == "pending" or not reason:
        return reasons["pending"]
    return reasons[reason] if reason in reasons and reason != "unknown" else reasons["unknown"].format(code=reason)


def _apps(t: dict[str, Any], source: dict[str, Any], result: dict[str, Any] | None
          ) -> tuple[int, int, list[str], int, list[tuple[str, str]], bool]:
    """(zainstalowane, wybrane, nazwy, ile jeszcze nazw, problemy, wgrywanie nie dotarło do aplikacji)."""
    apps = (result or {}).get("apps")
    if apps is None:
        total = (source.get("counts") or {}).get("apps", 0) if "apps" in (source.get("selection_groups") or ()) else 0
        return 0, total, [], 0, [], total > 0
    rows = apps.get("rows") or []
    ok_rows, problems = [], []
    for r in rows:
        name = r.get("label") or r.get("package") or "?"
        if r.get("status") in _DONE_ROWS or (r.get("status") == "skipped" and r.get("reason") == "installed"):
            ok_rows.append(name)
        else:
            problems.append((name, _reason(t, r)))
    names = sorted(ok_rows, key=str.casefold)
    return len(ok_rows), len(rows), names[:APPS_NAMED], max(0, len(names) - APPS_NAMED), problems, False


def _headline(t: dict[str, Any], tone: Tone, has_result: bool, app_problems: int, data_warn: bool,
              apps_missing: bool) -> str:
    h = t["headline"]
    if tone == "bad":
        return h["bad_partial"] if has_result else h["bad_none"]
    if tone == "ok":
        return h["done"]
    parts = [h["warn_data"] if data_warn else h["done"]]
    if apps_missing:
        parts.append(t["not_restored_apps"])
    if app_problems:
        form = "apps_one" if app_problems == 1 else (
            "apps_few" if app_problems % 10 in (2, 3, 4) and app_problems % 100 not in (12, 13, 14)
            else "apps_many")
        parts.append(h[form].format(n=app_problems))
    return " ".join(parts)


def build_transfer_protocol(journal: Journal, order_id: int, lang: str, now: datetime) -> TransferProtocol:
    t = TRANSFER_TEXTS[lang]
    order = journal.order(order_id)
    rec = journal.transfer(order_id)
    result = rec.result
    tiles = _tiles(t, rec.source, result, rec.whatsapp_restored)
    installed, total, named, more, problems, apps_missing = _apps(t, rec.source, result)

    finished = (order.status == "done" and result is not None and result.get("status") == "done"
                and not result.get("tel_error") and not result.get("apps_error"))
    data_warn = any(x.tone != "ok" for x in tiles)
    if not finished or any(x.tone == "bad" for x in tiles):
        tone: Tone = "bad"
    else:
        tone = "warn" if data_warn or apps_missing or problems else "ok"
    headline = _headline(t, tone, result is not None, len(problems), data_warn, apps_missing)

    wa_selected = (rec.source.get("counts") or {}).get("files_whatsapp", 0) > 0
    wa_tile = next((x for x in tiles if x.key == "whatsapp"), None)
    if rec.whatsapp_restored and wa_selected:
        whatsapp: Literal["restored", "on_phone", "none"] = "restored"
    elif wa_selected and wa_tile is not None and wa_tile.tone == "ok":
        whatsapp = "on_phone"
    else:
        whatsapp = "none"

    return TransferProtocol(
        number=order.number, lang=lang, client=order.client_name, received=rec.received_at, issued=now,
        source=_device(rec.source, rec.source.get("serial") or order.device_serial),
        target=_device(rec.target, rec.target_serial) if rec.target else None,
        tone=tone, headline=headline, tiles=tiles, apps_installed=installed, apps_total=total,
        apps_named=named, apps_more=more, apps_problems=problems,
        apps_malicious_skipped=int((rec.source.get("counts") or {}).get("apps_malicious", 0)),
        whatsapp=whatsapp,
        copy_until=None if rec.copy_deleted_at or rec.copy_expires is None else rec.copy_expires.date(),
        copy_deleted=rec.copy_deleted_at.date() if rec.copy_deleted_at else None)
