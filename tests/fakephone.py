"""FakePhone — telefon ze stanem do testów akcji. Polecenia zapisu zmieniają wyniki odczytów.

Polecenia skanu, których FakePhone nie modeluje, bierze z `static` (jak FakeAdb.responses).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from conftest import SERIAL, SYNTHETIC_DEVICES, make_synthetic_adb

from demalware.engine.actions import commands as C
from demalware.engine.adb.transport import AdbError
from demalware.engine.collectors.components import HOME_QUERY
from demalware.engine.collectors.packages import PM_DISABLED, PM_SYSTEM
from demalware.engine.collectors.system import DEVICE_POLICY, RESOLVE_HOME

POST = "android.permission.POST_NOTIFICATIONS"
LISTENERS = "enabled_notification_listeners"
A11Y = "enabled_accessibility_services"
GEARHEAD = ("com.google.android.projection.gearhead/com.google.android.gearhead.notifications."
            "SharedNotificationListenerManager$ListenerService")
APK_DIR = "/data/app/~~fake==/{package}-1"
FSI_MIN_SDK = 34
_HOME_HEADER = "priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\n"


@dataclass
class FakeApp:
    package: str
    system: bool = False
    installed: bool = True
    enabled: bool = True
    version_code: int = 1
    apks: tuple[str, ...] = ("base.apk",)
    appops: dict[str, str] = field(default_factory=dict)  # op → tryb; brak wpisu = "default"
    requested: set[str] = field(default_factory=set)
    granted: set[str] = field(default_factory=set)
    admin: bool = False
    home_activity: str | None = None  # np. ".Launcher": aplikacja jest kandydatem HOME
    keeps_apk: bool = False  # po `pm uninstall --user 0` APK zostaje (aplikacje systemowe)


def apk_bytes(package: str, name: str) -> bytes:
    return f"APK:{package}:{name}".encode()


def _sh_word(raw: str) -> str:
    """Jak powłoka telefonu czyta jedno słowo: '…' dosłownie, bez cudzysłowu $zmienne znikają."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    return re.sub(r"\$\w+", "", raw)


