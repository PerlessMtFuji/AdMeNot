"""Zdarzenia statystyk (spec kroku H §5): czyste funkcje, bez I/O.

`*_event` zwraca część własną zdarzenia; pola wspólne dokleja `telemetry.record` (`common`).
`sample()` buduje przykład tymi samymi funkcjami — to pokazuje UI w „Co wysyłamy”.
"""

from __future__ import annotations

import platform
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from admenot import __version__
from admenot.engine.actions.planner import AppPlan
from admenot.engine.device.info import DeviceInfo
from admenot.engine.session import ScanReport
from admenot.engine.workflow import AppStatus, OrderResult

MAX_PACKAGES = 200
MAX_ERRORS = 20
FLAGGED = ("malicious", "suspicious", "review")
LEVELS = ("silence", "disable", "remove")
SAMPLE_INSTALL = "00000000-0000-4000-8000-000000000000"
_PKG = re.compile(r"^[A-Za-z0-9_.]{1,255}$")
# Limity serwera (server/src/telemetry.ts): jedno złe pole odrzuca całą paczkę, więc przycinamy tu.
SHORT = 64
MAX_COUNT = 100_000
MAX_SECONDS = 86_400
MAX_SCORE = 1000


def _short(value: str | None) -> str:
    """Niepusty napis ≤ 64 znaki; pusty (np. telefon bez `ro.build.version.release`) → „?”."""
    return (value or "").strip()[:SHORT] or "?"


def _count(value: int, top: int = MAX_COUNT) -> int:
    return min(max(0, int(value)), top)


def hour(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:00:00Z")


def common(install: str, type_: str, now: datetime, lang: str) -> dict[str, Any]:
    return {"install": install, "type": type_, "t": hour(now), "app": __version__,
            "os": _short(f"{platform.system()} {platform.version()}"), "lang": lang}


def device_of(device: DeviceInfo) -> dict[str, str]:
    return {"manufacturer": _short(device.manufacturer), "model": _short(device.model),
            "android": _short(device.android_release)}


def _listed(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [i for i in items if _PKG.match(i["package"])][:MAX_PACKAGES]


def start_body(mode: str) -> dict[str, Any]:
    return {"mode": mode}


def scan_event(report: ScanReport, session: str, seconds: int, packages: bool,
               apk_stage: bool = False) -> dict[str, Any]:
    flagged = [r for r in report.results if r.verdict != "safe"]  # wyniki są już po wyniku malejąco
    apk = report.apk
    return {
        "device": device_of(report.device), "session": session, "apps": _count(len(report.results)),
        "verdicts": {v: sum(1 for r in flagged if r.verdict == v) for v in FLAGGED},
        "low_behavior_data": report.low_behavior_data,
        "apk": None if apk is None else {"requested": apk.requested, "analyzed": apk.analyzed,
                                         "failed": len(apk.failed)},
        "seconds": _count(seconds, MAX_SECONDS), "apk_stage": apk_stage,
        "packages": _listed({"package": r.facts.package, "verdict": r.verdict, "score": _count(r.score, MAX_SCORE),
                             "confidence": r.confidence, "system": r.facts.is_system}
                            for r in flagged) if packages else None,
    }


def repair_event(device: DeviceInfo, session: str, plans: list[AppPlan], verdicts: dict[str, str],
                 result: OrderResult | None, interrupted: str | None,
                 packages: bool) -> dict[str, Any]:
    statuses: dict[str, AppStatus] = {a.package: a for a in result.apps} if result else {}

    def source(package: str) -> str:
        return "flagged" if verdicts.get(package, "safe") != "safe" else "manual"

    def ok(package: str) -> bool | None:
        status = statuses.get(package)
        return None if status is None else status.status == "ok"

    failed = [a for a in statuses.values() if a.status != "ok"]
    errors = sorted({key[:SHORT] for a in failed for key in a.errors if key})[:MAX_ERRORS]
    return {
        "device": device_of(device), "session": session,
        "levels": {lvl: sum(1 for p in plans if p.level == lvl) for lvl in LEVELS},
        "sources": {src: sum(1 for p in plans if source(p.package) == src)
                    for src in ("flagged", "manual")},
        "failed": len(failed), "errors": errors, "interrupted": interrupted,
        "packages": _listed({"package": p.package, "source": source(p.package), "level": p.level,
                             "ok": ok(p.package)} for p in plans) if packages else None,
    }


def undo_event(device: DeviceInfo, apps: list[str], failed: list[str], age_days: int,
               packages: bool) -> dict[str, Any]:
    bad = set(failed)
    return {
        "device": device_of(device), "apps": len(apps), "failed": len(bad),
        "age_days": _count(age_days),
        "packages": _listed({"package": p, "ok": p not in bad} for p in apps) if packages else None,
    }


_SAMPLE_DEVICE = DeviceInfo(serial="-", brand="OPPO", manufacturer="OPPO", model="CPH2483",
                            device="-", market_name=None, android_release="14", sdk=34,
                            security_patch=None, uptime_s=0.0, local_now=datetime(2026, 10, 10))


def _sample_scan(packages: bool) -> dict[str, Any]:
    flagged = [{"package": "com.clean.pro.boost", "verdict": "malicious", "score": 82,
                "confidence": "high", "system": False},
               {"package": "com.wlive.forecast", "verdict": "review", "score": 31,
                "confidence": "medium", "system": False}]
    return {"device": device_of(_SAMPLE_DEVICE), "session": "ab12cd34", "apps": 187,
            "verdicts": {"malicious": 1, "suspicious": 0, "review": 1}, "low_behavior_data": False,
            "apk": {"requested": 2, "analyzed": 2, "failed": 0}, "seconds": 41,
            "apk_stage": False, "packages": flagged if packages else None}


def sample() -> dict[str, list[dict[str, Any]]]:
    now = datetime(2026, 10, 10, 14, 0, tzinfo=UTC)
    plans = [AppPlan("com.clean.pro.boost", "remove", []), AppPlan("com.wlive.forecast", "disable", [])]
    result = OrderResult(order=None, apps=[AppStatus("com.clean.pro.boost", "ok"),  # type: ignore[arg-type]
                                           AppStatus("com.wlive.forecast", "ok")], stopped=False)
    verdicts = {"com.clean.pro.boost": "malicious", "com.wlive.forecast": "review"}
    out: dict[str, list[dict[str, Any]]] = {}
    for name, packages in (("basic", False), ("packages", True)):
        bodies = [("start", start_body("simple")), ("scan", _sample_scan(packages)),
                  ("repair", repair_event(_SAMPLE_DEVICE, "ab12cd34", plans, verdicts, result,
                                          None, packages)),
                  ("undo", undo_event(_SAMPLE_DEVICE, ["com.wlive.forecast"], [], 2, packages))]
        out[name] = [{**common(SAMPLE_INSTALL, t, now, "pl"), **body} for t, body in bodies]
    return out
