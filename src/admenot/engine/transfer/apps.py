"""Aplikacje z kopii na nowym telefonie (Etap 4): plan (co da się zainstalować) i instalacja.

Nowy telefon: tylko dopisywanie. Instalacja idzie przez `AppInstallAdb` — wyłącznie `install` /
`install-multiple` (bez `-r`, `-d`, `-g`, bez odinstalowania) plików spod `apps/` kopii. Aplikacja
już zainstalowana (jakakolwiek wersja) nigdy nie jest instalowana ponownie. Stan każdej aplikacji
(`pending | installed | exists | skipped | failed`) leży w `RestoreState`, więc wznowienie po
rozłączeniu nie robi nic dwa razy: `pending` znaczy „polecenie poszło, wynik nieznany” — wtedy
najpierw sprawdzamy `pm list packages`.

Zgoda na ekranie telefonu: `install` czeka do `INSTALL_TIMEOUT`; odmowa albo limit czasu to
`failed/no_consent`, kolejne aplikacje lecą dalej. `INSTALL_FAILED_USER_RESTRICTED` (Xiaomi „Instaluj
przez USB”) blokuje resztę: reszta wybranych kończy jako `skipped/user_restricted`, a `only_blocked`
doinstaluje później tylko je.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from admenot.engine.actions.backup import is_complete
from admenot.engine.adb.transport import AdbError
from admenot.engine.device.info import DeviceInfo

from .backup import MAX_DISCONNECTS
from .guard import APP_INSTALLER, AppInstallAdb
from .restore_state import RestoreState
from .store import CopyDir

# Instalator zapisany w pakiecie (decyzja ze spike'u na OPPO, spec §5.2): aplikacje dostają aktualizacje
# ze Sklepu Play. `None` = instalacja bez `-i`.
INSTALLER: str | None = APP_INSTALLER
INSTALL_TIMEOUT = 300.0  # s — tyle czekamy na zgodę na ekranie telefonu
APP_ATTEMPTS = 3  # próby aplikacji z błędem bez rozpoznanego kodu (kabel/adb); rozłączenie próby nie zużywa

SkipReason = Literal["installed", "too_old", "too_new", "no_abi", "incomplete"]
AppError = Literal["user_restricted", "no_consent", "too_old", "no_abi", "no_space", "version_downgrade",
                   "conflict", "invalid_apk", "disconnected", "failed"]

_XIAOMI = {"xiaomi", "redmi", "poco"}
_ABI_SPLIT = re.compile(r"split_config\.([a-z0-9_]+)\.apk")
_ABIS = {"arm64_v8a", "armeabi_v7a", "armeabi", "x86", "x86_64", "mips", "mips64", "riscv64"}
_CODE = re.compile(r"INSTALL_(?:PARSE_)?FAILED_[A-Z0-9_]+")
_SECURITY = re.compile(r"security ?exception", re.IGNORECASE)
_INSTALLER_WORD = re.compile(r"installer", re.IGNORECASE)
_TOO_OLD_TARGET = 23  # Android 14+ odrzuca targetSdk poniżej 23
_TOO_OLD_ANDROID = 34

_CLASSIFY: tuple[tuple[re.Pattern[str], AppError], ...] = tuple(
    (re.compile(p, re.IGNORECASE), e) for p, e in (
        (r"INSTALL_FAILED_USER_RESTRICTED", "user_restricted"),
        (r"INSTALL_FAILED_ABORTED|cancell?ed[ _]by[ _]user", "no_consent"),
        (r"INSTALL_FAILED_DEPRECATED_SDK_VERSION|INSTALL_FAILED_OLDER_SDK", "too_old"),
        (r"INSTALL_FAILED_NO_MATCHING_ABIS", "no_abi"),
        (r"INSTALL_FAILED_INSUFFICIENT_STORAGE", "no_space"),
        (r"INSTALL_FAILED_VERSION_DOWNGRADE", "version_downgrade"),
        (r"INSTALL_FAILED_UPDATE_INCOMPATIBLE|INSTALL_FAILED_ALREADY_EXISTS|INSTALL_FAILED_DUPLICATE_PERMISSION",
         "conflict"),
        (r"INSTALL_PARSE_FAILED_|INSTALL_FAILED_INVALID_APK", "invalid_apk"),
    ))


def classify_install(output: str) -> tuple[AppError, str | None]:
    """Wyjście nieudanej instalacji -> (powód, surowy kod `INSTALL_FAILED_…`/`INSTALL_PARSE_FAILED_…` albo None)."""
    found = _CODE.search(output)
    code = found.group(0) if found else None
    for pattern, error in _CLASSIFY:
        if pattern.search(output):
            return error, code
    return "failed", code


@dataclass(frozen=True)
class AppCandidate:
    package: str
    label: str  # nazwa ze starego telefonu; brak -> nazwa pakietu
    version_code: int | None
    bytes: int
    verdict: str
    default_on: bool
    skip: SkipReason | None
    files: tuple[Path, ...]


@dataclass(frozen=True)
class AppsPlan:
    apps: list[AppCandidate]
    block: Literal["xiaomi"] | None


@dataclass(frozen=True)
class AppsProgress:
    stage: Literal["apps"]
    done: int
    total: int
    current: str  # etykieta aplikacji — tylko UI


@dataclass(frozen=True)
class AppsResult:
    selected: int
    installed: int
    exists: int
    skipped: dict[str, int]
    failed: dict[str, int]
    codes: dict[str, int]
    blocked: bool
    stopped: bool
    rows: list[dict[str, Any]]  # {"package", "label", "status", "reason"} dla każdej wybranej
    play_installer: bool  # każde wysłane polecenie instalacji miało `-i com.android.vending` (i jakieś wysłano)


def apk_sdk(base: Path) -> tuple[int | None, int | None]:
    """(minSdk, targetSdk) z APK przez androguard; błąd odczytu -> (None, None) — wtedy nie pomijamy."""
    try:
        from loguru import logger

        logger.disable("androguard")
        from androguard.core.apk import APK

        apk = APK(str(base))
        return _int(apk.get_min_sdk_version()), _int(apk.get_target_sdk_version())
    except Exception:  # noqa: BLE001 — uszkodzony APK nie może zatrzymać planu; instalacja sama oceni
        return None, None


def _int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def xiaomi_install_blocked(adb: AppInstallAdb) -> bool | None:
    """`persist.security.adbinstall`: `0` -> zablokowane, `1` -> dozwolone, inaczej nieznane (nie blokujemy)."""
    try:
        value = adb.shell("getprop persist.security.adbinstall").strip()
    except AdbError:
        return None
    return {"0": True, "1": False}.get(value)


def installer_rejected(output: str, c_files: tuple[Path, ...], package: str) -> bool:
    """Telefon odrzucił `-i`: SecurityException o instalatorze, bez kodu `INSTALL_FAILED_…`. Lokalne ścieżki
    plików i nazwa pakietu (mogą zawierać słowo „installer”) są przed sprawdzeniem wycinane z wyjścia."""
    if _CODE.search(output):
        return False
    text = output
    for f in c_files:
        for variant in (str(f), f.as_posix(), str(f.parent), f.parent.as_posix()):
            text = text.replace(variant, "")
    text = text.replace(package, "")
    return bool(_SECURITY.search(text) and _INSTALLER_WORD.search(text))


def _listed(out: str) -> set[str]:
    return {line[len("package:"):].strip() for line in out.splitlines() if line.startswith("package:")}


def _best_version(pkg_dir: Path, package: str) -> tuple[int, Path] | None:
    """Najwyższa kompletna wersja `apps/<pakiet>/<versionCode>/`."""
    best: tuple[int, Path] | None = None
    for d in pkg_dir.iterdir():
        if d.is_dir() and d.name.isdigit() and is_complete(d, package) and (best is None or int(d.name) > best[0]):
            best = (int(d.name), d)
    return best


def _abi_missing(files: tuple[Path, ...], abilist: str) -> bool:
    wanted = {m.group(1) for f in files if (m := _ABI_SPLIT.fullmatch(f.name)) and m.group(1) in _ABIS}
    if not wanted:
        return False
    have = {a.strip().replace("-", "_") for a in abilist.split(",") if a.strip()}
    return not (wanted & have)


def build_apps_plan(adb: AppInstallAdb, copy: CopyDir, device: DeviceInfo) -> AppsPlan:
    """Aplikacje z `apps/` kopii z powodem pominięcia albo bez. Tylko odczyty z telefonu."""
    verdicts = copy.read_verdicts() or {}
    labels = copy.read_app_labels()
    installed = _listed(adb.shell("pm list packages"))
    abilist = adb.shell("getprop ro.product.cpu.abilist").strip()
    apps: list[AppCandidate] = []
    root = copy.apps_dir
    for pkg_dir in sorted(root.iterdir()) if root.is_dir() else []:
        if not pkg_dir.is_dir():
            continue
        package = pkg_dir.name
        verdict = verdicts.get(package, (None, "unknown"))[1]
        label = labels.get(package) or package
        found = _best_version(pkg_dir, package)
        if found is None:
            apps.append(AppCandidate(package, label, None, 0, verdict, verdict != "suspicious", "incomplete", ()))
            continue
        version, directory = found
        files = tuple(sorted(directory.glob("*.apk")))
        size = sum(f.stat().st_size for f in files)
        skip: SkipReason | None = None
        if package in installed:
            skip = "installed"
        else:
            base = directory / "base.apk"
            min_sdk, target_sdk = apk_sdk(base if base.is_file() else files[0])
            if device.sdk >= _TOO_OLD_ANDROID and target_sdk is not None and target_sdk < _TOO_OLD_TARGET:
                skip = "too_old"
            elif min_sdk is not None and device.sdk < min_sdk:
                skip = "too_new"
            elif _abi_missing(files, abilist):
                skip = "no_abi"
        apps.append(AppCandidate(package, label, version, size, verdict, verdict != "suspicious", skip, files))
    apps.sort(key=lambda c: (c.label.lower(), c.package))
    block = None
    if device.manufacturer.lower() in _XIAOMI and xiaomi_install_blocked(adb) is True:
        block = "xiaomi"
    return AppsPlan(apps, block)


class _TooManyDisconnects(Exception):
    pass


class _Installer:
    def __init__(self, adb: AppInstallAdb, plan: AppsPlan, packages: frozenset[str], state: RestoreState,
                 on_progress: Callable[[AppsProgress], None], should_stop: Callable[[], bool],
                 wait_device: Callable[[], None], only_blocked: bool) -> None:
        self.adb, self.plan, self.state = adb, plan, state
        self.on_progress, self.should_stop, self.wait_device = on_progress, should_stop, wait_device
        self.only_blocked = only_blocked
        self.chosen = sorted((c for c in plan.apps if c.package in packages),
                             key=lambda c: (c.label.lower(), c.package))
        self.installer = INSTALLER
        self.sent = self.sent_with_installer = 0
        self.disconnects = 0
        self.blocked = False
        self.stopped = False

    # ---- telefon ---------------------------------------------------------------------------
    def _alive(self) -> bool:
        try:
            return self.adb.run(["get-state"]).strip() == "device"
        except AdbError:
            return False

    def _disconnected(self) -> None:
        self.disconnects += 1
        if self.disconnects > MAX_DISCONNECTS:
            raise _TooManyDisconnects
        self.wait_device()

    def _call(self, fn: Callable[[], Any]) -> Any:
        """Odczyt z telefonu; rozłączenie -> czekamy na telefon i ponawiamy (bez zużycia próby aplikacji)."""
        while True:
            try:
                return fn()
            except AdbError:
                if self._alive():
                    raise
                self._disconnected()

    def _present(self, package: str) -> bool:
        return package in self._call(lambda: _listed(self.adb.shell(f"pm list packages {package}")))

    def _send(self, c: AppCandidate) -> str:
        opt = ["-i", self.installer] if self.installer else []
        self.sent += 1
        self.sent_with_installer += bool(opt)
        args = ["install" if len(c.files) == 1 else "install-multiple", *opt, *map(str, c.files)]
        return self.adb.run(args, timeout=INSTALL_TIMEOUT)

    # ---- jedna aplikacja ---------------------------------------------------------------------
    def _set(self, package: str, status: str, reason: str | None = None, code: str | None = None) -> None:
        self.state.app_set(package, status, reason, code)

    def _install(self, c: AppCandidate, attempted: bool) -> bool:
        """Instaluje `c`; True = telefon zablokował instalacje (`user_restricted`)."""
        unknown = 0
        while True:
            if self._present(c.package):
                self._set(c.package, "installed" if attempted else "exists")
                return False
            attempted = True
            self.state.app_attempt(c.package)
            try:
                out = self._send(c)
            except AdbError as exc:
                if exc.kind == "timeout":
                    if self._present(c.package):  # zgoda przyszła tuż po limicie
                        self._set(c.package, "installed")
                    else:
                        self._set(c.package, "failed", "no_consent")
                    return False
                if not self._alive():
                    self._disconnected()
                    continue
                out = exc.message
            if "Success" in out and not _CODE.search(out):
                if self._present(c.package):
                    self._set(c.package, "installed")
                else:
                    self._set(c.package, "failed", "failed")
                return False
            error, code = classify_install(out)
            if self.installer and installer_rejected(out, c.files, c.package):
                self.installer = None  # telefon nie przyjmuje `-i`: ta aplikacja jeszcze raz, reszta też bez
                continue
            if error == "user_restricted":
                self._set(c.package, "skipped", error, code)
                return True
            if self._present(c.package):  # wcześniejsza sesja instalacji (stare okno zgody) mogła ją dokończyć
                self._set(c.package, "installed")
                return False
            if error == "failed" and code is None:
                unknown += 1
                if unknown < APP_ATTEMPTS:
                    continue
            self._set(c.package, "failed", error, code)
            return False

    # ---- przebieg ----------------------------------------------------------------------------
    def run(self) -> AppsResult:
        todo: list[tuple[AppCandidate, bool]] = []  # (aplikacja, czy instalacja już była wysłana)
        try:
            self._prepare(todo)
            self._process(todo, len(todo), 0)
        except _TooManyDisconnects:
            self.stopped = True
            for c, _ in todo:
                if self.state.apps_status().get(c.package, ("",))[0] == "pending":
                    self._set(c.package, "failed", "disconnected")
        return self._result()

    def _prepare(self, todo: list[tuple[AppCandidate, bool]]) -> None:
        if self.state.get_meta("apps_pre_installed") is None:
            try:
                before = self._call(lambda: _listed(self.adb.shell("pm list packages")))
            except AdbError:
                before = None  # lista tylko do ramki WhatsApp; zapiszemy przy następnym przebiegu
            if before is not None:
                self.state.set_meta("apps_pre_installed", sorted(before))
        prior = self.state.apps_status()
        for c in self.chosen:
            old = prior.get(c.package)
            if self.only_blocked:
                if old is None or old[:2] != ("skipped", "user_restricted"):
                    continue
                todo.append((c, False))
            elif old is None:
                todo.append((c, False))
            elif old[0] == "pending" or old[:2] == ("failed", "disconnected"):
                todo.append((c, True))
            elif old[:2] == ("failed", "no_consent"):
                # zgoda mogła przyjść po limicie czasu albo w starym oknie: pakiet jest -> zainstalowany
                try:
                    if self._present(c.package):
                        self._set(c.package, "installed")
                except AdbError:
                    pass

    def _one(self, c: AppCandidate, attempted: bool) -> None:
        if (self.blocked or self.plan.block == "xiaomi") and c.skip is None:
            if attempted and self._present(c.package):  # instalacja sprzed rozłączenia weszła
                self._set(c.package, "installed")
                return
            self.blocked = True
            self._set(c.package, "skipped", "user_restricted")
        elif c.skip == "installed":
            self._set(c.package, "installed" if attempted else "exists")
        elif c.skip is not None:
            self._set(c.package, "skipped", c.skip)
        elif self._install(c, attempted):
            self.blocked = True

    def _process(self, todo: list[tuple[AppCandidate, bool]], total: int, done: int) -> None:
        for c, attempted in todo:
            if self.should_stop():
                self.stopped = True
                return
            self.on_progress(AppsProgress("apps", done, total, c.label))
            try:
                self._one(c, attempted)
            except AdbError:  # polecenie nie przeszło, a telefon jest podłączony: ta jedna aplikacja, reszta dalej
                self._set(c.package, "failed", "failed")
            done += 1
        self.on_progress(AppsProgress("apps", done, total, ""))

    def _result(self) -> AppsResult:
        status = self.state.apps_status()
        rows: list[dict[str, Any]] = []
        installed = exists = 0
        skipped: Counter[str] = Counter()
        failed: Counter[str] = Counter()
        codes: Counter[str] = Counter()
        for c in self.chosen:
            st, reason, code = status.get(c.package, ("pending", None, None))
            if st == "installed":
                installed += 1
            elif st == "exists":
                exists += 1
            elif st == "skipped":
                skipped[reason or "unknown"] += 1
            elif st == "failed":
                failed[reason or "failed"] += 1
            if code and st in ("skipped", "failed"):
                codes[code] += 1
            rows.append({"package": c.package, "label": c.label, "status": st, "reason": reason})
        return AppsResult(len(self.chosen), installed, exists, dict(skipped), dict(failed), dict(codes),
                          self.blocked, self.stopped, rows,
                          self.sent > 0 and self.sent == self.sent_with_installer)


def run_install(adb: AppInstallAdb, device: DeviceInfo, copy: CopyDir, plan: AppsPlan,
                packages: frozenset[str], state: RestoreState, *, on_progress: Callable[[AppsProgress], None],
                should_stop: Callable[[], bool], wait_device: Callable[[], None],
                only_blocked: bool = False) -> AppsResult:
    """Instaluje wybrane `packages` z `plan` (alfabetycznie po etykiecie); wynik z końcowego stanu aplikacji."""
    return _Installer(adb, plan, packages, state, on_progress, should_stop, wait_device, only_blocked).run()
