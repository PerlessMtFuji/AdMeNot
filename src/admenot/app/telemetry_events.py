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
from admenot.engine.actions.planner import FIX_LEVEL, AppPlan
from admenot.engine.apk.timing import Eta
from admenot.engine.device.info import DeviceInfo
from admenot.engine.journal.db import Action
from admenot.engine.session import ScanReport
from admenot.engine.transfer.backup import BackupResult, Selection
from admenot.engine.transfer.restore import RestoreResult, UploadChoice
from admenot.engine.transfer.restore_plan import UPLOAD_GROUPS
from admenot.engine.transfer.telephony import CategoryResult
from admenot.engine.workflow import AppStatus, OrderResult

MAX_PACKAGES = 200
MAX_ERRORS = 20
FLAGGED = ("malicious", "suspicious", "review")
LEVELS = ("silence", "disable", "remove")
SITE_MODES = ("per_site", "shared", "rdp")
FIX_KINDS = ("channel", "site_permission")
SAMPLE_INSTALL = "00000000-0000-4000-8000-000000000000"
_PKG = re.compile(r"^[A-Za-z0-9_.]{1,255}$")
# Limity serwera (server/src/telemetry.ts): jedno złe pole odrzuca całą paczkę, więc przycinamy tu.
SHORT = 64
MAX_COUNT = 100_000
MAX_SECONDS = 86_400
MAX_SCORE = 1000
MAX_MB = 10_000_000  # 10 TB w MB — kopia telefonu; serwer ma ten sam limit `bytes_mb`
TRANSFER_CATEGORIES = ("contacts", "sms", "mms", "calls", "media", "downloads", "whatsapp",
                       "others", "apps")
MAX_STREAMS = 8  # serwer: `streams` 1–8


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


def _site_counts(report: ScanReport) -> dict[str, int]:
    """Liczba witryn z odczytu według sposobu odczytu — bez domen i bez pakietów przeglądarek."""
    counts = dict.fromkeys(SITE_MODES, 0)
    for check in report.device_checks:
        for browser in check.browsers:
            if browser.mode in counts:
                counts[browser.mode] += _count(len(browser.sites))
    return counts


def scan_event(report: ScanReport, session: str, seconds: int, packages: bool,
               apk_stage: bool = False, eta: Eta | None = None) -> dict[str, Any]:
    flagged = [r for r in report.results if r.verdict != "safe"]  # wyniki są już po wyniku malejąco
    apk = report.apk
    return {
        "device": device_of(report.device), "session": session, "apps": _count(len(report.results)),
        "verdicts": {v: sum(1 for r in flagged if r.verdict == v) for v in FLAGGED},
        "low_behavior_data": report.low_behavior_data,
        "apk": None if apk is None else {"requested": apk.requested, "analyzed": apk.analyzed,
                                         "failed": len(apk.failed)},
        "seconds": _count(seconds, MAX_SECONDS), "apk_stage": apk_stage,
        "apk_mode": report.apk_mode,
        "checks": {c.id: _short(c.state) for c in report.device_checks},
        "sites": _site_counts(report),
        "eta": {"kind": eta.kind, "seconds": _count(eta.seconds, MAX_SECONDS)} if eta else None,
        "packages": _listed({"package": r.facts.package, "verdict": r.verdict, "score": _count(r.score, MAX_SCORE),
                             "confidence": r.confidence, "system": r.facts.is_system}
                            for r in flagged) if packages else None,
    }


