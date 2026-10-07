from __future__ import annotations

from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.facts import AppFacts
from admenot.engine.parsers.common import UnrecognizedOutput, split_components
from admenot.engine.parsers.system import (
    parse_allowed_listeners,
    parse_device_admins,
    parse_resolved_home,
    parse_role_holders,
)

DEVICE_POLICY = "dumpsys device_policy"
ROLE_HOME = "cmd role get-role-holders android.app.role.HOME"
ROLE_BROWSER = "cmd role get-role-holders android.app.role.BROWSER"
ROLE_SMS = "cmd role get-role-holders android.app.role.SMS"
RESOLVE_HOME = ("cmd package resolve-activity --brief -a android.intent.action.MAIN "
                "-c android.intent.category.HOME")
A11Y_SERVICES = "settings get secure enabled_accessibility_services"
NOTIF_LISTENERS = "settings get secure enabled_notification_listeners"
# Stan NotificationManagera bez listy powiadomień: filtr na nieistniejący pakiet wycina
# powiadomienia (~100 linii zamiast ~12 tys.), sekcja „Allowed notification listeners” zostaje.
NOTIF_MANAGER = "dumpsys notification --package admenot.none"


class DevicePolicyCollector:
    name = "device_policy"

    def collect(self, adb: AdbTransport, apps: list[AppFacts]) -> set[str]:
        text = adb.shell(DEVICE_POLICY, timeout=30)
        if "Device Policy Manager" not in text:
            raise UnrecognizedOutput("dumpsys device_policy: unknown header")
        return parse_device_admins(text)

    def apply(self, facts: dict[str, AppFacts], data: set[str]) -> None:
        for f in facts.values():
            f.is_device_admin = f.package in data


class RolesCollector:
    name = "roles"

    def collect(self, adb: AdbTransport, apps: list[AppFacts]) -> dict[str, set[str]]:
        return {
            "home": self._home(adb),
            "browser": self._optional(adb, ROLE_BROWSER),
            "sms": self._optional(adb, ROLE_SMS),
        }

    @staticmethod
    def _home(adb: AdbTransport) -> set[str]:
        try:
            holders = parse_role_holders(adb.shell(ROLE_HOME))
            if holders:
                return holders
        except AdbError:
            pass  # Android < 10: brak `cmd role` — używamy resolve-activity
        return parse_resolved_home(adb.shell(RESOLVE_HOME))

    @staticmethod
    def _optional(adb: AdbTransport, command: str) -> set[str]:
        try:
            return parse_role_holders(adb.shell(command))
        except AdbError:
            return set()  # Android < 10 lub nagranie sprzed Planu 4

    def apply(self, facts: dict[str, AppFacts], data: dict[str, set[str]]) -> None:
        for f in facts.values():
            f.is_home_holder = f.package in data["home"]
            f.is_browser_holder = f.package in data["browser"]
            f.is_sms_holder = f.package in data["sms"]


class SecureSettingsCollector:
    name = "secure_settings"

    def collect(self, adb: AdbTransport, apps: list[AppFacts]) -> dict[str, set[str]]:
        return {
            "a11y": split_components(adb.shell(A11Y_SERVICES)),
            "listeners": self._listeners(adb),
        }

    @staticmethod
    def _listeners(adb: AdbTransport) -> set[str]:
        # Dostęp trzyma NotificationManager; kopia w ustawieniach potrafi się z nim rozjechać
        # (np. po `settings put`). To samo źródło co krok naprawy (steps.read_secure_list),
        # inaczej skan zgłaszałby dostęp, którego krok nie widzi i nie ma czego odebrać.
        try:
            approved = parse_allowed_listeners(adb.shell(NOTIF_MANAGER, timeout=30))
        except AdbError:
            approved = None  # nagranie sprzed tej zmiany: zostaje kopia
        if approved is not None:
            return split_components(":".join(approved))
        return split_components(adb.shell(NOTIF_LISTENERS))

    def apply(self, facts: dict[str, AppFacts], data: dict[str, set[str]]) -> None:
        for f in facts.values():
            f.accessibility_enabled = f.package in data["a11y"]
            f.notification_listener = f.package in data["listeners"]
