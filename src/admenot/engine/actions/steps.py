"""Kroki akcji. Każdy rodzaj kroku umie: odczytać stan, sprawdzić, czy cel jest osiągnięty,
wykonać zmianę i opisać krok odwrotny na podstawie stanu sprzed zmiany."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from admenot.engine.actions import commands as C
from admenot.engine.actions.backup import backup_apks, is_complete
from admenot.engine.actions.errors import ActionError, classify, from_adb, looks_failed
from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.collectors.packages import PM_DISABLED
from admenot.engine.collectors.system import DEVICE_POLICY, RESOLVE_HOME
from admenot.engine.parsers.appops import parse_appops
from admenot.engine.parsers.common import parse_package_list
from admenot.engine.parsers.packages import parse_dumpsys_packages
from admenot.engine.parsers.system import parse_device_admins, parse_resolved_component

State = dict[str, Any]


@dataclass
class Step:
    kind: str
    package: str
    params: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "package": self.package, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Step:
        return cls(data["kind"], data["package"], dict(data.get("params") or {}))


def read(adb: AdbTransport, command: str, timeout: float = 20.0) -> str:
    try:
        return adb.shell(command, timeout=timeout)
    except AdbError as exc:
        raise from_adb(exc) from exc


def run_checked(adb: AdbTransport, command: str, timeout: float = 20.0) -> str:
    out = read(adb, command, timeout)
    if looks_failed(out):
        raise ActionError(classify(out), out.strip())
    return out


def split_items(value: str) -> list[str]:
    value = value.strip()
    if not value or value == "null":
        return []
    return [item for item in value.split(":") if item]


def _flag(value: bool) -> str:
    return "1" if value else "0"


class StepHandler(Protocol):
    def probe(self, adb: AdbTransport, step: Step) -> State: ...

    def applied(self, step: Step, state: State) -> bool: ...

    def command(self, step: Step) -> str: ...

    def apply(self, adb: AdbTransport, step: Step, cache: Path | None) -> None: ...

    def inverse(self, step: Step, state: State) -> Step | None: ...


class _Simple:
    """Krok, którego wykonanie to jedno polecenie z `command()`."""

    def apply(self, adb: AdbTransport, step: Step, cache: Path | None) -> None:
        run_checked(adb, self.command(step))

    def command(self, step: Step) -> str:
        raise NotImplementedError


class _ForceStop(_Simple):
    def probe(self, adb: AdbTransport, step: Step) -> State:
        return {}

    def applied(self, step: Step, state: State) -> bool:
        return False

    def command(self, step: Step) -> str:
        return C.FORCE_STOP.format(package=step.package)

    def inverse(self, step: Step, state: State) -> Step | None:
        return None


class _AppOp(_Simple):
    def probe(self, adb: AdbTransport, step: Step) -> State:
        op = step.params["op"]
        ops = parse_appops(run_checked(adb, C.APPOPS_GET_OP.format(package=step.package, op=op)))
        return {"mode": ops[op].mode if op in ops else "default"}  # „No operations.” = default

    def applied(self, step: Step, state: State) -> bool:
        return state["mode"] == step.params["mode"]

    def command(self, step: Step) -> str:
        return C.APPOPS_SET.format(package=step.package, **step.params)

    def inverse(self, step: Step, state: State) -> Step | None:
        return Step("appop", step.package, {"op": step.params["op"], "mode": state["mode"]})


class _Permission(_Simple):
    def probe(self, adb: AdbTransport, step: Step) -> State:
        # Bez run_checked: dumpsys package wypisuje „Failure printing domain verification…” zawsze.
        dumps = parse_dumpsys_packages(read(adb, C.DUMPSYS_PACKAGE.format(package=step.package), 30))
        dump = dumps.get(step.package)
        return {"granted": bool(dump and step.params["permission"] in dump.granted)}

    def applied(self, step: Step, state: State) -> bool:
        return _flag(state["granted"]) == step.params["granted"]

    def command(self, step: Step) -> str:
        template = C.PM_GRANT if step.params["granted"] == "1" else C.PM_REVOKE
        return template.format(package=step.package, permission=step.params["permission"])

    def inverse(self, step: Step, state: State) -> Step | None:
        return Step("permission", step.package,
                    {"permission": step.params["permission"], "granted": _flag(state["granted"])})


class _SecureList:
    """Lista komponentów w `settings secure` (ułatwienia dostępu, nasłuch powiadomień)."""

    def probe(self, adb: AdbTransport, step: Step) -> State:
        return {"value": read(adb, C.SETTINGS_GET.format(key=step.params["key"])).strip()}

    def applied(self, step: Step, state: State) -> bool:
        items = set(split_items(state["value"]))
        wanted = set(split_items(step.params["components"]))
        return not (items & wanted) if step.params["op"] == "remove" else wanted <= items

    def command(self, step: Step) -> str:
        sign = "-" if step.params["op"] == "remove" else "+"
        return f"settings put secure {step.params['key']} ({sign}{step.params['components']})"

    def apply(self, adb: AdbTransport, step: Step, cache: Path | None) -> None:
        key = step.params["key"]
        items = split_items(self.probe(adb, step)["value"])
        wanted = split_items(step.params["components"])
        if step.params["op"] == "remove":
            new = [i for i in items if i not in wanted]
        else:
            new = items + [w for w in wanted if w not in items]
        value = ":".join(new)
        if "'" in value:
            raise ActionError("failed", f"unexpected quote in {key}")
        run_checked(adb, C.SETTINGS_PUT.format(key=key, value=value))

    def inverse(self, step: Step, state: State) -> Step | None:
        before = split_items(state["value"])
        wanted = split_items(step.params["components"])
        if step.params["op"] == "remove":
            op, changed = "add", [w for w in wanted if w in before]
        else:
            op, changed = "remove", [w for w in wanted if w not in before]
        if not changed:
            return None
        return Step("secure_list", step.package,
                    {"key": step.params["key"], "op": op, "components": ":".join(changed)})


class _Home(_Simple):
    def probe(self, adb: AdbTransport, step: Step) -> State:
        return {"component": parse_resolved_component(run_checked(adb, RESOLVE_HOME))}

    def applied(self, step: Step, state: State) -> bool:
        current = state["component"]
        return current is not None and (
            current.split("/")[0] == step.params["component"].split("/")[0])

    def command(self, step: Step) -> str:
        return C.SET_HOME.format(component=step.params["component"])

    def inverse(self, step: Step, state: State) -> Step | None:
        previous = state["component"]
        return Step("home", step.package, {"component": previous}) if previous else None


class _Enabled(_Simple):
    def probe(self, adb: AdbTransport, step: Step) -> State:
        disabled = parse_package_list(run_checked(adb, PM_DISABLED))
        return {"enabled": step.package not in disabled}

    def applied(self, step: Step, state: State) -> bool:
        return _flag(state["enabled"]) == step.params["enabled"]

    def command(self, step: Step) -> str:
        template = C.PM_ENABLE if step.params["enabled"] == "1" else C.PM_DISABLE
        return template.format(package=step.package)

    def inverse(self, step: Step, state: State) -> Step | None:
        return Step("enabled", step.package, {"enabled": _flag(state["enabled"])})


class _Backup:
    """Kopia APK na komputerze. Nie zmienia telefonu, więc nie ma kroku odwrotnego."""

    def probe(self, adb: AdbTransport, step: Step) -> State:
        return {"complete": is_complete(Path(step.params["dir"]))}

    def applied(self, step: Step, state: State) -> bool:
        # Bez versionCode nie wiadomo, czy kopia jest z tej wersji — pobieramy zawsze.
        return state["complete"] and bool(step.params.get("version_code"))

    def command(self, step: Step) -> str:
        return f"backup {step.package} -> {step.params['dir']}"

    def apply(self, adb: AdbTransport, step: Step, cache: Path | None) -> None:
        version = step.params.get("version_code")
        try:
            backup_apks(adb, step.package, int(version) if version else None,
                        Path(step.params["dir"]), cache)
        except AdbError as exc:
            error = from_adb(exc)
            raise (error if error.uncertain else ActionError("backup_failed", exc.message)) from exc
        except OSError as exc:
            raise ActionError("backup_failed", str(exc)) from exc

    def inverse(self, step: Step, state: State) -> Step | None:
        return None


def _install_from_backup(adb: AdbTransport, directory: Path) -> None:
    if not is_complete(directory):
        raise ActionError("no_backup", str(directory))
    apks = [str(p) for p in sorted(directory.glob("*.apk"))]
    args = ["install", apks[0]] if len(apks) == 1 else ["install-multiple", *apks]
    try:
        out = adb.run(args, timeout=C.INSTALL_TIMEOUT)
    except AdbError as exc:
        raise from_adb(exc) from exc
    if "Success" not in out:
        raise ActionError(classify(out), out.strip())


class _Installed:
    def probe(self, adb: AdbTransport, step: Step) -> State:
        listed = parse_package_list(run_checked(adb, C.PM_INSTALLED.format(package=step.package)))
        installed = step.package in listed  # filtr pm to podciąg — liczy się dokładna nazwa
        state: State = {"installed": installed}
        if installed:  # ponowna instalacja włącza aplikację — zapamiętujemy, czy była wyłączona
            state["enabled"] = step.package not in parse_package_list(run_checked(adb, PM_DISABLED))
        return state

    def applied(self, step: Step, state: State) -> bool:
        if _flag(state["installed"]) != step.params["installed"]:
            return False
        wanted = step.params.get("enabled")
        return wanted is None or not state["installed"] or _flag(state["enabled"]) == wanted

    def command(self, step: Step) -> str:
        template = C.PM_INSTALL_EXISTING if step.params["installed"] == "1" else C.PM_UNINSTALL
        return template.format(package=step.package)

    def apply(self, adb: AdbTransport, step: Step, cache: Path | None) -> None:
        if step.params["installed"] == "0":
            out = run_checked(adb, C.PM_UNINSTALL.format(package=step.package))
            if "Success" not in out:
                raise ActionError(classify(out), out.strip())
            return
        if not self.probe(adb, step)["installed"]:
            self._reinstall(adb, step)
        if step.params.get("enabled") == "0":  # była wyłączona przed naprawą
            run_checked(adb, C.PM_DISABLE.format(package=step.package))

    def _reinstall(self, adb: AdbTransport, step: Step) -> None:
        try:
            out = run_checked(adb, C.PM_INSTALL_EXISTING.format(package=step.package))
            if "installed for user" in out:
                return
        except ActionError as exc:
            if exc.uncertain:
                raise
        _install_from_backup(adb, Path(step.params["backup_dir"]))  # APK zniknął razem z aplikacją

    def inverse(self, step: Step, state: State) -> Step | None:
        params = {"installed": _flag(state["installed"]), "backup_dir": step.params["backup_dir"]}
        if state.get("enabled") is False:
            params["enabled"] = "0"
        return Step("installed", step.package, params)


class _Admin:
    """Odebranie uprawnień administratora (spec §7.2). ADB tylko otwiera ekran — decyduje
    dotknięcie „Dezaktywuj” na telefonie. Uprawnień nie da się przywrócić, więc brak odwrotności."""

    def probe(self, adb: AdbTransport, step: Step) -> State:
        return {"admin": step.package in parse_device_admins(read(adb, DEVICE_POLICY, 30))}

    def applied(self, step: Step, state: State) -> bool:
        return not state["admin"]

    def command(self, step: Step) -> str:
        return C.ADMIN_SETTINGS

    def apply(self, adb: AdbTransport, step: Step, cache: Path | None) -> None:
        try:
            run_checked(adb, C.ADMIN_SETTINGS)
        except ActionError as exc:
            if exc.uncertain:
                raise
            run_checked(adb, C.SECURITY_SETTINGS)  # nakładka producenta bez tego ekranu

    def inverse(self, step: Step, state: State) -> Step | None:
        return None


HANDLERS: dict[str, StepHandler] = {
    "force_stop": _ForceStop(),
    "appop": _AppOp(),
    "permission": _Permission(),
    "secure_list": _SecureList(),
    "home": _Home(),
    "enabled": _Enabled(),
    "backup": _Backup(),
    "installed": _Installed(),
    "admin": _Admin(),
}


def _handler(step: Step) -> StepHandler:
    try:
        return HANDLERS[step.kind]
    except KeyError:
        raise ValueError(f"unknown step kind: {step.kind!r}") from None


def probe(adb: AdbTransport, step: Step) -> State:
    return _handler(step).probe(adb, step)


def is_applied(step: Step, state: State) -> bool:
    return _handler(step).applied(step, state)


def command_for(step: Step) -> str:
    return _handler(step).command(step)


def apply(adb: AdbTransport, step: Step, apk_cache_dir: Path | None = None) -> None:
    _handler(step).apply(adb, step, apk_cache_dir)


def inverse(step: Step, state: State) -> Step | None:
    return _handler(step).inverse(step, state)
