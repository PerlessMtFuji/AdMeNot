import pytest
from fakephone import FakeApp, FakePhone

from admenot.engine.actions import commands as C
from admenot.engine.actions.context import read_phone_context
from admenot.engine.actions.executor import ExecOptions, run_order, start_order, undo
from admenot.engine.actions.planner import plan_app
from admenot.engine.adb.transport import AdbError
from admenot.engine.allowlist.trust import load_protected_list
from admenot.engine.facts import AppFacts
from admenot.engine.journal.db import Journal


class FakeClock:
    """Zegar testowy: `sleep` przesuwa czas; `on_sleep` symuluje dotknięcie na telefonie."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps = 0
        self.on_sleep = None

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds
        self.sleeps += 1
        if self.on_sleep:
            self.on_sleep(self.sleeps)


@pytest.fixture
def journal(tmp_path):
    with Journal(tmp_path / "journal.db") as j:
        yield j


def _phone():
    return FakePhone([
        FakeApp("com.adm", admin=True, keeps_apk=True),
        FakeApp("com.android.launcher", system=True, home_activity=".Launcher"),
    ], sdk=31)


def _tap_deactivate(phone, on_poll):
    def on_sleep(count):
        if count == on_poll:
            phone.apps["com.adm"].admin = False
    return on_sleep


def _run(phone, journal, tmp_path, level, clock, answers=("skip",)):
    ctx = read_phone_context(phone)
    plan = plan_app("com.adm", level, AppFacts("com.adm", version_code=1), ctx,
                    load_protected_list(), tmp_path / "backups")
    order = start_order(journal, phone.serial, "Test", [plan])
    replies = iter(answers)
    events = []
    options = ExecOptions(clock=clock.clock, sleep=clock.sleep, on_event=events.append,
                          on_admin_timeout=lambda package: next(replies))
    return order, run_order(phone, journal, order.id, options), events


def test_admin_deactivated_on_phone_then_removal_continues(journal, tmp_path):
    phone = _phone()
    clock = FakeClock()
    clock.on_sleep = _tap_deactivate(phone, 3)
    order, (outcome,), events = _run(phone, journal, tmp_path, "remove", clock)
    assert outcome.ok and not phone.apps["com.adm"].installed
    assert phone.opened == ["admin"] and clock.sleeps == 3
    admin = [(a.status, a.error) for a in journal.actions(order.id) if a.step["kind"] == "admin"]
    assert admin == [("done", None)]
    waits = [e for e in events if e["type"] == "admin_wait"]
    assert len(waits) == 1 and waits[0]["timeout"] == 180.0 and waits[0]["package"] == "com.adm"
    assert journal.order(order.id).status == "done"


def test_admin_timeout_then_skip(journal, tmp_path):
    phone = _phone()
    clock = FakeClock()
    order, (outcome,), _ = _run(phone, journal, tmp_path, "remove", clock)
    assert outcome.failed == [("installed", "device_admin")]
    assert phone.apps["com.adm"].installed
    assert clock.sleeps == 180  # odpytywanie co 1 s przez 3 min
    admin = next(a for a in journal.actions(order.id) if a.step["kind"] == "admin")
    assert (admin.status, admin.error) == ("failed", "admin_timeout")
    assert journal.order(order.id).status == "failed"


def test_admin_timeout_retry_reopens_screen(journal, tmp_path):
    phone = _phone()
    clock = FakeClock()
    clock.on_sleep = _tap_deactivate(phone, 200)  # dopiero w drugim podejściu
    _, (outcome,), _ = _run(phone, journal, tmp_path, "remove", clock, answers=("retry",))
    assert outcome.ok and phone.opened == ["admin", "admin"]


def test_disable_blocked_by_admin_takes_the_same_path(journal, tmp_path):
    phone = _phone()
    disable = C.PM_DISABLE.format(package="com.adm")
    phone.fail[disable] = AdbError("command_failed",
                                   "java.lang.SecurityException: Cannot disable a device admin")
    clock = FakeClock()

    def on_sleep(count):
        phone.apps["com.adm"].admin = False
        phone.fail.pop(disable, None)

    clock.on_sleep = on_sleep
    _, (outcome,), _ = _run(phone, journal, tmp_path, "disable", clock)
    assert outcome.ok and phone.apps["com.adm"].enabled is False


def test_admin_screen_falls_back_to_security_settings(journal, tmp_path):
    phone = _phone()
    phone.fail[C.ADMIN_SETTINGS] = (
        "Error: Activity class {com.android.settings/com.android.settings.Settings"
        "$DeviceAdminSettingsActivity} does not exist.\n")
    clock = FakeClock()
    clock.on_sleep = _tap_deactivate(phone, 1)
    _, (outcome,), _ = _run(phone, journal, tmp_path, "remove", clock)
    assert outcome.ok and phone.opened == ["security"]


def test_undo_restores_app_but_not_admin_rights(journal, tmp_path):
    phone = _phone()
    clock = FakeClock()
    clock.on_sleep = _tap_deactivate(phone, 1)
    order, _, _ = _run(phone, journal, tmp_path, "remove", clock)
    assert undo(phone, journal, order.id) == []
    app = phone.apps["com.adm"]
    assert app.installed and not app.admin
    assert journal.order(order.id).status == "undone"
