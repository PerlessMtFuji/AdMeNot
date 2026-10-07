import pytest
from fakephone import GEARHEAD, LISTENERS, POST, FakeApp, FakePhone

from admenot.engine.actions import commands as C
from admenot.engine.actions.context import read_phone_context
from admenot.engine.actions.executor import (
    ExecOptions,
    resume,
    run_order,
    start_order,
    undo,
    verify,
)
from admenot.engine.actions.planner import plan_app
from admenot.engine.adb.transport import AdbError
from admenot.engine.allowlist.trust import load_protected_list
from admenot.engine.facts import AppFacts
from admenot.engine.journal.db import Journal

AD_LISTENER = "com.ad/com.ad.Listener"
SAW = "android.permission.SYSTEM_ALERT_WINDOW"  # aplikacje w tych testach mogą rysować nad innymi
WRITES = ("appops set", "pm ", "settings put", "am force-stop", "cmd package set-home",
          "cmd notification")


def _phone():
    apps = [
        FakeApp("com.ad", home_activity=".Home", requested={POST}, granted={POST}),
        FakeApp("com.spam", appops={"SYSTEM_ALERT_WINDOW": "allow"}),
        FakeApp("com.android.launcher", system=True, home_activity=".Launcher"),
    ]
    return FakePhone(apps, sdk=34, home="com.ad/.Home",
                     secure={LISTENERS: f"{GEARHEAD}:{AD_LISTENER}"})


def _snapshot(phone):
    apps = {p: (a.installed, a.enabled, dict(a.appops), set(a.granted)) for p, a in phone.apps.items()}
    return phone.home, dict(phone.secure), apps


@pytest.fixture
def journal(tmp_path):
    with Journal(tmp_path / "journal.db") as j:
        yield j


def _order(phone, journal, tmp_path, requests):
    ctx = read_phone_context(phone)
    plans = [plan_app(package, level, AppFacts(package, version_code=1, requested_permissions={SAW}), ctx,
                      load_protected_list(), tmp_path / "backups")
             for package, level in requests.items()]
    return start_order(journal, phone.serial, "Test", plans)


BOTH = {"com.ad": "silence", "com.spam": "disable"}


def test_order_is_journaled_before_touching_the_phone(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, BOTH)
    assert not [c for c in phone.calls if c.startswith(WRITES) and not c.startswith("pm list")]
    assert {a.status for a in journal.actions(order.id)} == {"pending"}
    assert journal.order(order.id).status == "running"


def test_run_order_silences_and_disables(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, BOTH)
    outcomes = run_order(phone, journal, order.id)
    assert all(o.ok for o in outcomes) and {o.package for o in outcomes} == {"com.ad", "com.spam"}
    assert phone.home == "com.android.launcher/.Launcher"
    assert phone.secure[LISTENERS] == GEARHEAD
    ad, spam = phone.apps["com.ad"], phone.apps["com.spam"]
    assert ad.granted == set()
    assert ad.appops == {"SYSTEM_ALERT_WINDOW": "deny", "USE_FULL_SCREEN_INTENT": "deny"}
    assert spam.enabled is False and spam.appops["SYSTEM_ALERT_WINDOW"] == "deny"
    assert {a.status for a in journal.actions(order.id)} == {"done"}
    assert journal.order(order.id).status == "done"
    assert verify(phone, journal, order.id) == {}


def test_undo_order_restores_exact_state(journal, tmp_path):
    phone = _phone()
    before = _snapshot(phone)
    order = _order(phone, journal, tmp_path, BOTH)
    run_order(phone, journal, order.id)
    assert undo(phone, journal, order.id) == []
    assert _snapshot(phone) == before
    assert {a.status for a in journal.actions(order.id)} == {"undone"}
    assert journal.order(order.id).status == "undone"


def test_undo_one_app_then_one_step(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, BOTH)
    run_order(phone, journal, order.id)
    undo(phone, journal, order.id, package="com.spam")
    spam = phone.apps["com.spam"]
    assert spam.enabled and spam.appops == {"SYSTEM_ALERT_WINDOW": "allow"}
    assert phone.home == "com.android.launcher/.Launcher"  # com.ad nadal wyciszona
    assert journal.order(order.id).status == "partially_undone"

    overlay = next(a for a in journal.actions(order.id)
                   if a.package == "com.ad" and a.step["params"].get("op") == "SYSTEM_ALERT_WINDOW")
    undo(phone, journal, order.id, action_id=overlay.id)
    assert phone.apps["com.ad"].appops == {"USE_FULL_SCREEN_INTENT": "deny"}