def repair_event(device: DeviceInfo, session: str, plans: list[AppPlan], verdicts: dict[str, str],
                 result: OrderResult | None, interrupted: str | None,
                 packages: bool, blind: frozenset[str] = frozenset(),
                 actions: Iterable[Action] = ()) -> dict[str, Any]:
    """`actions`: kroki zlecenia z dziennika — poprawki ustawień liczą się wykonane, nie zaplanowane."""
    statuses: dict[str, AppStatus] = {a.package: a for a in result.apps} if result else {}
    done_fixes = [a.step["kind"] for a in actions if a.level == FIX_LEVEL and a.status == "done"]
    plans = [p for p in plans if p.level != FIX_LEVEL]  # ustawienia witryn, nie aplikacje

    def source(package: str) -> str:
        if package in blind:  # wybrana w trybie ręcznym; ukryty werdykt heurystyk jest w skanie
            return "blind"
        return "flagged" if verdicts.get(package, "safe") != "safe" else "manual"

    def ok(package: str) -> bool | None:
        status = statuses.get(package)
        return None if status is None else status.status == "ok"

    apps = {p.package for p in plans}  # przeglądarka z samą poprawką ustawień to nie nieudana aplikacja
    failed = [a for a in statuses.values() if a.status != "ok" and a.package in apps]
    errors = sorted({key[:SHORT] for a in failed for key in a.errors if key})[:MAX_ERRORS]
    return {
        "device": device_of(device), "session": session,
        "levels": {lvl: sum(1 for p in plans if p.level == lvl) for lvl in LEVELS},
        "sources": {src: sum(1 for p in plans if source(p.package) == src)
                    for src in ("flagged", "manual", "blind")},
        "fixes": {kind: done_fixes.count(kind) for kind in FIX_KINDS},
        "failed": len(failed), "errors": errors, "interrupted": interrupted,
        "packages": _listed({"package": p.package, "source": source(p.package), "level": p.level,
                             "ok": ok(p.package)} for p in plans) if packages else None,
    }


SITE_UNDO_ERRORS = frozenset({"site_skipped", "site_timeout"})


def undo_targets(targeted: Iterable[Action], errors: Iterable[tuple[Action, str]],
                 ) -> tuple[list[str], list[str]]:
    """(aplikacje, nieudane) cofania bez przeglądarek z samą poprawką ustawień: to nie aplikacje, a
    przeglądarka spoza tabeli znanych nie może trafić do telemetrii z nazwą pakietu."""
    targeted = list(targeted)
    apps = {a.package for a in targeted if a.level != FIX_LEVEL}
    # Niewłączona witryna (pominięta albo po czasie) liczy się w `sites`/`sites_restored`, nie jako błąd aplikacji.
    return sorted(apps), sorted({a.package for a, key in errors
                                 if a.package in apps and key not in SITE_UNDO_ERRORS})


def undo_event(device: DeviceInfo, apps: list[str], failed: list[str], age_days: int,
               packages: bool, sites: int = 0, sites_restored: int = 0) -> dict[str, Any]:
    bad = set(failed)
    return {
        "device": device_of(device), "apps": len(apps), "failed": len(bad),
        "age_days": _count(age_days),
        # Tylko liczby, bez nazw witryn.
        "sites": _count(sites), "sites_restored": _count(sites_restored),
        "packages": _listed({"package": p, "ok": p not in bad} for p in apps) if packages else None,
    }


def transfer_backup_event(device: DeviceInfo, result: BackupResult,
                          selection: Selection) -> dict[str, Any]:
    """Zakończona kopia starego telefonu: same liczby i wybrane rodzaje danych. Bez nazw folderów,
    plików i pakietów (`others`/`apps` to tylko „coś wybrano”)."""
    chosen = {"contacts": selection.contacts, "sms": selection.sms, "mms": selection.mms,
              "calls": selection.calls, "media": "media" in selection.categories,
              "downloads": "downloads" in selection.categories,
              "whatsapp": "whatsapp" in selection.categories,
              "others": bool(selection.others), "apps": bool(selection.apps)}
    return {
        "device": device_of(device), "status": result.status,
        "seconds": _count(result.seconds, MAX_SECONDS),
        "bytes_mb": _count(round(result.bytes / 1_000_000), MAX_MB),
        "files": _count(result.files_done), "files_failed": _count(result.files_failed),
        "apps": _count(result.apps_done), "apps_failed": _count(result.apps_failed),
        "categories": {k: bool(chosen[k]) for k in TRANSFER_CATEGORIES},
    }


