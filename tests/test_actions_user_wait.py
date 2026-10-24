import pytest
from fakephone import FakeApp, FakePhone
from test_actions_admin import FakeClock, _tap_deactivate
from test_actions_admin import _phone as _admin_phone
from test_actions_admin import _run as _admin_run

from admenot.engine.actions import steps as S
from admenot.engine.actions.executor import ExecOptions, resume, run_order, undo
from admenot.engine.actions.steps import Step
from admenot.engine.journal.db import Journal

CHROME = "com.android.chrome"
FIREFOX = "org.mozilla.firefox"
SITE = "web:https://www.bennish.net;13437173097254700"


@pytest.fixture
def journal(tmp_path):
    with Journal(tmp_path / "journal.db") as j:
        yield j


def _phone(**kw):
    phone = FakePhone([FakeApp(CHROME), FakeApp(FIREFOX)], **kw)
    phone.channels[CHROME] = {SITE: 3}
    return phone


def _order(journal, phone, *steps):
    order = journal.create_order(phone.serial, "Test")
    for step in steps:
        journal.add_action(order.id, step.package, "silence", step.to_dict(), S.command_for(step))
    return order


def _channel():
    return Step("channel", CHROME, {"channel_id": SITE})


def _options(clock, events, answers=("skip",)):
    replies = iter(answers)
    return ExecOptions(clock=clock.clock, sleep=clock.sleep, on_event=events.append,
                       on_admin_timeout=lambda package: next(replies))


def _switch_off_on_poll(phone, poll):
    def on_sleep(count):
        if count == poll:
            phone.channels[CHROME][SITE] = 0
    return on_sleep


def test_channel_step_waits_until_switch_turned_off(journal):
    phone = _phone()
    clock, events = FakeClock(), []
    clock.on_sleep = _switch_off_on_poll(phone, 2)
    order = _order(journal, phone, _channel())
    (outcome,) = run_order(phone, journal, order.id, _options(clock, events))
    assert outcome.ok and clock.sleeps == 2
    assert [a.status for a in journal.actions(order.id)] == ["done"]
    wait, done = [e for e in events if e["type"] in ("user_wait", "user_done")]
    assert wait["type"] == "user_wait" and wait["step"] == "channel" and wait["package"] == CHROME
    assert wait["timeout"] == 180.0 and wait["action_id"] == done["action_id"]
    assert done["type"] == "user_done" and done["status"] == "done" and done["error"] is None
    assert not [e for e in events if e["type"] in ("admin_wait", "admin_done")]


def test_channel_timeout_skip_marks_failed_user_timeout(journal):
    phone = _phone()
    clock, events = FakeClock(), []
    order = _order(journal, phone, _channel())
    (outcome,) = run_order(phone, journal, order.id, _options(clock, events))
    assert outcome.failed == [("channel", "user_timeout")]
    assert [(a.status, a.error) for a in journal.actions(order.id)] == [("failed", "user_timeout")]
    done = [e for e in events if e["type"] == "user_done"]
    assert [(e["status"], e["error"]) for e in done] == [("failed", "user_timeout")]
    assert journal.order(order.id).status == "failed"


def test_channel_timeout_retry_reopens_screen(journal):
    phone = _phone()
    clock, events = FakeClock(), []
    phone.on_channel_screen = lambda p, pkg, cid: (
        None if len(p.opened) < 2 else p.channels[pkg].__setitem__(cid, 0))
    clock.on_sleep = lambda n: None
    order = _order(journal, phone, _channel())
    # druga wizyta na ekranie przełącza kanał: po ponowieniu krok się kończy
    (outcome,) = run_order(phone, journal, order.id, _options(clock, events, ("retry", "skip")))
    assert outcome.ok and len(phone.opened) == 2
    assert [e["type"] for e in events if e["type"].startswith("user_")] == [
        "user_wait", "user_wait", "user_done"]


def test_reopen_request_opens_the_waiting_screen_again_without_restarting_the_wait(journal):
    phone = _phone()
    clock, events = FakeClock(), []
    asked = iter([False, True, False])  # serwisant klika „Otwórz ponownie” raz, przy drugim sprawdzeniu
    clock.on_sleep = _switch_off_on_poll(phone, 3)
    order = _order(journal, phone, _channel())
    options = _options(clock, events)
    options.reopen = lambda: next(asked, False)
    (outcome,) = run_order(phone, journal, order.id, options)
    assert outcome.ok and len(phone.opened) == 2
    assert [e["type"] for e in events if e["type"].startswith("user_")] == ["user_wait", "user_done"]


def test_resume_pending_channel_only_probes(journal):
    phone = _phone()
    order = _order(journal, phone, _channel())
    (row,) = journal.actions(order.id)
    journal.record_prev_state(row.id, {"importance": 3}, None)  # przerwane po zapisie stanu
    (outcome,) = resume(phone, journal, order.id, _options(FakeClock(), []))
    assert phone.opened == []
    assert outcome.failed == [("channel", "user_timeout")]
    # użytkownik zdążył wyłączyć kanał, zanim zlecenie wznowiono: krok jest wykonany
    order2 = _order(journal, phone, _channel())
    (row2,) = journal.actions(order2.id)
    journal.record_prev_state(row2.id, {"importance": 3}, None)
    phone.channels[CHROME][SITE] = 0
    (outcome2,) = resume(phone, journal, order2.id, _options(FakeClock(), []))
    assert outcome2.ok and phone.opened == []


def test_admin_path_still_emits_user_wait_with_admin_kind(journal, tmp_path):
    phone = _admin_phone()
    clock = FakeClock()
    clock.on_sleep = _tap_deactivate(phone, 2)
    _, (outcome,), events = _admin_run(phone, journal, tmp_path, "remove", clock)
    assert outcome.ok
    wait = [e for e in events if e["type"] == "user_wait"]
    done = [e for e in events if e["type"] == "user_done"]
    assert [e["step"] for e in wait] == ["admin"] and wait[0]["package"] == "com.adm"
    assert [(e["status"], e["error"]) for e in done] == [("done", None)]


def test_rdp_failure_fails_step_and_order_continues(journal):
    phone = _phone(firefox_debugging=False)
    phone.channels[CHROME][SITE] = 0  # drugi krok już wykonany
    perm = Step("site_permission", FIREFOX, {"origin": "https://www.bennish.net",
                                             "permission": "desktop-notification", "capability": "2"})
    order = _order(journal, phone, perm, _channel())
    outcomes = run_order(phone, journal, order.id, _options(FakeClock(), []))
    first, second = journal.actions(order.id)
    assert (first.status, first.error) == ("failed", "rdp_unavailable")
    assert second.status == "done"
    assert {o.package: o.failed for o in outcomes} == {FIREFOX: [("site_permission", "rdp_unavailable")],
                                                      CHROME: []}


def test_undo_of_channel_already_off_before_repair_opens_nothing(journal):
    phone = _phone()
    phone.channels[CHROME][SITE] = 0
    order = _order(journal, phone, _channel())
    run_order(phone, journal, order.id, _options(FakeClock(), []))
    assert undo(phone, journal, order.id) == []
    # naprawa niczego nie zmieniła (kanał był wyłączony), więc cofnięcie też nie ma czego włączać
    assert [a.status for a in journal.actions(order.id)] == ["undone"]
    assert journal.order(order.id).status == "undone"
    assert phone.opened == []
