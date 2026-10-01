import pytest
from fakephone import make_cli_phone

from demalware.engine.actions import commands as C
from demalware.engine.actions.executor import ExecOptions, resume, run_order
from demalware.engine.actions.planner import Blocked
from demalware.engine.journal.db import Journal
from demalware.engine.phones.provider import PhoneImageProvider
from demalware.engine.session import run_scan
from demalware.engine.settings import Settings
from demalware.engine.workflow import (
    AppStatus,
    OrderInterrupted,
    OrderResult,
    clear_cache_after_repair,
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


def test_stopped_order_lists_apps_the_runner_never_reached(tmp_path):
    phone = make_cli_phone()
    journal, order, result = _run(tmp_path, phone, {"com.wlive.forecast": "disable",
                                                     "com.whatsapp": "silence"},
                                  ExecOptions(should_stop=lambda: True))
    queued = list(dict.fromkeys(a.package for a in journal.actions(order.id)))
    assert result.stopped is True and len(queued) == 2
    assert result.apps == [AppStatus(p, "stopped") for p in queued]


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


def test_certain_error_from_the_admin_fallback_still_interrupts_the_order(tmp_path):
    """`_Admin.apply` opens the admin-settings screen, falling back to security settings when
    that fails; when BOTH fail with a "certain" (non-uncertain) error, the error escapes
    `run_order` uncaught (executor.py: `_recover` -> `_admin_path` -> `S.apply` isn't guarded
    there). `execute_order` must still turn it into `OrderInterrupted`, not let it leak out as a
    bare `ActionError` — the CLI only knows how to report `OrderInterrupted` as "disconnected"."""
    phone = make_cli_phone()  # com.clean.pro.boost is a device admin; disabling it needs the screen
    phone.fail[C.ADMIN_SETTINGS] = "Error: could not start admin settings.\n"
    phone.fail[C.SECURITY_SETTINGS] = "Error: could not start security settings.\n"
    report = run_scan(phone)
    plan = plan_order(phone, report, {"com.clean.pro.boost": "disable"})
    journal = Journal(tmp_path / "j.db")
    order = start(journal, plan, None)

    with pytest.raises(OrderInterrupted) as info:
        execute_order(phone, journal, order, ExecOptions())

    assert info.value.order.number == order.number
    assert info.value.order.status == "running"
    assert [o.number for o in journal.interrupted_orders(phone.serial)] == [order.number]


def test_start_stores_the_snapshot_and_execute_the_verification(tmp_path):
    phone = make_cli_phone()
    report = run_scan(phone)
    plan = plan_order(phone, report, {"com.wlive.forecast": "disable"})
    match = PhoneImageProvider(tmp_path / "missing", tmp_path / "o.json").match(report.device)
    journal = Journal(tmp_path / "j.db")
    order = start(journal, plan, "Anna", report, match)
    snap = journal.scan(order.id)
    assert snap["device"]["model"] == "SM-A145R" and snap["phone"]["confidence"] == "none"
    apps = {a["package"]: a for a in snap["apps"]}
    assert apps["com.wlive.forecast"]["chosen_level"] == "disable"
    assert apps["com.clean.pro.boost"]["chosen_level"] is None
    assert snap["scope"]["profiles"]["present"] == [0]
    assert journal.verification(order.id) is None
    execute_order(phone, journal, order, ExecOptions())
    assert journal.verification(order.id) == {}


def test_start_without_report_keeps_the_order_without_snapshot(tmp_path):
    journal, order, _ = _run(tmp_path, make_cli_phone(), {"com.wlive.forecast": "disable"})
    assert journal.scan(order.id) is None and journal.verification(order.id) == {}


def test_resume_overwrites_the_verification(tmp_path):
    phone = make_cli_phone()
    done = []
    options = ExecOptions(on_event=lambda e: e.get("status") == "done" and done.append(1),
                          should_stop=lambda: len(done) >= 1)
    journal, order, _ = _run(tmp_path, phone, {"com.wlive.forecast": "disable"}, options)
    assert journal.verification(order.id) == {}  # verify sprawdza tylko kroki „done”
    journal.save_verification(order.id, {"com.wlive.forecast": ["enabled"]})  # nieaktualna
    execute_order(phone, journal, order, ExecOptions(), resume)
    assert journal.verification(order.id) == {}


def test_clear_cache_after_repair_only_when_enabled_and_finished(tmp_path):
    entry = tmp_path / "com.a" / "id"
    entry.mkdir(parents=True)
    (entry / "base.apk").write_bytes(b"x" * 10)
    on, off = Settings(apk_cache_clear_after_repair=True), Settings()
    stopped = OrderResult(order=None, apps=[], stopped=True)
    finished = OrderResult(order=None, apps=[], stopped=False)
    assert clear_cache_after_repair(finished, off, tmp_path) is None
    assert clear_cache_after_repair(stopped, on, tmp_path) is None
    assert entry.exists()
    assert clear_cache_after_repair(finished, on, tmp_path) == 10
    assert not entry.exists()
