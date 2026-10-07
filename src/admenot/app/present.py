"""Dane silnika → JSON dla UI w wybranym języku. Czyste funkcje, bez telefonu i bez okna.

Teksty z silnika (werdykty, opisy reguł, kroki, błędy) tłumaczymy tutaj; UI tłumaczy tylko
własne napisy.
"""

from __future__ import annotations

import base64
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from admenot.engine.actions.planner import Blocked, default_level
from admenot.engine.apk.analyze import clean_label, scope_notes
from admenot.engine.apk.cache import CacheUsage, Estimate
from admenot.engine.device.info import DeviceInfo
from admenot.engine.evidence import ladders
from admenot.engine.facts import AppFacts
from admenot.engine.journal.db import Action, Journal, Order
from admenot.engine.phones.provider import SILHOUETTE, PhoneMatch
from admenot.engine.report.model import device_block
from admenot.engine.rules.model import CATEGORIES, Finding
from admenot.engine.scoring import AppResult
from admenot.engine.session import ScanReport
from admenot.engine.texts import (
    TEXTS,
    capability_label,
    confidence_label,
    error_text,
    gap_label,
    level_label,
    order_status_label,
    reason_text,
    scope_label,
    step_label,
    verdict_label,
    warning_text,
)
from admenot.engine.workflow import OrderPlan, OrderResult

