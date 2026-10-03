import pytest
from fakephone import FakeApp, FakePhone

from admenot.engine.actions import commands as C
from admenot.engine.actions.context import read_phone_context
from admenot.engine.actions.errors import ActionError
from admenot.engine.actions.executor import resume, run_order, start_order, undo
from admenot.engine.actions.planner import plan_app
from admenot.engine.allowlist.trust import load_protected_list
from admenot.engine.facts import AppFacts
from admenot.engine.journal.db import Journal

SAW = "android.permission.SYSTEM_ALERT_WINDOW"  # aplikacje w tych testach mogą rysować nad innymi
DISABLE = C.PM_DISABLE.format(package="com.spam")
OVERLAY = C.APPOPS_SET.format(package="com.spam", op="SYSTEM_ALERT_WINDOW", mode="deny")


@pytest.fixture
def journal(tmp_path):
    with Journal(tmp_path / "journal.db") as j:
        yield j


def _phone():
    return FakePhone([
        FakeApp("com.spam", appops={"SYSTEM_ALERT_WINDOW": "allow"}),
        FakeApp("com.other"),
        FakeApp("com.android.launcher", system=True, home_activity=".Launcher"),
    ], sdk=31)


def _snapshot(phone):
    return {p: (a.installed, a.enabled, dict(a.appops)) for p, a in phone.apps.items()}


def _order(phone, journal, tmp_path):
    ctx = read_phone_context(phone)
    plans = [plan_app(package, level, AppFacts(package, version_code=1, requested_permissions={SAW}), ctx,
                      load_protected_list(), tmp_path / "backups")
             for package, level in (("com.spam", "disable"), ("com.other", "silence"))]
    return start_order(journal, phone.serial, "Test", plans)


def _interrupt(phone, journal, order, command):
    """Polecenie dociera do telefonu, ale odpowiedź ginie — kabel wypada w tej chwili."""
    phone.lose_response.add(command)
    with pytest.raises(ActionError) as exc:
        run_order(phone, journal, order.id)
    assert exc.value.uncertain
    phone.lose_response.clear()
    phone.disconnected = False  # telefon podłączony ponownie


def test_disconnect_leaves_pending_steps_and_resume_does_not_repeat_the_command(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path)
    _interrupt(phone, journal, order, DISABLE)
    assert phone.apps["com.spam"].enabled is False  # polecenie doszło, odpowiedź nie
    assert [o.id for o in journal.interrupted_orders(phone.serial)] == [order.id]
    assert journal.order(order.id).status == "running"

    outcomes = resume(phone, journal, order.id)
    assert all(o.ok for o in outcomes)
    assert phone.calls.count(DISABLE) == 1
    assert {a.status for a in journal.actions(order.id)} == {"done"}
    assert journal.order(order.id).status == "done"
    assert journal.interrupted_orders(phone.serial) == []


def test_undo_of_interrupted_order_uses_state_from_before_the_change(journal, tmp_path):
    phone = _phone()
    before = _snapshot(phone)
    order = _order(phone, journal, tmp_path)
    _interrupt(phone, journal, order, OVERLAY)
    assert phone.apps["com.spam"].appops["SYSTEM_ALERT_WINDOW"] == "deny"

    assert undo(phone, journal, order.id) == []
    assert _snapshot(phone) == before  # „allow” z dziennika, a nie „deny” z chwili cofania
    rows = [(a.package, a.step["kind"], a.status, a.error) for a in journal.actions(order.id)]
    assert ("com.spam", "enabled", "undone", "not_started") in rows
    assert journal.order(order.id).status == "undone"


def test_resume_keeps_the_original_inverse(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path)
    _interrupt(phone, journal, order, OVERLAY)
    resume(phone, journal, order.id)
    overlay = next(a for a in journal.actions(order.id)
                   if a.package == "com.spam" and a.step["params"].get("op") == "SYSTEM_ALERT_WINDOW")
    assert overlay.prev_state == {"mode": "allow"}
    assert overlay.inverse["params"] == {"op": "SYSTEM_ALERT_WINDOW", "mode": "allow"}
    undo(phone, journal, order.id)
    assert phone.apps["com.spam"].appops == {"SYSTEM_ALERT_WINDOW": "allow"}


def test_second_disconnect_during_resume_keeps_the_order_resumable(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path)
    _interrupt(phone, journal, order, DISABLE)
    phone.disconnected = True
    with pytest.raises(ActionError):
        resume(phone, journal, order.id)
    phone.disconnected = False
    resume(phone, journal, order.id)
    assert journal.order(order.id).status == "done"
