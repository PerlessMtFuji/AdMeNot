import pytest
from fakephone import GEARHEAD, LISTENERS, POST, FakeApp, FakePhone

from demalware.engine.actions import commands as C
from demalware.engine.actions.context import read_phone_context
from demalware.engine.actions.executor import ExecOptions, run_order, start_order, undo, verify
from demalware.engine.actions.planner import plan_app
from demalware.engine.adb.transport import AdbError
from demalware.engine.allowlist.trust import load_protected_list
from demalware.engine.facts import AppFacts
from demalware.engine.journal.db import Journal

AD_LISTENER = "com.ad/com.ad.Listener"
WRITES = ("appops set", "pm ", "settings put", "am force-stop", "cmd package set-home")


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
    plans = [plan_app(package, level, AppFacts(package, version_code=1), ctx,
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