MAX_PROBLEMS = 3
_MIME = {".webp": "image/webp", ".svg": "image/svg+xml", ".png": "image/png",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def image_uri(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    mime = _MIME.get(path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


INSTALLER_NAMES: dict[str, str | dict[str, str]] = {
    "com.android.vending": {"pl": "Sklep Play", "en": "Play Store"},
    "com.android.chrome": "Chrome",
    "com.sec.android.app.sbrowser": "Samsung Internet",
    "org.mozilla.firefox": "Firefox",
    "com.apkpure.aegon": "APKPure",
    "com.google.android.packageinstaller": {"pl": "Instalator pakietów", "en": "Package installer"},
    "com.android.packageinstaller": {"pl": "Instalator pakietów", "en": "Package installer"},
}
SOURCE_TEXTS = {"pl": {"system": "systemowa", "unknown": "nieznane", "play": "Sklep Play"},
                "en": {"system": "system", "unknown": "unknown", "play": "Play Store"}}


def severity(weight: int) -> str:
    return "bad" if weight >= 20 else "warn" if weight >= 10 else "neutral"


def symptoms(findings: list[Finding], lang: str) -> list[dict[str, Any]]:
    """Jeden objaw na kategorię: zdania prostych opisów od najcięższej reguły, bez powtórzeń."""
    groups: dict[str, list[Finding]] = {}
    for f in findings:
        if f.category in CATEGORIES:
            groups.setdefault(f.category, []).append(f)
    ranked = []
    for category, items in groups.items():
        items = sorted(items, key=lambda f: -f.weight)
        text = " ".join(dict.fromkeys(f.text(lang) for f in items))
        ranked.append((-items[0].weight, CATEGORIES.index(category),
                       {"category": category, "severity": severity(items[0].weight), "text": text}))
    return [entry for *_, entry in sorted(ranked, key=lambda r: (r[0], r[1]))]


def source_view(facts: AppFacts, lang: str) -> dict[str, Any]:
    texts = SOURCE_TEXTS[lang]
    if facts.is_system:
        label = texts["system"]
    elif facts.installer is None:
        label = texts["unknown"]
    elif facts.from_play:
        label = texts["play"]
    else:
        name = INSTALLER_NAMES.get(facts.installer, facts.installer)
        label = name[lang] if isinstance(name, dict) else name
    days = None if facts.installed_days is None else round(facts.installed_days)
    return {"label": label, "days": days}


def app_name(facts: AppFacts | None, package: str) -> str:
    label, _ = clean_label(facts.label if facts else None)
    return label or package


def device_card(info: DeviceInfo, match: PhoneMatch | None) -> dict[str, Any]:
    if match is not None and match.phone is not None:
        name = match.phone.name
    else:
        name = info.market_name or f"{info.brand} {info.model}".strip() or info.serial
    return {
        "serial": info.serial, "name": name, "brand": info.brand,
        "manufacturer": info.manufacturer, "model": info.model, "market_name": info.market_name,
        "android": info.android_release, "sdk": info.sdk, "patch": info.security_patch,
        "uptime_s": info.uptime_s, "imei": info.imei,
        "match": ({"confidence": match.confidence, "step": match.step, "matched": match.matched}
                  if match is not None else None),
        "image": image_uri(match.image if match is not None else SILHOUETTE),
    }


def app_view(r: AppResult, lang: str) -> dict[str, Any]:
    findings = [
        {"rule_id": f.rule_id, "class": f.rule_class, "weight": f.weight,
         "text": f.text(lang), "text_expert": f.text(lang, expert=True),
         "evidence": plain(f.evidence), "category": f.category, "label": f.label_text(lang),
         "basis": f.basis, "source": f.source, "locations": list(f.locations)}
        for f in r.findings
    ]
    facts = r.facts
    label_key = "safe_incomplete" if r.verdict == "safe" and r.incomplete else r.verdict
    return {
        "package": facts.package, "name": app_name(facts, facts.package), "score": r.score,
        "verdict": r.verdict, "verdict_label": verdict_label(label_key, lang),
        "confidence": r.confidence, "confidence_label": confidence_label(r.confidence, lang),
        "gaps": [{"key": g, "label": gap_label(g, lang)} for g in sorted(facts.gaps)],
        "scope": [{"key": k, "label": scope_label(k, lang)} for k in scope_notes(facts)],
        "trusted": r.trusted, "incomplete": r.incomplete, "is_system": facts.is_system,
        "enabled": facts.enabled,
        "from_play": facts.from_play, "installer": facts.installer,
        "is_admin": facts.is_device_admin, "default_level": default_level(r),
        "problems": list(dict.fromkeys(f["text"] for f in findings))[:MAX_PROBLEMS],
        "findings": findings, "apk_error": facts.apk_error, "icon": facts.icon,
        "ad_sdks": sorted(facts.ad_sdks) if facts.ad_sdks is not None else None,
        "symptoms": symptoms(r.findings, lang), "source": source_view(facts, lang),
        "capabilities": [{"key": ld.capability, "label": capability_label(ld.capability, lang),
                          "levels": ld.levels} for ld in ladders(facts)],
    }


def scan_view(report: ScanReport, lang: str) -> dict[str, Any]:
    results = report.results
    statuses = list(report.collectors.values())
    verdicts = [r.verdict for r in results]
    return {
        "collectors": {"ok": sum(s.ok for s in statuses), "total": len(statuses),
                       "failed": [{"name": s.name, "error": s.error} for s in statuses if not s.ok],
                       "partial": [{"name": s.name, "count": len(s.partial)}
                                   for s in statuses if s.ok and s.partial]},
        "low_behavior_data": report.low_behavior_data,
        "apk": plain(asdict(report.apk)) if report.apk else None,
        "apps": [app_view(r, lang) for r in results],
        "profiles": {"others": list(report.profiles.others) if report.profiles else [],
                     "known": bool(report.profiles and report.profiles.present is not None)},
        "usage_window_h": report.usage_window_h,
        "counts": {
            "malicious": verdicts.count("malicious"), "suspicious": verdicts.count("suspicious"),
            "review": verdicts.count("review"), "safe": verdicts.count("safe"),
            "non_play": sum(not r.facts.is_system and not r.facts.from_play for r in results),
            "admins": sum(r.facts.is_device_admin for r in results),
            "total": len(results), "user": sum(not r.facts.is_system for r in results),
        },
    }


def plan_view(plan: OrderPlan, lang: str) -> dict[str, Any]:
    apps = []
    for r in plan.results:
        base = {"package": r.package, "name": app_name(plan.facts.get(r.package), r.package),
                "level": r.level, "level_label": level_label(r.level, lang)}
        if isinstance(r, Blocked):
            apps.append({**base, "blocked": True, "reason": r.reason,
                         "reason_text": reason_text(r.reason, lang, r.package),
                         "steps": [], "warnings": []})
        else:
            apps.append({**base, "blocked": False, "reason": None, "reason_text": None,
                         "steps": [step_label(s.to_dict(), lang) for s in r.steps],
                         "warnings": [warning_text(w, lang) for w in r.warnings]})
    return {"apps": apps, "runnable": len(plan.plans)}


def step_view(event: dict[str, Any], lang: str, manufacturer: str,
              names: dict[str, str]) -> dict[str, Any]:
    package = event["package"]
    return {
        "action_id": event["action_id"], "package": package, "name": names.get(package, package),
        "kind": event["step"]["kind"], "label": step_label(event["step"], lang),
        "status": event["status"],
        "error": error_text(event["error"], lang, manufacturer) if event.get("error") else None,
        "restore_bytes": event.get("restore_bytes"),
    }


def result_view(result: OrderResult, names: dict[str, str], lang: str,
                manufacturer: str) -> dict[str, Any]:
    status = result.order.status
    return {
        "order": result.order.number, "status": status,
        "status_label": order_status_label(status, lang),
        "stopped": result.stopped,
        "apps": [{"package": a.package, "name": names.get(a.package, a.package),
                  "outcome": a.status,
                  "errors": [error_text(k, lang, manufacturer) for k in a.errors],
                  "kinds": list(a.kinds)} for a in result.apps],
    }


def action_view(a: Action, lang: str) -> dict[str, Any]:
    return {
        "id": a.id, "package": a.package, "level": a.level,
        "level_label": level_label(a.level, lang), "kind": a.step["kind"],
        "step_label": step_label(a.step, lang), "status": a.status,
        "status_label": TEXTS[lang]["action_status"].get(a.status, a.status),
        "error": error_text(a.error, lang) if a.error else None,
    }


def _history_device(journal: Journal, serial: str, orders: list[Order]) -> dict[str, Any]:
    # Nazwa i zdjęcie jak w protokole: z migawki najnowszego zlecenia, które ją ma.
    if not orders:
        return {"serial": serial, "name": serial, "model": None, "image": image_uri(SILHOUETTE),
                "imei": None}
    order, snap = orders[0], None
    for o in orders:
        snap = journal.scan(o.id)
        if snap is not None:
            order = o
            break
    block = device_block(snap or {}, order)
    return {"serial": serial, "name": block.name, "model": block.model, "image": image_uri(block.image),
            "imei": block.imei}


def device_identity(journal: Journal, serial: str) -> tuple[str, str | None]:
    """Nazwa i IMEI telefonu z zapisanych zleceń, jak na ekranie historii (zapas nazwy: numer seryjny)."""
    device = _history_device(journal, serial, journal.orders_for(serial))
    return device["name"], device["imei"]


def _order_apps(snap: dict[str, Any] | None, actions: list[Action]) -> dict[str, dict[str, Any]]:
    # Nazwy i ikony z migawki tego zlecenia: historia nie zależy od bieżącego skanu ani telefonu.
    if snap is None:
        return {}
    saved = {a["package"]: a for a in snap.get("apps", [])}
    return {p: {"name": saved.get(p, {}).get("label"), "icon": saved.get(p, {}).get("icon")}
            for p in dict.fromkeys(a.package for a in actions)}


def history_view(journal: Journal, serial: str | None, serials: list[str],
                 lang: str) -> dict[str, Any]:
    devices = []
    for s in serials:
        found = journal.orders_for(s)
        devices.append(_history_device(journal, s, found))
    if serial is None:
        return {"serial": None, "serials": serials, "devices": devices, "orders": []}
    interrupted = {o.id for o in journal.interrupted_orders(serial)}
    orders = []
    for o in journal.orders_for(serial):
        actions = journal.actions(o.id)
        orders.append({
            "id": o.id, "number": o.number,
            "created_at": o.created_at.isoformat(timespec="minutes"),
            "status": o.status,
            "status_label": order_status_label(o.status, lang),
            "client": o.client_name, "model": o.device_model,
            "interrupted": o.id in interrupted,
            "screenshots": journal.screenshot_count(o.id),
            "actions": [action_view(a, lang) for a in actions],
            "apps": _order_apps(journal.scan(o.id) if actions else None, actions),
        })
    return {"serial": serial, "serials": serials, "devices": devices, "orders": orders}


def estimate_view(est: Estimate, use: CacheUsage) -> dict[str, int]:
    return {"to_fetch_bytes": est.to_fetch_bytes, "total_bytes": est.total_bytes, "apps": est.apps,
            "unknown": est.unknown, "cached": est.cached, "largest_bytes": est.largest_bytes,
            "limit_bytes": use.limit_bytes, "effective_bytes": use.effective_bytes,
            "free_bytes": use.free_bytes}
