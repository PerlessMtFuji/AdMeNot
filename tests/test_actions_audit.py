"""Błędy wykonawcy z audytu przed wydaniem (2026-10-11): resume, undo, stop, równoległość, HOME."""

import pytest
from fakephone import FakeApp, FakePhone

from admenot.engine.actions import commands as C
from admenot.engine.actions.context import read_phone_context
from admenot.engine.actions.executor import ExecOptions, resume, run_order, start_order, undo
from admenot.engine.actions.planner import Blocked, plan_app
from admenot.engine.allowlist.trust import load_protected_list
from admenot.engine.facts import AppFacts
from admenot.engine.journal.db import Journal
from admenot.engine.oplock import DeviceBusy, device_lock, operation_active

LAUNCHER = "com.android.launcher/.Launcher"
SPLITS = ("base.apk", "split_config.arm64_v8a.apk")


@pytest.fixture
def journal(tmp_path):
    with Journal(tmp_path / "journal.db") as j:
        yield j


def _phone(**kw):
    return FakePhone([
        FakeApp("com.spam", version_code=7, apks=SPLITS, home_activity=".Home"),
        FakeApp("com.android.launcher", system=True, home_activity=".Launcher"),
    ], sdk=31, home=LAUNCHER, **kw)


def _order(phone, journal, tmp_path, level, package="com.spam"):
    ctx = read_phone_context(phone)
    plan = plan_app(package, level, AppFacts(package, version_code=7), ctx, load_protected_list(),
                    tmp_path / "backups" / "SERIAL")
    return start_order(journal, phone.serial, "Test", [plan])


def _run_until(phone, journal, order, kind):
    """Wykonuje zlecenie i wstrzymuje przed pierwszym krokiem `kind`."""
    rows = journal.actions(order.id)
    stop_at = next(i for i, a in enumerate(rows) if a.step["kind"] == kind)
    calls = {"n": 0}

    def should_stop():
        calls["n"] += 1
        return calls["n"] > stop_at

    run_order(phone, journal, order.id, ExecOptions(should_stop=should_stop))
    assert journal.actions(order.id)[stop_at].status == "pending"


def _status(journal, order, kind):
    return next(a for a in journal.actions(order.id) if a.step["kind"] == kind)


# --- BUG-04: resume ponownie sprawdza warunki planu -------------------------------------------

def test_resume_does_not_disable_what_became_the_active_keyboard(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, "disable")
    _run_until(phone, journal, order, "enabled")
    phone.secure["default_input_method"] = "com.spam/.Keyboard"  # klient zmienił klawiaturę
    resume(phone, journal, order.id)
    row = _status(journal, order, "enabled")
    assert (row.status, row.error) == ("failed", "active_ime")
    assert phone.apps["com.spam"].enabled and C.PM_DISABLE.format(package="com.spam") not in phone.calls


def test_resume_does_not_uninstall_an_app_updated_after_the_backup(journal, tmp_path):
    phone = _phone(sha256sum=True)
    order = _order(phone, journal, tmp_path, "remove")
    _run_until(phone, journal, order, "installed")
    phone.apps["com.spam"].build = b"update"  # aktualizacja z Play między stop a resume
    resume(phone, journal, order.id)
    row = _status(journal, order, "installed")
    assert (row.status, row.error) == ("failed", "backup_stale")
    assert phone.apps["com.spam"].installed


def test_resume_with_unrecognized_context_changes_nothing(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, "disable")
    _run_until(phone, journal, order, "enabled")
    phone.fail[C.DEFAULT_IME] = "unsupported format\n"
    resume(phone, journal, order.id)
    assert _status(journal, order, "enabled").error == "context_unknown"
    assert phone.apps["com.spam"].enabled


# --- BUG-07: nieudane przełączenie HOME blokuje wyłączenie launchera ---------------------------

def test_failed_home_switch_blocks_disabling_the_current_launcher(journal, tmp_path):
    phone = _phone()
    phone.home = "com.spam/.Home"
    order = _order(phone, journal, tmp_path, "disable")
    phone.fail[C.SET_HOME.format(component=LAUNCHER)] = "Error: OEM refused\n"
    run_order(phone, journal, order.id)
    assert _status(journal, order, "home").status == "failed"
    assert (_status(journal, order, "enabled").error) == "home_active"
    assert phone.apps["com.spam"].enabled and phone.home == "com.spam/.Home"


