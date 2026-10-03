from fakephone import make_cli_phone

from admenot.engine.actions.context import read_phone_context
from admenot.engine.actions.executor import ExecOptions, resume, run_order, start_order
from admenot.engine.actions.planner import plan_app
from admenot.engine.allowlist.trust import load_protected_list
from admenot.engine.journal.db import Journal
from admenot.engine.session import run_scan


def _order(tmp_path, phone, requests):
    report = run_scan(phone)
    facts = {r.facts.package: r.facts for r in report.results}
    ctx = read_phone_context(phone, "samsung")
    plans = [plan_app(p, level, facts[p], ctx, load_protected_list(), tmp_path / "b")
             for p, level in requests.items()]
    journal = Journal(tmp_path / "j.db")
    return journal, start_order(journal, phone.serial, "SM-A145R", plans)


def test_stop_before_next_step_leaves_the_rest_pending(tmp_path):
    phone = make_cli_phone()
    journal, order = _order(tmp_path, phone, {"com.wlive.forecast": "disable"})
    events, done = [], []

    def on_event(e):
        events.append(e)
        if e["type"] == "step" and e["status"] == "done":
            done.append(e["action_id"])

    options = ExecOptions(on_event=on_event, should_stop=lambda: len(done) >= 2)
    run_order(phone, journal, order.id, options)
    statuses = [a.status for a in journal.actions(order.id)]
    assert statuses[:2] == ["done", "done"] and set(statuses[2:]) == {"pending"}
    assert events[-1] == {"type": "stopped"}
    assert journal.order(order.id).status == "running"
    assert [o.id for o in journal.interrupted_orders(phone.serial)] == [order.id]
    assert phone.apps["com.wlive.forecast"].enabled

    resume(phone, journal, order.id)
    assert {a.status for a in journal.actions(order.id)} == {"done"}
    assert journal.order(order.id).status == "done"
    assert phone.apps["com.wlive.forecast"].enabled is False


def test_stop_ends_the_admin_wait_without_asking(tmp_path):
    phone = make_cli_phone()
    journal, order = _order(tmp_path, phone, {"com.clean.pro.boost": "disable"})
    asked, stop = [], []

    def on_event(e):
        if e["type"] == "admin_wait":
            stop.append(True)

    options = ExecOptions(on_event=on_event, should_stop=lambda: bool(stop), admin_timeout=60,
                          sleep=lambda s: None,
                          on_admin_timeout=lambda p: asked.append(p) or "retry")
    run_order(phone, journal, order.id, options)
    admin = [a for a in journal.actions(order.id) if a.step["kind"] == "admin"]
    assert [(a.status, a.error) for a in admin] == [("failed", "admin_timeout")]
    assert asked == []
    assert phone.apps["com.clean.pro.boost"].enabled