class FakePhone:
    def __init__(
        self,
        apps: list[FakeApp],
        *,
        sdk: int = 34,
        secure: dict[str, str] | None = None,
        home: str | None = None,
        serial: str = "FAKE",
        static: dict[str, str | AdbError] | None = None,
        host: dict[str, str | AdbError] | None = None,
    ) -> None:
        self.serial: str | None = serial
        self.sdk = sdk
        self.apps = {a.package: a for a in apps}
        self.secure = dict(secure or {})
        self.home = home  # komponent domyślnego launchera albo None
        self.static = dict(static or {})
        self.host = dict(host or {})
        self.fail: dict[str, AdbError | str] = {}  # polecenie → wyjątek albo wyjście z kodem 0
        self.lose_response: set[str] = set()  # wykonuje się, ale odpowiedź ginie (odłączenie)
        self.disconnected = False
        self.on_admin_screen: Callable[[FakePhone], None] | None = None
        self.opened: list[str] = []
        self.calls: list[str] = []

    def with_serial(self, serial: str) -> FakePhone:
        self.serial = serial
        return self

    # --- transport -------------------------------------------------------------------------

    def shell(self, command: str, timeout: float = 20.0) -> str:
        self.calls.append(command)
        self._check_connected()
        if command in self.fail:
            value = self.fail[command]
            if isinstance(value, AdbError):
                raise value
            return value
        out = self._dynamic(command)
        if out is None:
            out = self._answer(self.static, command)
        if command in self.lose_response:
            self.disconnected = True
            self._check_connected()
        return out

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        if args and args[0] == "shell":
            return self.shell(" ".join(args[1:]), timeout=timeout)
        self.calls.append("host:" + " ".join(args))
        self._check_connected()
        if args[0] == "pull" and len(args) == 3:
            return self._pull(args[1], Path(args[2]))
        if args[0] in ("install", "install-multiple"):
            return self._install([Path(a) for a in args[1:] if not a.startswith("-")])
        return self._answer(self.host, " ".join(args))

    def _check_connected(self) -> None:
        if self.disconnected:
            raise AdbError("no_device", f"device '{self.serial}' not found")

    @staticmethod
    def _answer(table: dict[str, str | AdbError], key: str) -> str:
        if key not in table:
            raise AdbError("command_failed", f"FakePhone: no response for {key!r}")
        value = table[key]
        if isinstance(value, AdbError):
            raise value
        return value

    # --- polecenia modelowane ---------------------------------------------------------------

    def _dynamic(self, command: str) -> str | None:
        if command == C.GETPROP_SDK:
            return f"{self.sdk}\n"
        if command == PM_SYSTEM:
            return self._list(a for a in self._present() if a.system)
        if command == PM_DISABLED:
            return self._list(a for a in self._present() if not a.enabled)
        if command == RESOLVE_HOME:
            return _HOME_HEADER + (self.home or "android/com.android.internal.app.ResolverActivity") + "\n"
        if command == HOME_QUERY:
            return "".join(f"{_HOME_HEADER}  {c}\n" for c in self._home_candidates())
        if command == DEVICE_POLICY:
            return self._device_policy()
        if command in (C.ADMIN_SETTINGS, C.SECURITY_SETTINGS):
            return self._open(command)
        if re.fullmatch(r"am force-stop \S+", command):
            return ""
        if m := re.fullmatch(r"appops get (\S+) (\w+)", command):
            return self._appops_get(m[1], m[2])
        if m := re.fullmatch(r"appops set (\S+) (\w+) (\w+)", command):
            return self._appops_set(m[1], m[2], m[3])
        if m := re.fullmatch(r"pm (grant|revoke) (\S+) (\S+)", command):
            return self._permission(m[1], m[2], m[3])
        if (m := re.fullmatch(r"dumpsys package (\S+)", command)) and m[1] != "packages":
            return self._dumpsys_package(m[1])
        if m := re.fullmatch(r"settings get secure (\S+)", command):
            return self.secure.get(m[1], "null") + "\n"
        if m := re.fullmatch(r"settings put secure (\S+) (.+)", command):
            self.secure[m[1]] = _sh_word(m[2])
            return ""
        if m := re.fullmatch(r"cmd package set-home-activity --user 0 (.+)", command):
            return self._set_home(_sh_word(m[1]))
        if m := re.fullmatch(r"pm disable-user --user 0 (\S+)", command):
            return self._set_enabled(m[1], False)
        if m := re.fullmatch(r"pm enable --user 0 (\S+)", command):
            return self._set_enabled(m[1], True)
        if m := re.fullmatch(r"pm list packages --user 0 (\S+)", command):
            return self._list(a for a in self._present() if m[1] in a.package)
        if m := re.fullmatch(r"pm path (\S+)", command):
            return self._pm_path(m[1])
        if m := re.fullmatch(r"pm uninstall --user 0 (\S+)", command):
            return self._uninstall(m[1])
        if m := re.fullmatch(r"cmd package install-existing --user 0 (\S+)", command):
            return self._install_existing(m[1])
        return None

    def _present(self) -> list[FakeApp]:
        return [a for a in self.apps.values() if a.installed]

    @staticmethod
    def _list(apps) -> str:
        return "".join(f"package:{a.package}\n" for a in apps)

    def _app(self, package: str) -> FakeApp:
        app = self.apps.get(package)
        if app is None or not app.installed:
            raise AdbError("command_failed", f"Error: Unknown package: {package}")
        return app

    def _check_op(self, op: str) -> None:
        if op == "USE_FULL_SCREEN_INTENT" and self.sdk < FSI_MIN_SDK:
            raise AdbError("command_failed", f"Error: Unknown operation string: {op}")

    def _appops_get(self, package: str, op: str) -> str:
        app = self._app(package)
        self._check_op(op)
        mode = app.appops.get(op)
        return "No operations.\nDefault mode: allow\n" if mode is None else f"{op}: {mode}\n"

    def _appops_set(self, package: str, op: str, mode: str) -> str:
        app = self._app(package)
        self._check_op(op)
        if mode == "default":
            app.appops.pop(op, None)
        else:
            app.appops[op] = mode
        return ""

    def _permission(self, action: str, package: str, permission: str) -> str:
        app = self._app(package)
        if permission not in app.requested:
            raise AdbError("command_failed",
                           f"Exception occurred while executing '{action}':\n"
                           f"java.lang.SecurityException: Package {package} has not requested "
                           f"permission {permission}")
        if action == "grant":
            app.granted.add(permission)
        else:
            app.granted.discard(permission)
        return ""

    def _dumpsys_package(self, package: str) -> str:
        app = self.apps.get(package)
        if app is None or not app.installed:
            return "Domain verification status:\nFailure printing domain verification information\n"
        perms = "".join(f"        {p}: granted={'true' if p in app.granted else 'false'}\n"
                        for p in sorted(app.requested))
        return ("Domain verification status:\nFailure printing domain verification information\n"
                "Packages:\n"
                f"  Package [{package}] (f00d):\n"
                f"    versionCode={app.version_code} minSdk=26 targetSdk=34\n"
                f"    User 0: ceDataInode=1 installed=true enabled={0 if app.enabled else 3}\n"
                "      runtime permissions:\n" + perms)

    def _home_candidates(self) -> list[str]:
        return [f"{a.package}/{a.home_activity}" for a in self._present()
                if a.enabled and a.home_activity]

    def _set_home(self, component: str) -> str:
        if component not in self._home_candidates():
            raise AdbError("command_failed", f"Error: component {component} not found")
        self.home = component
        return "Success\n"

    def _forget_home(self, package: str) -> None:
        if self.home and self.home.startswith(package + "/"):
            self.home = None

    def _set_enabled(self, package: str, enabled: bool) -> str:
        app = self._app(package)
        app.enabled = enabled
        if not enabled:
            self._forget_home(package)
        return f"Package {package} new state: {'enabled' if enabled else 'disabled-user'}\n"

    def _device_policy(self) -> str:
        admins = "".join(f"      {a.package}/.AdminReceiver:\n        uid=10001\n"
                         for a in self._present() if a.admin)
        return ("Current Device Policy Manager state:\n  User 0:\n"
                "    Enabled Device Admins (User 0, provisioningState: 0):\n"
                + admins + "    mPasswordOwner=-1\n")

    def _open(self, command: str) -> str:
        self.opened.append("admin" if command == C.ADMIN_SETTINGS else "security")
        if self.on_admin_screen:
            self.on_admin_screen(self)
        return "Starting: Intent { cmp=com.android.settings/.Settings }\n"

    def _pm_path(self, package: str) -> str:
        app = self._app(package)
        return "".join(f"package:{APK_DIR.format(package=package)}/{n}\n" for n in app.apks)

    def _uninstall(self, package: str) -> str:
        app = self._app(package)
        if app.admin:
            raise AdbError("command_failed", "Failure [DELETE_FAILED_DEVICE_POLICY_MANAGER]")
        app.installed = False
        self._forget_home(package)
        return "Success\n"

    def _install_existing(self, package: str) -> str:
        app = self.apps.get(package)
        if app is None or (not app.installed and not app.keeps_apk):
            raise AdbError("command_failed", f"Package {package} doesn't exist")
        app.installed = True
        return f"Package {package} installed for user: 0\n"

    def _pull(self, remote: str, local: Path) -> str:
        for app in self._present():
            prefix = APK_DIR.format(package=app.package) + "/"
            name = remote[len(prefix):]
            if remote.startswith(prefix) and name in app.apks:
                local.write_bytes(apk_bytes(app.package, name))
                return f"{remote}: 1 file pulled\n"
        raise AdbError("command_failed", f"remote object '{remote}' does not exist")

    def _install(self, files: list[Path]) -> str:
        packages = set()
        for f in files:
            if not f.exists():
                raise AdbError("command_failed", f"adb: failed to stat {f}")
            packages.add(f.read_bytes().decode().split(":")[1])
        if len(packages) != 1:
            raise AdbError("command_failed", "Failure [INSTALL_FAILED_INVALID_APK]")
        app = self.apps[packages.pop()]
        app.installed, app.enabled = True, True
        return "Success\n"


def make_cli_phone() -> FakePhone:
    """Syntetyczny Galaxy A14 z conftest, ale ze stanem: skan czyta ten sam telefon, który zmienia `fix`."""
    launcher = "com.android.launcher3.uioverrides.QuickstepLauncher"
    apps = [
        FakeApp("com.clean.pro.boost", version_code=7, admin=True,
                apks=("base.apk", "split_config.arm64_v8a.apk"),
                requested={POST}, granted={POST}, appops={"SYSTEM_ALERT_WINDOW": "allow"}),
        FakeApp("com.whatsapp", version_code=242000, requested={POST}, granted={POST}),
        FakeApp("com.wlive.forecast", version_code=31, requested={POST}, granted={POST}),
        FakeApp("com.sec.android.app.launcher", system=True, version_code=150000,
                home_activity=launcher, keeps_apk=True),
    ]
    return FakePhone(
        apps,
        sdk=34,
        serial=SERIAL,
        home=f"com.sec.android.app.launcher/{launcher}",
        secure={LISTENERS: "com.whatsapp/com.whatsapp.NotificationListener"},
        static=make_synthetic_adb().responses,
        host={"devices -l": SYNTHETIC_DEVICES},
    )