def test_alternative_home_is_not_a_launcher_the_same_plan_disables(tmp_path):
    phone = FakePhone([FakeApp("com.spam", home_activity=".Home"),
                       FakeApp("com.android.launcher", system=True, home_activity=".Launcher")],
                      home="com.spam/.Home")
    ctx = read_phone_context(phone)
    plan = plan_app("com.spam", "disable", AppFacts("com.spam"), ctx, load_protected_list(),
                    tmp_path, avoid_homes=frozenset({"com.android.launcher"}))
    assert plan == Blocked("com.spam", "disable", "home_no_alternative")


# --- BUG-05: undo potwierdza stan po cofnięciu ------------------------------------------------

def test_undo_that_does_not_change_the_phone_is_not_marked_undone(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, "disable")
    run_order(phone, journal, order.id)
    enable = C.PM_ENABLE.format(package="com.spam")
    phone.fail[enable] = "Package com.spam new state: enabled\n"  # kod 0, stan bez zmian
    errors = undo(phone, journal, order.id, options=ExecOptions(sleep=lambda s: None))
    assert [(a.step["kind"], key) for a, key in errors] == [("enabled", "not_restored")]
    assert _status(journal, order, "enabled").status == "done"  # nadal do cofnięcia
    assert phone.apps["com.spam"].enabled is False
    assert journal.order(order.id).status == "partially_undone"
    del phone.fail[enable]
    assert undo(phone, journal, order.id) == []
    assert phone.apps["com.spam"].enabled and journal.order(order.id).status == "undone"


# --- BUG-09: nieudane cofnięcie kroku „failed” nie daje statusu „undone” ----------------------

def test_failed_step_with_inverse_that_cannot_be_undone_keeps_order_partially_undone(
        journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, "disable")
    run_order(phone, journal, order.id)
    row = _status(journal, order, "enabled")
    journal.set_action_status(row.id, "failed", "timeout")  # niepewny wynik: zmiana mogła zajść
    phone.fail[C.PM_ENABLE.format(package="com.spam")] = "Error: java.lang.SecurityException\n"
    errors = undo(phone, journal, order.id)
    assert errors and _status(journal, order, "enabled").status == "failed"
    assert journal.order(order.id).status == "partially_undone"


# --- EDGE-01: undo respektuje „Wstrzymaj” ------------------------------------------------------

def test_undo_stops_before_the_next_inverse(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, "disable")
    run_order(phone, journal, order.id)
    events = []
    assert undo(phone, journal, order.id,
                options=ExecOptions(should_stop=lambda: True, on_event=events.append)) == []
    assert phone.apps["com.spam"].enabled is False
    assert {"type": "stopped"} in events
    assert journal.order(order.id).status == "partially_undone"


# --- BUG-06: jedna operacja na telefon, zapisany krok odwrotny nie jest nadpisywany -----------

def test_second_process_gets_busy_instead_of_running_the_same_order(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, "disable")
    with device_lock(journal.path, phone.serial):
        assert operation_active(journal.path)
        with pytest.raises(DeviceBusy):
            run_order(phone, journal, order.id)
        with pytest.raises(DeviceBusy):
            undo(phone, journal, order.id)
    assert not operation_active(journal.path)
    assert {a.status for a in journal.actions(order.id)} == {"pending"}
    assert phone.apps["com.spam"].enabled


def test_prev_state_is_recorded_only_once(journal, tmp_path):
    phone = _phone()
    order = _order(phone, journal, tmp_path, "disable")
    row = _status(journal, order, "enabled")
    inverse = {"kind": "enabled", "package": "com.spam", "params": {"enabled": "1"}}
    assert journal.record_prev_state(row.id, {"enabled": True}, inverse) is True
    # Drugi proces ze starą migawką (prev_state=None) widzi już wyłączoną aplikację:
    assert journal.record_prev_state(row.id, {"enabled": False}, None) is False
    assert journal.action(row.id).inverse == inverse
