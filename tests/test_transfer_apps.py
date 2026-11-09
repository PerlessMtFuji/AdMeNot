"""Silnik instalacji aplikacji z kopii: plan, instalacja przez strażnika `AppInstallAdb`, stan do wznowienia."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
from faketransfer import FakeStoragePhone

from admenot.engine.actions.backup import COMPLETE
from admenot.engine.adb.transport import AdbError
from admenot.engine.device.info import DeviceInfo
from admenot.engine.transfer import apps as A
from admenot.engine.transfer import store
from admenot.engine.transfer.guard import AppInstallAdb
from admenot.engine.transfer.restore_state import RestoreState, restore_state_path

NOW = datetime(2026, 11, 8, 12, 0, 0)
VENDING = "com.android.vending"


def _device(sdk: int = 34, manufacturer: str = "OPPO") -> DeviceInfo:
    return DeviceInfo(serial="NEW", brand=manufacturer.lower(), manufacturer=manufacturer, model="X", device="x",
                      market_name=None, android_release="14", sdk=sdk, security_patch=None, uptime_s=1.0,
                      local_now=NOW)


class Env:
    def __init__(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
        self.copy = store.create_copy("OLD", _device(), None, NOW)
        self.phone = FakeStoragePhone(tmp_path / "newphone", serial="NEW")
        self.phone.props["ro.product.cpu.abilist"] = "arm64-v8a,armeabi-v7a"
        self.adb = AppInstallAdb(self.phone, self.copy.apps_dir)
        self.state = RestoreState(restore_state_path(self.copy, "NEW"))
        self.verdicts: list[dict] = []
        self.sdk: dict[str, tuple[int | None, int | None]] = {}
        monkeypatch.setattr(A, "apk_sdk", lambda base: self.sdk.get(base.parent.parent.name, (21, 30)))
        self.waited = 0

    def add(self, package: str, label: str, files: tuple[str, ...] = ("base.apk",), verdict: str = "clean",
            version: int = 7, complete: bool = True) -> Path:
        d = self.copy.apps_dir / package / str(version)
        d.mkdir(parents=True)
        hashes = {}
        for name in files:
            data = f"{package}:{name}".encode()
            (d / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        if complete:
            (d / COMPLETE).write_text(json.dumps({"package": package, "version_code": version, "files": hashes}),
                                      encoding="utf-8")
        self.verdicts.append({"package": package, "version_code": version, "verdict": verdict, "label": label})
        self.copy.verdicts_path.write_text(json.dumps(self.verdicts), encoding="utf-8")
        return d

    def plan(self, device: DeviceInfo | None = None) -> A.AppsPlan:
        return A.build_apps_plan(self.adb, self.copy, device or _device())

    def wait(self) -> None:
        self.waited += 1
        self.phone.reconnect()

    def run(self, plan: A.AppsPlan, packages=None, only_blocked: bool = False, stop=lambda: False):
        progress: list[A.AppsProgress] = []
        res = A.run_install(self.adb, _device(), self.copy, plan,
                            frozenset(packages if packages is not None else (c.package for c in plan.apps)),
                            self.state, on_progress=progress.append, should_stop=stop, wait_device=self.wait,
                            only_blocked=only_blocked)
        self.progress = progress
        return res


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def test_plan_marks_installed_too_old_no_abi(env):
    env.add("com.a.inst", "Inst")
    env.add("com.b.old", "Old")
    env.add("com.c.x86", "X86", files=("base.apk", "split_config.x86.apk"))
    env.add("com.d.arm", "Arm", files=("base.apk", "split_config.arm64_v8a.apk"))
    env.add("com.e.bad", "Bad", verdict="suspicious")
    env.add("com.f.inc", "Inc", complete=False)
    env.phone.installed.add("com.a.inst")
    env.sdk["com.b.old"] = (14, 22)
    plan = env.plan()
    by = {c.package: c for c in plan.apps}
    assert by["com.a.inst"].skip == "installed"
    assert by["com.b.old"].skip == "too_old"
    assert by["com.c.x86"].skip == "no_abi"
    assert by["com.d.arm"].skip is None
    assert by["com.e.bad"].default_on is False and by["com.e.bad"].skip is None
    assert by["com.a.inst"].default_on is True
    assert by["com.f.inc"].skip == "incomplete"
    assert by["com.d.arm"].bytes > 0 and len(by["com.d.arm"].files) == 2
    assert [c.label for c in plan.apps] == sorted((c.label for c in plan.apps), key=str.lower)
    assert plan.block is None


def test_plan_never_offers_malicious_apps(env):
    """Szkodliwe nie trafiają do kopii (Etap 1); gdyby jednak tam były — plan ich nie zawiera, więc
    `run_install` ich nie zainstaluje nawet wskazanych z nazwy."""
    env.add("com.a.ok", "Ok")
    env.add("com.b.mal", "Mal", verdict="malicious")
    plan = env.plan()
    assert [c.package for c in plan.apps] == ["com.a.ok"]
    res = env.run(plan, packages={"com.a.ok", "com.b.mal"})
    assert "com.b.mal" not in env.phone.installed
    assert [r["package"] for r in res.rows] == ["com.a.ok"]


def test_plan_too_new_and_old_only_on_sdk_34(env):
    env.add("com.a.x", "X")
    env.sdk["com.a.x"] = (30, 30)
    assert env.plan(_device(sdk=29)).apps[0].skip == "too_new"
    env.sdk["com.a.x"] = (14, 22)
    assert env.plan(_device(sdk=33)).apps[0].skip is None
    env.sdk["com.a.x"] = (None, None)
    assert env.plan(_device(sdk=34)).apps[0].skip is None


@pytest.mark.parametrize("value,expected", [("0", "xiaomi"), ("1", None), ("", None), ("weird", None)])
def test_xiaomi_blocked_from_prop(env, value, expected):
    env.add("com.a.x", "X")
    env.phone.props["persist.security.adbinstall"] = value
    assert env.plan(_device(manufacturer="Xiaomi")).block == expected


@pytest.mark.parametrize("miui_prop", ["ro.miui.ui.version.name", "ro.mi.os.version.name"])
def test_missing_prop_on_miui_means_blocked(env, miui_prop):
    # Redmi Note 11 (MIUI 13): bez wartości, dopóki serwisant ani razu nie włączy „Instaluj przez USB”
    env.phone.props[miui_prop] = "V130"
    assert A.xiaomi_install_blocked(env.adb) is True
    env.phone.props["persist.security.adbinstall"] = "1"
    assert A.xiaomi_install_blocked(env.adb) is False


def test_declined_miui_dialog_fails_one_app_not_the_rest(env):
    # Ustawienie włączone, a instalacja i tak `USER_RESTRICTED`: odrzucone/przegapione okno zgody MIUI.
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    env.phone.props["persist.security.adbinstall"] = "1"
    env.phone.install_blocked = True
    res = env.run(env.plan(_device(manufacturer="Xiaomi")))
    assert not res.blocked and res.skipped == {}
    assert len(env.phone.host_commands) == 2
    assert {(r["status"], r["reason"]) for r in res.rows} == {("failed", "no_consent")}


def test_xiaomi_prop_ignored_on_other_makers_and_helper(env):
    env.phone.props["persist.security.adbinstall"] = "0"
    assert A.xiaomi_install_blocked(env.adb) is True
    env.phone.props["persist.security.adbinstall"] = "1"
    assert A.xiaomi_install_blocked(env.adb) is False
    env.phone.props.pop("persist.security.adbinstall")
    assert A.xiaomi_install_blocked(env.adb) is None
    env.phone.props["persist.security.adbinstall"] = "0"
    assert env.plan(_device(manufacturer="OPPO")).block is None


def test_install_single_and_split(env):
    env.add("com.a.single", "Alpha")
    env.add("com.b.split", "Beta", files=("base.apk", "split_config.arm64_v8a.apk"))
    res = env.run(env.plan())
    assert res.selected == 2 and res.installed == 2 and res.exists == 0 and not res.blocked
    cmds = env.phone.host_commands
    assert [c[0] for c in cmds] == ["install", "install-multiple"]
    assert cmds[0][1:3] == ["-i", VENDING] and cmds[0][3].endswith("base.apk")
    assert cmds[1][1:3] == ["-i", VENDING]
    assert [Path(p).name for p in cmds[1][3:]] == ["base.apk", "split_config.arm64_v8a.apk"]
    assert {"com.a.single", "com.b.split"} <= env.phone.installed
    assert res.play_installer is True
    assert [r["status"] for r in res.rows] == ["installed", "installed"]
    assert env.state.apps_status()["com.a.single"][0] == "installed"
    assert env.progress[-1].done == 2 and env.progress[-1].total == 2


def test_install_never_uses_r_or_d(env):
    env.add("com.a.single", "Alpha")
    env.add("com.b.split", "Beta", files=("base.apk", "split_config.arm64_v8a.apk"))
    env.phone.installed.add("com.c.there")
    env.add("com.c.there", "Gamma")
    env.run(env.plan())
    for cmd in env.phone.host_commands:
        assert not {"-r", "-d", "-g", "uninstall"} & set(cmd)
    assert not any("uninstall" in c for c in env.phone.commands)
    assert len(env.phone.host_commands) == 2  # zainstalowanej nie ruszamy


def test_already_installed_is_exists_not_reinstalled(env):
    env.add("com.a.x", "X")
    env.phone.installed.add("com.a.x")
    res = env.run(env.plan())
    assert res.exists == 1 and res.installed == 0 and env.phone.host_commands == []
    assert res.rows[0]["status"] == "exists"
    assert res.play_installer is False


def test_pre_installed_list_saved_once(env):
    env.add("com.a.x", "X")
    env.phone.installed.add("com.whatsapp")
    env.run(env.plan())
    assert env.state.get_meta("apps_pre_installed") == ["com.whatsapp"]


def test_user_restricted_blocks_rest(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    env.add("com.c.three", "Gamma")
    env.phone.install_blocked = True
    res = env.run(env.plan())
    assert res.blocked and res.installed == 0
    assert res.skipped == {"user_restricted": 3}
    assert len(env.phone.host_commands) == 1
    assert {r["status"] for r in res.rows} == {"skipped"}
    assert {r["reason"] for r in res.rows} == {"user_restricted"}


def test_xiaomi_block_skips_without_attempts(env):
    env.add("com.a.one", "Alpha")
    env.phone.props["persist.security.adbinstall"] = "0"
    res = env.run(env.plan(_device(manufacturer="Xiaomi")))
    assert res.blocked and res.skipped == {"user_restricted": 1} and env.phone.host_commands == []


def test_only_blocked_installs_remaining(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    env.add("com.c.three", "Gamma")
    env.phone.installed.add("com.b.two")  # już jest -> exists, nie ruszane po odblokowaniu
    env.phone.install_blocked = True
    first = env.run(env.plan())
    assert first.blocked
    assert env.state.apps_status()["com.b.two"][0] == "exists"
    env.phone.install_blocked = False
    env.phone.host_commands.clear()
    second = env.run(env.plan(), only_blocked=True)
    assert [Path(c[-1]).parent.parent.name for c in env.phone.host_commands] == ["com.a.one", "com.c.three"]
    by = {r["package"]: r["status"] for r in second.rows}
    assert by == {"com.a.one": "installed", "com.b.two": "exists", "com.c.three": "installed"}
    assert second.installed == 2 and second.exists == 1 and not second.blocked


def test_disconnect_mid_install_resumes_without_double(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    env.phone.disconnect_after_install.add("com.a.one")
    res = env.run(env.plan())
    assert env.waited == 1
    assert [Path(c[-1]).parent.parent.name for c in env.phone.host_commands].count("com.a.one") == 1
    assert res.installed == 2 and res.exists == 0
    assert {r["package"]: r["status"] for r in res.rows} == {"com.a.one": "installed", "com.b.two": "installed"}


def test_disconnect_before_install_is_retried_without_using_attempt(env):
    env.add("com.a.one", "Alpha")
    plan = env.plan()
    env.phone.online = False
    res = env.run(plan)
    assert res.installed == 1 and env.waited >= 1


def test_consent_timeout_is_no_consent_and_continues(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    env.phone.install_timeout.add("com.a.one")
    res = env.run(env.plan())
    assert res.installed == 1
    assert res.failed == {"no_consent": 1}
    assert [r["status"] for r in res.rows] == ["failed", "installed"]
    assert env.state.apps_status()["com.a.one"][:2] == ("failed", "no_consent")


def test_consent_refusal_and_known_failures_recorded(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    env.phone.install_fail["com.a.one"] = "Failure [INSTALL_FAILED_ABORTED: User rejected permissions]"
    env.phone.install_fail["com.b.two"] = "Failure [INSTALL_FAILED_NO_MATCHING_ABIS: Failed to extract native libraries]"
    res = env.run(env.plan())
    assert res.failed == {"no_consent": 1, "no_abi": 1}
    assert res.codes == {"INSTALL_FAILED_ABORTED": 1, "INSTALL_FAILED_NO_MATCHING_ABIS": 1}
    assert len(env.phone.host_commands) == 2  # znany błąd nie jest ponawiany


def test_unknown_failure_retried_up_to_attempts(env):
    env.add("com.a.one", "Alpha")
    env.phone.install_fail["com.a.one"] = "Failure [something odd]"
    res = env.run(env.plan())
    assert res.failed == {"failed": 1}
    assert len(env.phone.host_commands) == A.APP_ATTEMPTS


def test_installer_rejected_falls_back_without_i(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    env.phone.installer_rejected = True
    res = env.run(env.plan())
    assert res.installed == 2 and res.failed == {}
    cmds = env.phone.host_commands
    assert "-i" in cmds[0]            # próba z -i
    assert "-i" not in cmds[1]        # ponowienie bez -i
    assert "-i" not in cmds[2]        # druga aplikacja już bez -i
    assert len(cmds) == 3
    assert res.play_installer is False


def test_stop_leaves_rest_pending(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    res = env.run(env.plan(), stop=stop)
    assert res.stopped and res.installed == 1
    assert [r["status"] for r in res.rows] == ["installed", "pending"]


def test_resume_does_not_repeat_final_results(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    env.phone.install_fail["com.a.one"] = "Failure [INSTALL_FAILED_VERSION_DOWNGRADE]"
    env.run(env.plan())
    env.phone.host_commands.clear()
    res = env.run(env.plan())
    assert env.phone.host_commands == []
    assert res.failed == {"version_downgrade": 1} and res.exists + res.installed == 1


def test_deselected_apps_untouched(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    res = env.run(env.plan(), packages={"com.b.two"})
    assert res.selected == 1 and res.installed == 1
    assert "com.a.one" not in env.phone.installed


@pytest.mark.parametrize("text,error,code", [
    ("Failure [INSTALL_FAILED_USER_RESTRICTED: Install canceled by user]", "user_restricted",
     "INSTALL_FAILED_USER_RESTRICTED"),
    ("Failure [INSTALL_FAILED_ABORTED: User rejected permissions]", "no_consent", "INSTALL_FAILED_ABORTED"),
    ("Failure [INSTALL_CANCELED_BY_USER]", "no_consent", None),
    ("Failure: canceled by user", "no_consent", None),
    ("Failure [INSTALL_FAILED_DEPRECATED_SDK_VERSION: x]", "too_old", "INSTALL_FAILED_DEPRECATED_SDK_VERSION"),
    ("Failure [INSTALL_FAILED_OLDER_SDK]", "too_old", "INSTALL_FAILED_OLDER_SDK"),
    ("Failure [INSTALL_FAILED_NO_MATCHING_ABIS]", "no_abi", "INSTALL_FAILED_NO_MATCHING_ABIS"),
    ("Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]", "no_space", "INSTALL_FAILED_INSUFFICIENT_STORAGE"),
    ("Failure [INSTALL_FAILED_VERSION_DOWNGRADE]", "version_downgrade", "INSTALL_FAILED_VERSION_DOWNGRADE"),
    ("Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]", "conflict", "INSTALL_FAILED_UPDATE_INCOMPATIBLE"),
    ("Failure [INSTALL_FAILED_ALREADY_EXISTS]", "conflict", "INSTALL_FAILED_ALREADY_EXISTS"),
    ("Failure [INSTALL_FAILED_DUPLICATE_PERMISSION]", "conflict", "INSTALL_FAILED_DUPLICATE_PERMISSION"),
    ("Failure [INSTALL_PARSE_FAILED_NOT_APK]", "invalid_apk", "INSTALL_PARSE_FAILED_NOT_APK"),
    ("Failure [INSTALL_FAILED_INVALID_APK]", "invalid_apk", "INSTALL_FAILED_INVALID_APK"),
    ("Failure [INSTALL_FAILED_SOMETHING_NEW]", "failed", "INSTALL_FAILED_SOMETHING_NEW"),
    ("garbage", "failed", None),
])
def test_classify_install_codes(text, error, code):
    assert A.classify_install(text) == (error, code)


def test_adb_error_kinds_for_phone_offline(env):
    # sanity: fake zgłasza offline jako AdbError
    env.phone.online = False
    with pytest.raises(AdbError):
        env.adb.run(["get-state"])


def _installs(env, package):
    return [c for c in env.phone.host_commands if Path(c[-1]).parent.parent.name == package]


def test_pending_from_previous_process_and_present_is_installed_without_install(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    plan = env.plan()
    env.state.app_attempt("com.a.one")  # polecenie poszło w poprzednim procesie
    env.state.app_attempt("com.b.two")
    env.phone.installed.update({"com.a.one", "com.b.two"})  # stare okno zgody dokończyło instalację
    res = env.run(plan)
    assert res.installed == 2 and res.failed == {} and env.phone.host_commands == []
    # to samo, gdy plan zbudowano jeszcze przed instalacją (pakiet pojawia się dopiero przy sprawdzeniu)
    env.state.db.execute("DELETE FROM apps")
    env.state.app_attempt("com.a.one")
    env.phone.installed.clear()
    plan = env.plan()
    env.phone.installed.add("com.a.one")
    res = env.run(plan, packages={"com.a.one"})
    assert res.installed == 1 and env.phone.host_commands == []


@pytest.mark.parametrize("failure", ["Failure [INSTALL_FAILED_ALREADY_EXISTS: x]",
                                     "Failure [INSTALL_FAILED_ABORTED: User rejected permissions]"])
def test_failure_but_package_landed_is_installed(env, failure):
    env.add("com.a.one", "Alpha")
    env.phone.install_fail["com.a.one"] = failure
    env.phone.install_fail_lands.add("com.a.one")
    res = env.run(env.plan())
    assert res.installed == 1 and res.failed == {}
    assert len(env.phone.host_commands) == 1


def test_installer_word_in_package_name_does_not_drop_installer(env):
    env.add("com.my.installer", "Alpha")
    env.add("com.b.two", "Beta")
    env.phone.install_fail["com.my.installer"] = "Failure [INSTALL_FAILED_ABORTED: User rejected permissions]"
    res = env.run(env.plan())
    assert res.failed == {"no_consent": 1} and res.installed == 1
    assert all("-i" in c for c in env.phone.host_commands)
    assert len(_installs(env, "com.my.installer")) == 1
    assert res.play_installer is True


def test_installer_rejected_requires_security_exception_about_installer():
    files = (Path("/x/apps/com.a.b/1/base.apk"),)
    msg = "java.lang.SecurityException: Caller is not allowed to set the installer package"
    assert A.installer_rejected(msg, files, "com.a.b")
    assert not A.installer_rejected("Failure [INSTALL_FAILED_ABORTED]: SecurityException installer", files, "com.a.b")
    assert not A.installer_rejected("package installer: failed to install /x/apps/com.a.b/1/base.apk", files,
                                    "com.a.b")
    assert not A.installer_rejected("SecurityException: foo /x/apps/com.a.b/1/base.apk", files, "com.a.b")


def test_no_consent_row_rechecked_on_resume(env):
    env.add("com.a.one", "Alpha")
    env.phone.install_timeout.add("com.a.one")
    plan = env.plan()
    res = env.run(plan)
    assert res.failed == {"no_consent": 1}
    env.phone.installed.add("com.a.one")  # zgoda przyszła później
    env.phone.host_commands.clear()
    res = env.run(plan)
    assert res.installed == 1 and res.failed == {} and env.phone.host_commands == []


def test_pending_under_block_checks_presence_first(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    env.phone.props["persist.security.adbinstall"] = "0"
    plan = env.plan(_device(manufacturer="Xiaomi"))
    env.state.app_attempt("com.a.one")
    env.phone.installed.add("com.a.one")
    plan = A.AppsPlan(plan.apps, plan.block)
    res = env.run(plan)
    by = {r["package"]: (r["status"], r["reason"]) for r in res.rows}
    assert by == {"com.a.one": ("installed", None), "com.b.two": ("skipped", "user_restricted")}


def test_adb_error_while_alive_fails_one_app_and_continues(env):
    env.add("com.a.one", "Alpha")
    env.add("com.b.two", "Beta")
    plan = env.plan()

    def boom(command: str) -> None:
        if command == "pm list packages com.a.one":
            raise AdbError("command_failed", "boom")

    env.phone.on_shell = boom
    res = env.run(plan)
    assert res.failed == {"failed": 1} and res.installed == 1
    assert [r["status"] for r in res.rows] == ["failed", "installed"]


def test_adb_text_with_timeout_is_not_no_consent():
    assert A.classify_install("adb: connection timeout while installing") == ("failed", None)