def test_step_already_in_target_state_is_not_sent_and_undo_keeps_it(journal, tmp_path):
    phone = _phone()
    phone.apps["com.spam"].enabled = False  # użytkownik sam ją wyłączył przed naprawą
    order = _order(phone, journal, tmp_path, {"com.spam": "disable"})
    run_order(phone, journal, order.id)
    assert C.PM_DISABLE.format(package="com.spam") not in phone.calls
    assert undo(phone, journal, order.id) == []
    assert phone.apps["com.spam"].enabled is False


def test_undo_after_user_re_enabled_the_app(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, {"com.spam": "disable"})
    run_order(phone, journal, order.id)
    phone.apps["com.spam"].enabled = True  # użytkownik sam ją włączył
    assert undo(phone, journal, order.id) == []
    assert phone.apps["com.spam"].enabled
    assert C.PM_ENABLE.format(package="com.spam") not in phone.calls


def test_failed_step_does_not_stop_the_rest(journal, tmp_path):
    phone = _phone()
    command = C.APPOPS_SET.format(package="com.spam", op="SYSTEM_ALERT_WINDOW", mode="deny")
    phone.fail[command] = AdbError("command_failed", "java.lang.SecurityException: not allowed")
    order = _order(phone, journal, tmp_path, {"com.spam": "disable"})
    (outcome,) = run_order(phone, journal, order.id)
    assert outcome.failed == [("appop", "security")]
    assert phone.apps["com.spam"].enabled is False
    assert journal.order(order.id).status == "failed"


def test_events_report_each_step(journal, tmp_path):
    phone = _phone()
    events = []
    order = _order(phone, journal, tmp_path, {"com.spam": "disable"})
    run_order(phone, journal, order.id, ExecOptions(on_event=events.append))
    pairs = [(e["step"]["kind"], e["status"]) for e in events]
    assert pairs[:2] == [("permission", "running"), ("permission", "done")]
    assert pairs[-1] == ("enabled", "done")
    assert all(e["type"] == "step" and e["package"] == "com.spam" for e in events)


def test_verify_reports_setting_the_app_restored(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, {"com.ad": "silence"})
    run_order(phone, journal, order.id)
    phone.apps["com.ad"].appops["SYSTEM_ALERT_WINDOW"] = "allow"
    assert verify(phone, journal, order.id) == {"com.ad": ["appop"]}


def test_undo_after_user_uninstalled_the_app(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, {"com.ad": "silence"})
    run_order(phone, journal, order.id)
    phone.apps["com.ad"].installed = False  # użytkownik sam ją odinstalował
    secure_before_undo = dict(phone.secure)
    assert undo(phone, journal, order.id) == []
    assert phone.secure == secure_before_undo  # nie dopisujemy komponentów nieistniejącej aplikacji
    assert phone.home == "com.android.launcher/.Launcher"
    rows = journal.actions(order.id)
    assert {a.status for a in rows} == {"undone"}
    assert {a.error for a in rows if a.inverse is not None} == {"app_gone"}
    assert journal.order(order.id).status == "undone"


class _ClosedAfter:
    """Polecenie dociera do telefonu, ale adb kończy się zwykłym błędem („error: closed”)."""

    def __init__(self, phone, command):
        self.phone, self.command = phone, command
        self.serial = phone.serial

    def shell(self, command, timeout=20.0):
        out = self.phone.shell(command, timeout)
        if command == self.command:
            raise AdbError("command_failed", "error: closed")
        return out

    def run(self, args, timeout=20.0):
        return self.phone.run(args, timeout)


def test_undo_reverts_step_marked_failed_although_it_was_applied(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, {"com.spam": "disable"})
    run_order(_ClosedAfter(phone, C.PM_DISABLE.format(package="com.spam")), journal, order.id)
    assert phone.apps["com.spam"].enabled is False
    assert undo(phone, journal, order.id) == []
    assert phone.apps["com.spam"].enabled


def test_undo_of_really_failed_step_sends_nothing(journal, tmp_path):
    phone = _phone()
    command = C.PM_DISABLE.format(package="com.spam")
    phone.fail[command] = AdbError("command_failed", "Error: something odd")
    order = _order(phone, journal, tmp_path, {"com.spam": "disable"})
    run_order(phone, journal, order.id)
    assert undo(phone, journal, order.id) == []
    assert C.PM_ENABLE.format(package="com.spam") not in phone.calls


def test_resume_after_undo_keeps_undone_status(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, {"com.spam": "disable"})
    run_order(phone, journal, order.id)
    undo(phone, journal, order.id)
    resume(phone, journal, order.id)
    assert journal.order(order.id).status == "undone"


def test_undo_with_unknown_package_changes_nothing(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, {"com.spam": "disable"})
    run_order(phone, journal, order.id)
    with pytest.raises(ValueError):
        undo(phone, journal, order.id, package="com.spma")
    assert journal.order(order.id).status == "done"