def transfer_restore_event(device: DeviceInfo, result: RestoreResult, choice: UploadChoice,
                           streams: int) -> dict[str, Any]:
    """Wgrywanie kopii na nowy telefon (`device` = telefon docelowy): same liczby i wybrane grupy.
    Bez nazw plików, folderów i pakietów z plików APK — „Inne foldery” to tylko `others`: coś
    wybrano. Serial telefonu docelowego (`result.target_serial`) też nie wychodzi."""
    groups = {g: g in choice.groups for g in UPLOAD_GROUPS}
    groups["others"] = any(g.startswith("other:") for g in choice.groups)
    return {
        "device": device_of(device), "status": result.status,
        "seconds": _count(result.seconds, MAX_SECONDS),
        "bytes_mb": _count(round(result.bytes / 1_000_000), MAX_MB),
        "files": _count(result.files_done), "exists": _count(result.files_exists),
        "renamed": _count(result.files_renamed), "denied": _count(result.files_denied),
        "failed": _count(result.files_failed), "unselected": _count(result.files_unselected),
        "missing": _count(result.files_missing), "apk_skipped": _count(result.apk_skipped),
        "apk_suspicious_skipped": _count(result.apk_suspicious_skipped),
        "streams": min(max(1, int(streams)), MAX_STREAMS), "hashed": result.hashed,
        "media_scan": result.media_scan, "groups": groups,
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
            # Szybki skan (apk_stage False): APK jeszcze nie przeanalizowane, tryb dopiero do wyboru.
            "apk": None, "seconds": 41, "apk_stage": False, "apk_mode": "pending", "eta": None,
            "checks": {"site_notifications": "review"}, "sites": {"per_site": 2, "shared": 1, "rdp": 0},
            "packages": flagged if packages else None}


def sample() -> dict[str, list[dict[str, Any]]]:
    now = datetime(2026, 10, 10, 14, 0, tzinfo=UTC)
    plans = [AppPlan("com.clean.pro.boost", "remove", []), AppPlan("com.wlive.forecast", "disable", [])]
    result = OrderResult(order=None, apps=[AppStatus("com.clean.pro.boost", "ok"),  # type: ignore[arg-type]
                                           AppStatus("com.wlive.forecast", "ok")], stopped=False)
    verdicts = {"com.clean.pro.boost": "malicious", "com.wlive.forecast": "review"}
    backup = BackupResult(status="complete", copy_id="-", telephony={"contacts": CategoryResult("ok", 412)},
                          files_done=5230, files_failed=0, apps_done=12, apps_failed=0,
                          bytes=38_400_000_000, seconds=2710)
    chosen = Selection(contacts=True, sms=True, mms=False, calls=True,
                       categories=frozenset({"media", "whatsapp"}), others=frozenset(),
                       apps=frozenset({"-"}))
    restore = RestoreResult(status="complete", target_serial="-", files_done=5108, files_exists=120,
                            files_renamed=3, files_denied=0, files_failed=0, files_unselected=0,
                            apk_skipped=1, apk_suspicious_skipped=0, bytes=37_900_000_000, seconds=1840,
                            hashed=False, media_scan="done", files_missing=0)
    upload = UploadChoice(groups=frozenset({"photos", "videos", "downloads", "whatsapp"}), apks_on=frozenset())
    out: dict[str, list[dict[str, Any]]] = {}
    for name, packages in (("basic", False), ("packages", True)):
        bodies = [("start", start_body("simple")), ("scan", _sample_scan(packages)),
                  ("repair", repair_event(_SAMPLE_DEVICE, "ab12cd34", plans, verdicts, result,
                                          None, packages)),
                  ("undo", undo_event(_SAMPLE_DEVICE, ["com.wlive.forecast"], [], 2, packages,
                                    sites=2, sites_restored=1)),
                  ("transfer_backup", transfer_backup_event(_SAMPLE_DEVICE, backup, chosen)),
                  ("transfer_restore", transfer_restore_event(_SAMPLE_DEVICE, restore, upload, 4))]
        out[name] = [{**common(SAMPLE_INSTALL, t, now, "pl"), **body} for t, body in bodies]
    return out
