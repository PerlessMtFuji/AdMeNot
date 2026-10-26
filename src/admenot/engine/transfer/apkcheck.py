"""Ocena plików APK z kopii przed wgraniem na nowy telefon (spec Etapu 2 §5, §8a).

Sam plik bez potwierdzenia (dziedziczenie po zainstalowanej aplikacji albo IOC) nigdy nie dostaje
oceny „szkodliwy”: fałszywy alarm to po cichu pominięty plik klienta.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from admenot.engine.apk.analyze import ApkReport, analyze_apk
from admenot.engine.apk.iocs import IocList, load_default_iocs
from admenot.engine.apk.limits import ApkRejected, preflight
from admenot.engine.apk.manifest import read_manifest
from admenot.engine.facts import AppFacts
from admenot.engine.transfer.store import CopyDir

ApkOutcome = Literal["clean", "suspicious", "malicious", "unknown"]
ApkLevel = Literal["installed", "ioc", "static", "none"]

BUNDLE_EXT = (".apks", ".xapk", ".apkm")
CHECKS_FILE = "apk_checks.json"
_OBFUSCATED = 0.5


@dataclass(frozen=True)
class ApkCheck:
    remote: str
    package: str | None
    outcome: ApkOutcome
    level: ApkLevel
    default_on: bool  # „szkodliwy” nigdy nie jest wgrywany


def _check(remote: str, package: str | None, outcome: ApkOutcome, level: ApkLevel) -> ApkCheck:
    return ApkCheck(remote, package, outcome, level, outcome in ("clean", "unknown"))


def _analyze_file(name: str, paths: list[Path]) -> ApkReport:
    """Domyślna analiza luźnego pliku: pakiet nie jest znany z góry, więc czytamy go z manifestu.

    `preflight` idzie przed `read_manifest`, żeby bomba ZIP nie trafiła do parsera."""
    path = paths[0]
    try:
        preflight(path)
    except ApkRejected as exc:
        return ApkReport("", error=f"rejected: {exc}")
    try:
        package = read_manifest(path).package or ""
    except Exception:  # noqa: BLE001 — nieczytelny manifest = pakiet nieznany
        package = ""
    report = analyze_apk(package, paths)
    return report


def _installed_certs(copy: CopyDir, package: str) -> set[str] | None:
    """Certyfikat aplikacji skopiowanej ze starego telefonu; `None`, gdy brak APK w kopii."""
    for apk in sorted((copy.apps_dir / package).glob("*/base.apk")):
        try:
            preflight(apk)
            certs = set(read_manifest(apk).cert_sha256)
        except Exception:  # noqa: BLE001, S112 — nieczytelny APK = certyfikat nieznany
            continue
        if certs:
            return certs
    return None


def _facts(report: ApkReport) -> AppFacts:
    facts = AppFacts(report.package)
    hashes = set(report.files.values()) | ({report.sha256} if report.sha256 else set())
    facts.apk_sha256 = tuple(sorted(hashes)) or None
    facts.cert_sha256 = tuple(report.cert_sha256) or None
    return facts


def _sha_ioc(local: Path, report: ApkReport | None, iocs: IocList) -> bool:
    """Zgodność SHA-256 pliku z IOC nie wymaga manifestu; haszowanie nie parsuje archiwum."""
    hashes = set(report.files.values()) if report else set()
    if report and report.sha256:
        hashes.add(report.sha256)
    try:
        hashes.add(_sha256(local))
    except OSError:
        pass
    return any(i.kind == "sha256" and i.value in hashes for i in iocs.entries)


def _judge(remote: str, local: Path, report: ApkReport,
           verdicts: dict[str, tuple[int | None, str]] | None, iocs: IocList, copy: CopyDir) -> ApkCheck:
    package = report.package or None
    if (report.error or "").startswith("rejected:") or not package:
        if _sha_ioc(local, report, iocs):
            return _check(remote, package, "malicious", "ioc")
        return _check(remote, package, "unknown", "none")
    known = verdicts.get(package) if verdicts else None
    if known and known[1] in ("malicious", "suspicious"):
        return _check(remote, package, known[1], "installed")  # type: ignore[arg-type]
    for ioc in iocs.match(_facts(report)):
        if ioc.kind == "sha256" or (ioc.kind == "signer" and ioc.exclusive):
            return _check(remote, package, "malicious", "ioc")
    if known:
        installed = _installed_certs(copy, package)
        mine = set(report.cert_sha256)
        if installed is not None and mine:
            return _check(remote, package, "clean" if installed == mine else "suspicious", "installed")
    flagged = report.label_padded or (
        bool(report.ad_sdks) and (report.dynamic_code or report.obfuscation_ratio >= _OBFUSCATED))
    return _check(remote, package, "suspicious" if flagged else "clean", "static")


def check_apks(
    copy: CopyDir,
    files: list[tuple[str, Path]],
    iocs: IocList | None = None,
    analyze: Callable[[str, list[Path]], ApkReport] | None = None,
) -> list[ApkCheck]:
    iocs = iocs if iocs is not None else load_default_iocs()
    analyze = analyze or _analyze_file  # w czasie wywołania: podmienialne w testach
    verdicts = copy.read_verdicts()
    result = []
    for remote, local in files:
        if remote.lower().endswith(BUNDLE_EXT):
            result.append(_check(remote, None, "unknown", "none"))
            continue
        try:
            report = analyze(remote, [local])
        except Exception:  # noqa: BLE001 — jeden plik nie przerywa oceny reszty
            if _sha_ioc(local, None, iocs):
                result.append(_check(remote, None, "malicious", "ioc"))
            else:
                result.append(_check(remote, None, "unknown", "none"))
            continue
        result.append(_judge(remote, local, report, verdicts, iocs, copy))
    return result


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def load_or_check(copy: CopyDir, files: list[tuple[str, Path]]) -> list[ApkCheck]:
    """Wynik w `<copy>/apk_checks.json` (z SHA-256 pliku); niezmienione pliki nie są analizowane ponownie.
    Pliku nieczytelnego (np. usuniętego z kopii przez antywirus) nie ma w wyniku."""
    path = copy.path / CHECKS_FILE
    try:
        cached = {e["remote"]: e for e in json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, ValueError, KeyError, TypeError):
        cached = {}
    hashes: dict[str, str] = {}
    for remote, local in files:
        try:
            hashes[remote] = _sha256(local)
        except OSError:
            continue
    files = [(remote, local) for remote, local in files if remote in hashes]
    out: dict[str, ApkCheck] = {}
    todo: list[tuple[str, Path]] = []
    for remote, local in files:
        entry = cached.get(remote)
        try:
            if entry and entry["sha256"] == hashes[remote]:
                out[remote] = ApkCheck(**entry["check"])
                continue
        except (KeyError, TypeError):
            pass
        todo.append((remote, local))
    if todo:
        for check in check_apks(copy, todo):
            out[check.remote] = check
        data = [{"remote": r, "sha256": hashes[r], "check": asdict(out[r])} for r, _ in files]
        tmp = path.with_name(CHECKS_FILE + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    return [out[remote] for remote, _ in files]
