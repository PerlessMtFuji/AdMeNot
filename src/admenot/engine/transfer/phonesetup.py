"""Zmiany nowego telefonu na czas zapisu telefonii i ich odwracanie (spec Etapu 3 §4, §6.2).

Program zmienia na nowym telefonie najwyżej cztery rzeczy: appop `WRITE_SMS` dla shell, posiadacza roli
SMS, zainstalowaną aplikację pomocniczą i katalog pomocnika `/data/local/tmp/admenot`. Każdą zapisuje
w meta `device_changes` stanu wgrywania (z commitem) **przed** poleceniem, które ją wprowadza, więc
po zamknięciu programu albo wyrwanym kablu `cleanup` przy następnym podłączeniu wie, co odwrócić.
`cleanup` jest idempotentne: każdy krok potwierdzony odczytem z telefonu czyści swoje pole.

Posiadacza roli SMS czytamy z `dumpsys role` (`cmd role get-role-holders` nie ma na Androidzie 13/MIUI).
Polecenia idą przez `guard.TelephonyWriteAdb` (`telephony_adb`), który przepuszcza oddanie roli tylko
zapisanemu poprzedniemu posiadaczowi.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from ..adb.transport import AdbError, AdbTransport
from . import helper
from .guard import _APPOP_MODES, SMS_ROLE, STAT_TAIL, TelephonyWriteAdb, q
from .restore_state import RestoreState, device_changes_pending, restore_state_path
from .store import CopyDir

TAP_POLL = 2  # s — odpytywanie roli, gdy czekamy na stuknięcie na telefonie
META_KEY = "device_changes"
APPOP_GET = "appops get com.android.shell WRITE_SMS"
INSTALL_TIMEOUT = 180.0
_CONNECTION_KINDS = {"offline", "no_device", "unauthorized", "adb_missing"}
_APPOP_LINE = re.compile(r"^\s*WRITE_SMS:\s*([a-z]+)")
_DEFAULT_MODE = re.compile(r"^\s*Default mode:\s*([a-z]+)")
_REFUSED = ("INSTALL_FAILED_", "Failure [", "canceled by user")
_sleep = time.sleep  # podmieniane w testach

OnTap = Callable[[str | None], None]  # "sms_role_grant" | "sms_role_restore" | None (koniec prośby)


@dataclass(frozen=True)
class DeviceChanges:
    """Zmiany telefonu do odwrócenia; `None`/`False` = nie zmienialiśmy (albo już odwrócone)."""

    appop_prev: str | None = None  # tryb `WRITE_SMS` shell sprzed zmiany (jawnie przywracany)
    role_prev: tuple[str, ...] | None = None  # posiadacze roli SMS sprzed zmiany; `()` = brak
    companion: bool = False  # aplikacja pomocnicza mogła zostać zainstalowana
    helper_dir: bool = False  # mogło powstać `/data/local/tmp/admenot`

    @property
    def pending(self) -> bool:
        return self != DeviceChanges()


@dataclass(frozen=True)
class CleanupResult:
    role_ok: bool
    appop_ok: bool
    companion_removed: bool
    helper_removed: bool

    @property
    def ok(self) -> bool:
        return self.role_ok and self.appop_ok and self.companion_removed and self.helper_removed


# --------------------------------------------------------------------------------------
# Stan
# --------------------------------------------------------------------------------------
def device_changes(state: RestoreState) -> DeviceChanges:
    raw = state.get_meta(META_KEY) or {}
    role = raw.get("role_prev")
    return DeviceChanges(raw.get("appop_prev"), None if role is None else tuple(role),
                         bool(raw.get("companion")), bool(raw.get("helper_dir")))


def _save(state: RestoreState, changes: DeviceChanges) -> None:
    state.set_meta(META_KEY, asdict(changes))  # `set_meta` robi commit


def _update(state: RestoreState, **fields) -> None:
    _save(state, replace(device_changes(state), **fields))


def mark_helper_dir(state: RestoreState) -> None:
    """Przed pierwszym `mkdir -p` katalogu pomocnika (`AppProcessWriter`)."""
    if not device_changes(state).helper_dir:
        _update(state, helper_dir=True)


def telephony_adb(inner: AdbTransport, state: RestoreState) -> TelephonyWriteAdb:
    """Strażnik zapisu telefonii: oddać rolę SMS wolno tylko zapisanemu poprzedniemu posiadaczowi."""
    return TelephonyWriteAdb(inner, role_restore=lambda: frozenset(device_changes(state).role_prev or ()))


def pending_cleanup(copies: list[CopyDir], serial: str) -> list[Path]:
    """Stany wgrywania tego telefonu, w których zostały zmiany telefonu do odwrócenia."""
    paths = [restore_state_path(c, serial) for c in copies]
    return [p for p in paths if device_changes_pending(p)]


# --------------------------------------------------------------------------------------
# Odczyty
# --------------------------------------------------------------------------------------
def parse_role_holders(dumpsys: str, role: str = SMS_ROLE) -> tuple[str, ...]:
    """Posiadacze roli z `dumpsys role`: sekcja `name=<rola>` (pierwszy użytkownik), linie `holders=`."""
    holders: list[str] = []
    inside = False
    for raw in dumpsys.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if line.startswith("name="):
            if inside:
                break
            inside = line == f"name={role}"
        elif inside and line.startswith("}"):
            break
        elif inside and line.startswith("holders="):
            holders += [h.strip() for h in line.removeprefix("holders=").split(",") if h.strip()]
    return tuple(holders)


def sms_role_holders(adb: AdbTransport) -> tuple[str, ...]:
    return parse_role_holders(adb.shell("dumpsys role", timeout=30))


def read_appop(adb: AdbTransport) -> str:
    """Tryb `WRITE_SMS` shell: wpis `WRITE_SMS: <tryb>`, a bez wpisu („No operations.”) tryb domyślny
    z linii `Default mode:` (OPPO: `ignore`); `default` tylko, gdy nie ma żadnej z nich."""
    default = None
    for line in adb.shell(APPOP_GET).replace("\r\n", "\n").split("\n"):
        if m := _APPOP_LINE.match(line):
            return m.group(1)
        if default is None and (m := _DEFAULT_MODE.match(line)):
            default = m.group(1)
    return default or "default"


def _installed(adb: AdbTransport) -> bool:
    out = adb.shell(f"pm list packages {helper.PACKAGE}")
    return any(line.strip() == f"package:{helper.PACKAGE}" for line in out.splitlines())


def _connection(exc: AdbError) -> bool:
    return exc.kind in _CONNECTION_KINDS


# --------------------------------------------------------------------------------------
# Zmiany
# --------------------------------------------------------------------------------------
def set_appop_allow(adb: AdbTransport, state: RestoreState) -> None:
    """`WRITE_SMS` shell na `allow` (droga `app_process` dla SMS/MMS); poprzedni tryb zapisany przed
    zmianą. Przy wznowieniu zapisany tryb zostaje (odczyt pokazywałby już nasze `allow`)."""
    if device_changes(state).appop_prev is None:
        prev = read_appop(adb)
        if prev not in _APPOP_MODES:
            raise AdbError("command_failed", f"unexpected appop mode: {prev[:40]}")
        _update(state, appop_prev=prev)
    adb.shell("appops set com.android.shell WRITE_SMS allow")


def install_companion(adb: AdbTransport, state: RestoreState) -> Literal["ok", "blocked"]:
    """Instaluje aplikację pomocniczą (`install -g`: uprawnienia od razu). APK sprawdzany najpierw na
    komputerze (`HelperBroken` przy złym SHA-256). Pozostałość po awarii najpierw odinstalowana.
    `blocked`: telefon odmówił instalacji (np. Xiaomi bez „Instaluj przez USB”)."""
    apk, _ = helper.artifact("apk")
    if not device_changes(state).companion:
        _update(state, companion=True)
    if _installed(adb):
        adb.shell(f"pm uninstall {helper.PACKAGE}")
    try:
        out = adb.run(["install", "-g", str(apk)], timeout=INSTALL_TIMEOUT)
    except AdbError as exc:
        if not _connection(exc) and any(m in exc.message for m in _REFUSED):
            return "blocked"
        raise
    if any(m in out for m in _REFUSED) or not _installed(adb):
        return "blocked"
    return "ok"


def take_sms_role(adb: AdbTransport, state: RestoreState, on_tap: OnTap, should_stop: Callable[[], bool],
                  skip_tap: Callable[[], bool]) -> Literal["ok", "skipped"]:
    """Aplikacja pomocnicza jako domyślna aplikacja SMS. Poprzedni posiadacz zapisany przed zmianą (przy
    wznowieniu zostaje zapisany wcześniej). Gdy `add-role-holder` nie wystarcza, systemowe okno
    i czekanie na stuknięcie co `TAP_POLL` s; `skip_tap()` (albo `should_stop()`) -> `skipped`."""
    if device_changes(state).role_prev is None:
        _update(state, role_prev=tuple(h for h in sms_role_holders(adb) if h != helper.PACKAGE))
    try:
        try:
            adb.shell(f"cmd role add-role-holder {SMS_ROLE} {helper.PACKAGE}")
        except AdbError as exc:
            if _connection(exc):
                raise
        if helper.PACKAGE in sms_role_holders(adb):
            return "ok"
        adb.shell(f"am start -n {helper.PACKAGE}/.RoleActivity")
        on_tap("sms_role_grant")
        while True:
            if skip_tap() or should_stop():
                return "skipped"
            _sleep(TAP_POLL)
            if helper.PACKAGE in sms_role_holders(adb):
                return "ok"
    finally:
        on_tap(None)


# --------------------------------------------------------------------------------------
# Sprzątanie
# --------------------------------------------------------------------------------------
def _role_restored(holders: tuple[str, ...], prev: tuple[str, ...]) -> bool:
    if helper.PACKAGE in holders:
        return False
    return not prev or prev[0] in holders


def _restore_role(adb: AdbTransport, state: RestoreState, on_tap: OnTap,
                  should_stop: Callable[[], bool]) -> bool:
    prev = device_changes(state).role_prev
    if prev is None:
        return True
    try:
        try:
            adb.shell(f"cmd role add-role-holder {SMS_ROLE} {prev[0]}" if prev
                      else f"cmd role remove-role-holder {SMS_ROLE} {helper.PACKAGE}")
        except AdbError as exc:
            if _connection(exc):
                return False
        if not _role_restored(sms_role_holders(adb), prev):
            adb.shell("am start -a android.settings.MANAGE_DEFAULT_APPS_SETTINGS")
            on_tap("sms_role_restore")
            try:
                while True:  # bez limitu (wariant B): zadanie nie kończy się przed przywróceniem roli
                    if should_stop():
                        return False
                    _sleep(TAP_POLL)
                    if _role_restored(sms_role_holders(adb), prev):
                        break
            finally:
                on_tap(None)
    except AdbError:
        return False
    _update(state, role_prev=None)
    return True


def _restore_appop(adb: AdbTransport, state: RestoreState) -> bool:
    prev = device_changes(state).appop_prev
    if prev is None:
        return True
    if prev not in _APPOP_MODES:
        return False
    try:
        adb.shell(f"appops set com.android.shell WRITE_SMS {prev}")
        if read_appop(adb) != prev:
            return False
    except AdbError:
        return False
    _update(state, appop_prev=None)
    return True


def _remove_companion(adb: AdbTransport, state: RestoreState, role_ok: bool) -> bool:
    if not device_changes(state).companion:
        return True
    if not role_ok:  # odinstalowanie posiadacza roli oddałoby ją systemowi, nie poprzedniej aplikacji
        return False
    try:
        if _installed(adb):
            adb.shell(f"pm uninstall {helper.PACKAGE}")
            if _installed(adb):
                return False
    except AdbError:
        return False
    _update(state, companion=False)
    return True


def _remove_helper_dir(adb: AdbTransport, state: RestoreState) -> bool:
    if not device_changes(state).helper_dir:
        return True
    try:
        adb.shell(f"rm -rf {helper.HELPER_DIR}")
        out = adb.shell("stat -c " + q("%s|%Y|%n") + " " + q(helper.HELPER_DIR) + STAT_TAIL)
    except AdbError:
        return False
    if "No such file or directory" not in out:
        return False
    _update(state, helper_dir=False)
    return True


def cleanup(adb: AdbTransport, state: RestoreState, on_tap: OnTap,
            should_stop: Callable[[], bool]) -> CleanupResult:
    """Odwraca zapisane zmiany: rola SMS (czekanie na stuknięcie bez limitu, przerywane `should_stop`),
    appop, odinstalowanie aplikacji pomocniczej (dopiero po potwierdzonej roli), katalog pomocnika.
    Nieudany krok zostawia swoje pole w `device_changes` do następnego podłączenia."""
    role_ok = _restore_role(adb, state, on_tap, should_stop)
    return CleanupResult(role_ok, _restore_appop(adb, state), _remove_companion(adb, state, role_ok),
                         _remove_helper_dir(adb, state))
