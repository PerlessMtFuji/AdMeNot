import pytest
from fakephone import make_cli_phone

from demalware.engine.actions.executor import ExecOptions, resume, run_order
from demalware.engine.actions.planner import Blocked
from demalware.engine.journal.db import Journal
from demalware.engine.session import run_scan
from demalware.engine.workflow import (
    AppStatus,
    OrderInterrupted,
    execute_order,
    plan_order,
    recommended_requests,
    start,
    targeted_actions,
    undo_order,
)

DISABLE = "pm disable-user --user 0 com.wlive.forecast"


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def _run(tmp_path, phone, requests, options=None, runner=run_order, client=None):
    report = run_scan(phone)
    plan = plan_order(phone, report, requests)
    journal = Journal(tmp_path / "j.db")
    order = start(journal, plan, client)
    return journal, order, execute_order(phone, journal, order, options or ExecOptions(), runner)


def test_recommended_requests_and_blocked_protected_launcher():
    phone = make_cli_phone()
    report = run_scan(phone)
    requests = recommended_requests(report)
    assert requests["com.clean.pro.boost"] == "remove" and "com.whatsapp" not in requests
    plan = plan_order(phone, report, {"com.sec.android.app.launcher": "disable",
                                      "com.wlive.forecast": "disable"})
    blocked = [r for r in plan.results if isinstance(r, Blocked)]
    assert [(b.package, b.reason) for b in blocked] == [("com.sec.android.app.launcher", "protected")]
    assert [p.package for p in plan.plans] == ["com.wlive.forecast"]
    unlocked = plan_order(phone, report, {"com.sec.android.app.launcher": "silence"},
                          unlocked=["com.sec.android.app.launcher"])
    assert [p.package for p in unlocked.plans] == ["com.sec.android.app.launcher"]


def test_execute_disables_and_verifies(tmp_path):
    phone = make_cli_phone()
    events = []
    _, _, result = _run(tmp_path, phone, {"com.wlive.forecast": "disable"},
                        ExecOptions(on_event=events.append), client="Anna")
    assert result.apps == [AppStatus("com.wlive.forecast", "ok")]
    assert result.stopped is False and result.order.status == "done"
    assert result.order.client_name == "Anna"
    assert {"type": "verify"} in events
    assert phone.apps["com.wlive.forecast"].enabled is False


def test_still_active_after_verification(tmp_path):
    phone = make_cli_phone()

    def runner(adb, journal, order_id, options):
        outcomes = run_order(adb, journal, order_id, options)
        phone.apps["com.wlive.forecast"].enabled = True  # aplikacja „wróciła” sama
        return outcomes

    _, _, result = _run(tmp_path, phone, {"com.wlive.forecast": "disable"}, runner=runner)
    assert result.apps == [AppStatus("com.wlive.forecast", "still_active", kinds=["enabled"])]


def test_failed_admin_removal(tmp_path):
    phone = make_cli_phone()
    options = ExecOptions(admin_timeout=0, sleep=lambda s: None)
    _, _, result = _run(tmp_path, phone, {"com.clean.pro.boost": "remove"}, options)
    (app,) = result.apps
    assert app.status == "failed" and "device_admin" in app.errors
    assert phone.apps["com.clean.pro.boost"].installed


def test_stopped_order_marks_the_app_stopped_and_resumes(tmp_path):
    phone = make_cli_phone()
    done = []
    options = ExecOptions(on_event=lambda e: e.get("status") == "done" and done.append(1),
                          should_stop=lambda: len(done) >= 1)
    journal, order, result = _run(tmp_path, phone, {"com.wlive.forecast": "disable"}, options)
    assert result.stopped is True
    assert result.apps == [AppStatus("com.wlive.forecast", "stopped")]
    again = execute_order(phone, journal, order, ExecOptions(), resume)
    assert again.apps == [AppStatus("com.wlive.forecast", "ok")] and again.stopped is False


def test_disconnect_raises_order_interrupted(tmp_path):
    phone = make_cli_phone()
    phone.lose_response.add(DISABLE)
    with pytest.raises(OrderInterrupted) as info:
        _run(tmp_path, phone, {"com.wlive.forecast": "disable"})
    assert info.value.order.number.startswith("ZS/")


def test_undo_order_restores_and_reports(tmp_path):
    phone = make_cli_phone()
    journal, order, _ = _run(tmp_path, phone, {"com.wlive.forecast": "disable"})
    events = []
    result = undo_order(phone, journal, order, options=ExecOptions(on_event=events.append))
    assert result.order.status == "undone" and result.errors == []
    assert result.admin_not_restored is False
    assert phone.apps["com.wlive.forecast"].enabled
    assert {e["type"] for e in events} == {"undo"}


def test_targeted_actions_filters_by_package_and_action_id(tmp_path):
    phone = make_cli_phone()
    journal, order, _ = _run(tmp_path, phone, {"com.wlive.forecast": "disable",
                                                "com.whatsapp": "silence"})
    all_actions = journal.actions(order.id)
    assert targeted_actions(journal, order.id) == all_actions

    forecast_only = targeted_actions(journal, order.id, package="com.wlive.forecast")
    assert forecast_only and all(a.package == "com.wlive.forecast" for a in forecast_only)

    one = targeted_actions(journal, order.id, action_id=all_actions[0].id)
    assert one == [all_actions[0]]

    assert targeted_actions(journal, order.id, package="com.does.not.exist") == []
