"""FakePhone — telefon ze stanem do testów akcji. Polecenia zapisu zmieniają wyniki odczytów.

Polecenia skanu, których FakePhone nie modeluje, bierze z `static` (jak FakeAdb.responses).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from conftest import SERIAL, SYNTHETIC_DEVICES, make_synthetic_adb

from admenot.engine.actions import commands as C
from admenot.engine.adb.transport import AdbError
from admenot.engine.collectors.components import HOME_QUERY
from admenot.engine.collectors.packages import PM_DISABLED, PM_SYSTEM
from admenot.engine.collectors.profiles import PM_USERS
from admenot.engine.collectors.system import DEVICE_POLICY, NOTIF_MANAGER, RESOLVE_HOME
from admenot.engine.device_checks import (
    APP_BROWSER_QUERY,
    APP_BROWSER_QUERY_PLAIN,
    BROWSER_QUERY,
    BROWSER_QUERY_PLAIN,
)

POST = "android.permission.POST_NOTIFICATIONS"
LISTENERS = "enabled_notification_listeners"
A11Y = "enabled_accessibility_services"
GEARHEAD = ("com.google.android.projection.gearhead/com.google.android.gearhead.notifications."
            "SharedNotificationListenerManager$ListenerService")
APK_DIR = "/data/app/~~fake==/{package}-1"
FSI_MIN_SDK = 34
FIREFOX_SOCKET = "org.mozilla.firefox/firefox-debugger-socket"
_CHANNEL_SCREEN = re.compile(
    re.escape(C.CHANNEL_SETTINGS).replace(r"\{package\}", r"(\S+)").replace(r"\{channel\}", r"(.*)"))
_HOME_HEADER ="priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\n"


@dataclass
class FakeApp:
    package: str
    system: bool = False
    installed: bool = True
    enabled: bool = True
    until_used: bool = False  # wyłączona = enabled=4 (DISABLED_UNTIL_USED), nie 3
    version_code: int = 1
    apks: tuple[str, ...] = ("base.apk",)
    appops: dict[str, str] = field(default_factory=dict)  # op → tryb; brak wpisu = "default"
    requested: set[str] = field(default_factory=set)
    granted: set[str] = field(default_factory=set)
    admin: bool = False
    home_activity: str | None = None  # np. ".Launcher": aplikacja jest kandydatem HOME
    keeps_apk: bool = False  # po `pm uninstall --user 0` APK zostaje (aplikacje systemowe)
    build: bytes = b""  # dopisywane do bajtów APK: przebudowana aplikacja z tym samym versionCode

    def apk(self, name: str) -> bytes:
        return apk_bytes(self.package, name) + self.build


def apk_bytes(package: str, name: str) -> bytes:
    return f"APK:{package}:{name}".encode()


def png_bytes(size: tuple[int, int] = (9, 16), color: tuple[int, int, int] = (30, 120, 200),
              dot: bool = True) -> bytes:
    """Mały PNG „ekranu”; `dot` dokłada biały piksel, żeby obraz nie był jednolity."""
    from PIL import Image

    image = Image.new("RGB", size, color)
    if dot:
        image.putpixel((0, 0), (255, 255, 255))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


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
        sha256sum: bool = False,
        listener_cmd: bool = True,
        firefox_debugging: bool = False,
    ) -> None:
        self.serial: str | None = serial
        self.sdk = sdk
        self.apps = {a.package: a for a in apps}
        self.secure = dict(secure or {})
        self.home = home  # komponent domyślnego launchera albo None
        self.static = dict(static or {})
        self.host = dict(host or {})
        self.sha256sum = sha256sum
        # Android 9+: dostęp do powiadomień trzyma NotificationManager, a ustawienie jest jego
        # kopią — `settings put` jej nie odbiera (OPPO CPH2271, 2026-10-07). Bez `listener_cmd`
        # (stary Android) ustawienie jest jedynym źródłem, a `cmd notification` go nie zna.
        self.listener_cmd = listener_cmd
        self.listeners_allowed: list[str] | None = (
            [c for c in self.secure.get(LISTENERS, "").split(":") if c] if listener_cmd else None)
        self.fail: dict[str, AdbError | str] = {}  # polecenie → wyjątek albo wyjście z kodem 0
        self.lose_response: set[str] = set()  # wykonuje się, ale odpowiedź ginie (odłączenie)
        self.disconnected = False
        self.on_admin_screen: Callable[[FakePhone], None] | None = None
        self.opened: list[str] = []
        self.calls: list[str] = []
        self.screen: bytes = png_bytes()
        self.firefox_debugging = firefox_debugging  # gniazdo zdalnego debugowania Firefoxa istnieje
        self.forwards: dict[int, str] = {}  # port hosta → gniazdo abstrakcyjne
        self.channels: dict[str, dict[str, int]] = {}  # pakiet → {id kanału: importance}
        self.channel_groups: dict[str, list[str]] = {}  # pakiet → id grup kanałów (Chromium: „sites”)
        self.browsers: list[str] = []  # pakiety otwierające dowolny link http
        self.app_browsers: list[str] = []  # MAIN + CATEGORY_APP_BROWSER: aplikacja deklaruje, że jest przeglądarką
        self.active: list[tuple[str, str, str, str | None]] = []  # (pakiet, kanał, tag, subText)
        self.firefox_perms: dict[str, int] = {}  # origin → capability (1 zezwól, 2 zablokuj)
        self.on_channel_screen: Callable[[FakePhone, str, str], None] | None = None

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
        if args[0] == "forward" and " ".join(args) not in self.host:
            return self._forward(args[1:])
        return self._answer(self.host, " ".join(args))

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        key = " ".join(args)
        self.calls.append("host-bytes:" + key)
        self._check_connected()
        if key in self.fail:
            value = self.fail[key]
            if isinstance(value, AdbError):
                raise value
            return value.encode()
        if key == "exec-out screencap -p":
            return self.screen
        raise AdbError("command_failed", f"FakePhone: no bytes for {key!r}")

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
        if command in (BROWSER_QUERY, BROWSER_QUERY_PLAIN):
            found = "".join(f"{_HOME_HEADER}  {p}/.Browser\n" for p in self.browsers)
            return found or "No activities found\n"
        if command in (APP_BROWSER_QUERY, APP_BROWSER_QUERY_PLAIN):
            found = "".join(f"{_HOME_HEADER}  {p}/.Main\n" for p in self.app_browsers)
            return found or "No activities found\n"
        if command == HOME_QUERY:
            found = "".join(f"{_HOME_HEADER}  {c}\n" for c in self._home_candidates())
            return found or "No activities found\n"
        if command == "cat /proc/net/unix":
            return self._proc_net_unix()
        if command == DEVICE_POLICY:
            return self._device_policy()
        if command == NOTIF_MANAGER:
            return self._notification_manager()
        if command == C.NOTIFICATIONS_FULL and command not in self.static:
            return self._notification_dump()
        if m := re.fullmatch(_CHANNEL_SCREEN, command):
            return self._open_channel(m[1], m[2].replace("'\"'\"'", "'"))
        if command in (C.ADMIN_SETTINGS, C.SECURITY_SETTINGS):
            return self._open(command)
        if re.fullmatch(r"am force-stop \S+", command):
            return ""
        if m := re.fullmatch(r"appops get --user 0 (\S+) (\w+)", command):
            return self._appops_get(m[1], m[2])
        if m := re.fullmatch(r"appops set --user 0 (\S+) (\w+) (\w+)", command):
            return self._appops_set(m[1], m[2], m[3])
        if m := re.fullmatch(r"pm (grant|revoke) --user 0 (\S+) (\S+)", command):
            return self._permission(m[1], m[2], m[3])
        if (m := re.fullmatch(r"dumpsys package (\S+)", command)) and m[1] != "packages":
            return self._dumpsys_package(m[1])
        if m := re.fullmatch(r"settings get --user 0 secure (\S+)", command):
            return self.secure.get(m[1], "null") + "\n"
        if m := re.fullmatch(r"settings put --user 0 secure (\S+) (.+)", command):
            self.secure[m[1]] = _sh_word(m[2])
            return ""
        if m := re.fullmatch(r"cmd notification (allow|disallow)_listener (.+) 0", command):
            return self._listener(m[1] == "allow", _sh_word(m[2]))
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
        if self.sha256sum and command.startswith("sha256sum "):
            return self._sha256(shlex.split(command)[1:])
        return None

    def _proc_net_unix(self) -> str:
        rows = ["Num       RefCount Protocol Flags    Type St Inode Path",
                "0000000000000000: 00000002 00000000 00010000 0001 01 12345 /dev/socket/zygote"]
        if self.firefox_debugging:
            rows.append(f"0000000000000000: 00000002 00000000 00010000 0001 01 23456 @{FIREFOX_SOCKET}")
        return "\n".join(rows) + "\n"

    def _forward(self, args: list[str]) -> str:
        if len(args) == 2 and args[0] == "--remove":
            port = int(args[1].removeprefix("tcp:"))
            if port not in self.forwards:
                raise AdbError("command_failed", f"listener 'tcp:{port}' not found")
            del self.forwards[port]
            return ""
        if len(args) == 2 and args[0] == "tcp:0" and args[1].startswith("localabstract:"):
            port = 40000 + len(self.forwards)
            while port in self.forwards:
                port += 1
            self.forwards[port] = args[1].removeprefix("localabstract:")
            return f"{port}\n"
        raise AdbError("command_failed", f"FakePhone: unsupported forward {' '.join(args)!r}")

    def _sha256(self, remotes: list[str]) -> str:
        lines = []
        for remote in remotes:
            for app in self._present():
                prefix = APK_DIR.format(package=app.package) + "/"
                name = remote[len(prefix):]
                if remote.startswith(prefix) and name in app.apks:
                    digest = hashlib.sha256(app.apk(name)).hexdigest()
                    lines.append(f"{digest}  {remote}\n")
        return "".join(lines)

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
                f"    User 0: ceDataInode=1 installed=true enabled={0 if app.enabled else 4 if app.until_used else 3}\n"
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
        app.enabled, app.until_used = enabled, False
        if not enabled:
            self._forget_home(package)
        return f"Package {package} new state: {'enabled' if enabled else 'disabled-user'}\n"

    def _listener(self, allow: bool, component: str) -> str:
        if self.listeners_allowed is None:
            return f"Unknown command: {'allow' if allow else 'disallow'}_listener\n"
        if "/" not in component:
            return "Invalid listener - must be a ComponentName\n"
        if allow and component not in self.listeners_allowed:
            self.listeners_allowed.append(component)
        if not allow and component in self.listeners_allowed:
            self.listeners_allowed.remove(component)
        self.secure[LISTENERS] = ":".join(self.listeners_allowed)  # system odświeża kopię
        return ""

    def _notification_manager(self) -> str:
        head = "Current Notification Manager state (filtered to 'admenot.none'):\n  Notification List:\n"
        if self.listeners_allowed is None:
            return head  # stary Android: bez sekcji zatwierdzonych słuchaczy
        return (head + "  Notification listeners:\n    Allowed notification listeners:\n"
                f"      {':'.join(self.listeners_allowed)} (user: 0 isPrimary: true)\n"
                "    Has user set:\n")

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

    def _notification_dump(self) -> str:
        """`dumpsys notification --noredact` w formacie z nagrań (tests/data/site_notifications)."""
        lines = ["Current Notification Manager state:", "  Notification List:"]
        for package, channel, tag, sub_text in self.active:
            lines.append(f"    NotificationRecord(0x1: pkg={package} user=UserHandle{{0}} id=1 tag={tag or 'null'} "
                         f"importance=3 key=0|{package}|1|{tag}|10100: Notification(channel={channel} "
                         "shortcut=null flags=0x10)")
            lines.append("      uid=10100 userId=0")
            if sub_text is not None:
                lines.append(f"        android.subText=String ({sub_text})")
        lines += ["", " Notification Preferences:", "    per-package config:", "PackagePreferences:"]
        for package, channels in self.channels.items():
            lines.append(f"      AppSettings: {package} (10113)")
            for channel_id, importance in channels.items():
                lines.append(f"        NotificationChannel{{mId='{channel_id}', mName={channel_id}, "
                             f"mDescription=, mImportance={importance}, mBypassDnd=false}}")
            for group in self.channel_groups.get(package, []):
                lines.append(f"        NotificationChannelGroup{{mId='{group}', mName={group}, mDescription=, "
                             "mBlocked=false, mChannels=[], mUserLockedFields=0}")
        return "\n".join(lines) + "\n"

    def _open_channel(self, package: str, channel_id: str) -> str:
        self.opened.append(C.CHANNEL_SETTINGS.format(package=package, channel=C.quoted(channel_id)))
        if self.on_channel_screen:
            self.on_channel_screen(self, package, channel_id)
        return "Starting: Intent { act=android.settings.CHANNEL_NOTIFICATION_SETTINGS }\n"

    def rdp_connect(self, port: int) -> FakeRdp:
        """Połączenie z przekierowanym portem: bez gniazda Firefoxa nikt nie nasłuchuje."""
        if not self.firefox_debugging:
            raise ConnectionRefusedError(f"nothing listens on {port}")
        return FakeRdp(perms=self.firefox_perms).connect(port)

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
        app.installed, app.enabled = True, True  # nowy stan użytkownika: domyślnie włączona
        return f"Package {package} installed for user: 0\n"

    def _pull(self, remote: str, local: Path) -> str:
        for app in self._present():
            prefix = APK_DIR.format(package=app.package) + "/"
            name = remote[len(prefix):]
            if remote.startswith(prefix) and name in app.apks:
                local.write_bytes(app.apk(name))
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


class FakeRdp:
    """Fałszywy serwer RDP Firefoxa: `connect(port)` zwraca strumień (ten sam obiekt).

    Odpowiada powitaniem, deskryptorem procesu, celem i `evaluationResult`. Skrypty z szablonów
    firefox_rdp liczy na słowniku `perms` (origin → capability); inny skrypt to wyjątek JS.
    `results` (kolejka gotowych wyników) ma pierwszeństwo przed `perms`.
    """

    def __init__(self, results: list[str] | None = None, *, perms: dict[str, int] | None = None,
                 chunk: int | None = None, closes_at: str | None = None,
                 exception: str | None = None, long_string: bool = False) -> None:
        self.results = list(results) if results is not None else None
        self.perms = perms if perms is not None else {}
        self.chunk = chunk  # tyle bajtów najwyżej na jedno recv()
        self.closes_at = closes_at  # "connect" | "eval": połączenie znika bez odpowiedzi
        self.exception = exception  # evaluationResult z hasException
        self.long_string = long_string  # wynik jako longString z aktorem substring
        self.port: int | None = None
        self.sent: list[dict] = []
        self.scripts: list[str] = []
        self.closed = False
        self._out = b""
        self._in = b""
        self._long = ""

    def connect(self, port: int) -> FakeRdp:
        self.port = port
        if self.closes_at != "connect":
            self._reply({"from": "root", "applicationType": "browser", "traits": {}})
        return self

    def settimeout(self, timeout: float) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def sendall(self, data: bytes) -> None:
        self._in += data
        while b":" in self._in:
            head, rest = self._in.split(b":", 1)
            if len(rest) < int(head):
                return
            self._in = rest[int(head):]
            packet = json.loads(rest[:int(head)])
            self.sent.append(packet)
            self._handle(packet)

    def recv(self, size: int) -> bytes:
        if not self._out:
            if self.closes_at:
                return b""
            raise TimeoutError("FakeRdp: nothing to read")
        n = min(size, self.chunk or size)
        data, self._out = self._out[:n], self._out[n:]
        return data

    def _reply(self, packet: dict) -> None:
        raw = json.dumps(packet).encode()
        self._out += str(len(raw)).encode() + b":" + raw

    def _handle(self, packet: dict) -> None:
        to, kind = packet["to"], packet["type"]
        if to == "root" and kind == "getProcess":
            self._reply({"from": "root", "processDescriptor": {"actor": "proc1", "id": 0}})
        elif to == "proc1" and kind == "getTarget":
            self._reply({"from": "proc1", "process": {"actor": "target1", "consoleActor": "console1"}})
        elif to == "console1" and kind == "evaluateJSAsync":
            self.scripts.append(packet["text"])
            if self.closes_at == "eval":
                return
            self._reply({"from": "console1", "resultID": "1-0"})
            self._reply({"from": "console1", "type": "evaluationResult", "resultID": "1-0",
                         "input": packet["text"], **self._evaluate(packet["text"])})
        elif to == "long1" and kind == "substring":
            self._reply({"from": "long1", "substring": self._long[packet["start"]:packet["end"]]})
        else:
            self._reply({"from": to, "error": "unrecognizedPacketType", "message": kind})

    def _evaluate(self, text: str) -> dict:
        if self.exception is not None:
            return {"hasException": True, "exceptionMessage": self.exception}
        if self.results is not None:
            result = self.results.pop(0)
        else:
            try:
                result = self._run_template(text)
            except ValueError as exc:
                return {"hasException": True, "exceptionMessage": str(exc)}
        if self.long_string:
            self._long = result
            return {"hasException": False, "result": {
                "type": "longString", "initial": result[:10], "length": len(result), "actor": "long1"}}
        return {"hasException": False, "result": result}

    def _run_template(self, text: str) -> str:
        from admenot.engine.browsers import firefox_rdp as R

        if text == R.READ_JS:
            return json.dumps([[o, c] for o, c in self.perms.items()])
        for template, store in ((R.ADD_JS, True), (R.REMOVE_JS, False)):
            head, rest = template.split("{origin}")
            pattern = re.escape(head) + r'(?P<origin>".*")' + re.escape(rest).replace(
                r"\{capability\}", r"(?P<cap>[12])")
            if m := re.fullmatch(pattern, text, re.DOTALL):
                origin = json.loads(m["origin"])
                if store:
                    self.perms[origin] = int(m["cap"])
                else:
                    self.perms.pop(origin, None)
                return "true"
        raise ValueError(f"ReferenceError: unexpected script {text[:80]!r}")


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
    phone = FakePhone(
        apps,
        sdk=34,
        serial=SERIAL,
        home=f"com.sec.android.app.launcher/{launcher}",
        secure={LISTENERS: "com.whatsapp/com.whatsapp.NotificationListener"},
        # Współczesny telefon odpowiada na `pm list users` (jeden profil) — nagrania mostu
        # nie pokazują więc ostrzeżenia o nieznanym zakresie profili (Plan 4b, przegląd M2).
        static={**make_synthetic_adb().responses,
                PM_USERS: "Users:\n\tUserInfo{0:Owner:c13} running\n"},
        host={"devices -l": SYNTHETIC_DEVICES},
    )
    # com.clean.pro.boost jest aktywnym administratorem: wyłączenie też jest blokowane, nie tylko usunięcie.
    phone.fail[C.PM_DISABLE.format(package="com.clean.pro.boost")] = AdbError(
        "command_failed", "java.lang.SecurityException: Cannot disable a device admin")
    return phone
