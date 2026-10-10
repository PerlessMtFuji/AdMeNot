"""Kopia APK przed usunięciem (spec §7.1, §7.4): backups/<serial>/<pakiet>/<versionCode>/.

Kopia jest kompletna tylko wtedy, gdy jej manifest (`.complete`: pakiet, wersja, SHA-256 każdego
pliku) zgadza się z plikami na dysku. Sam znacznik i „jakiś” APK nie wystarczą (audyt 2026-10-11,
BUG-02): ucięty albo brakujący split dałby usunięcie bez działającej drogi powrotu.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from admenot.engine.actions.errors import ActionError
from admenot.engine.adb.transport import AdbTransport
from admenot.engine.apk.fetch import fetch_apks, installed_hashes

COMPLETE = ".complete"  # manifest kopii (JSON); jego brak = kopia niepełna


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read_manifest(directory: Path) -> dict | None:
    """Manifest kopii zgodny z plikami na dysku, inaczej None."""
    try:
        manifest = json.loads((directory / COMPLETE).read_text("utf-8"))
        files = manifest["files"]
        if not isinstance(files, dict) or not files:
            return None
        if {p.name for p in directory.glob("*.apk")} != set(files):
            return None  # brakujący split albo obcy plik
        if any(_sha256(directory / name) != digest for name, digest in files.items()):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return manifest


def is_complete(directory: Path, package: str | None = None) -> bool:
    manifest = read_manifest(directory)
    return manifest is not None and package in (None, manifest.get("package"))


def _copy_verified(package: str, version_code: int | None, apks: list[Path],
                   expected: dict[str, str] | None, target: Path) -> None:
    """Kopiuje dokładnie pliki zwrócone przez `fetch_apks` do unikalnego katalogu roboczego
    i sprawdza SHA-256 każdej kopii (z telefonu, gdy znany, inaczej ze źródła). Wpis mógł zniknąć
    po pobraniu (przycięty przez drugi proces): wtedy błąd i brak manifestu — bez kopii nie
    odinstalowujemy."""
    if not apks:
        raise ActionError("backup_failed", "no APK files to back up")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(tempfile.mkdtemp(prefix=target.name + ".part-", dir=target.parent))
    try:
        files: dict[str, str] = {}
        for apk in apks:
            if not apk.is_file():
                raise ActionError("backup_failed", f"{apk} is gone")
            want = expected.get(apk.name) if expected else _sha256(apk)
            copy = partial / apk.name
            shutil.copy2(apk, copy)
            if want is None or _sha256(copy) != want:
                raise ActionError("backup_failed", f"{apk}: copy differs from the installed file")
            files[apk.name] = want
        manifest = {"package": package, "version_code": version_code, "files": files}
        (partial / COMPLETE).write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        shutil.rmtree(target, ignore_errors=True)
        partial.rename(target)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def backup_apks(
    adb: AdbTransport,
    package: str,
    version_code: int | None,
    target: Path,
    cache_dir: Path | None = None,
) -> list[Path]:
    """Kopia base + splity w `target` (= <root>/<pakiet>/<versionCode|unknown>).

    Istniejąca kopia jest użyta ponownie tylko, gdy jej manifest zgadza się ze skrótami plików
    zainstalowanych teraz na telefonie. Bez skrótów z telefonu (brak `sha256sum`) kopiujemy od nowa.
    `fetch_apks` bierze pliki z pamięci podręcznej analizy APK, gdy skróty się zgadzają.
    """
    if target.parent.name != package:
        raise ValueError(f"backup dir {target} does not belong to {package}")
    installed = installed_hashes(adb, package)
    manifest = read_manifest(target)
    if installed is not None and manifest is not None and (
            manifest.get("package") == package and manifest["files"] == installed):
        return sorted(target.glob("*.apk"))
    fetched = fetch_apks(adb, package, cache_dir if cache_dir is not None else target.parent.parent)
    _copy_verified(package, version_code, fetched.paths, fetched.expected, target)
    return sorted(target.glob("*.apk"))
