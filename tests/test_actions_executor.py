import pytest
from fakephone import GEARHEAD, LISTENERS, POST, FakeApp, FakePhone
from test_actions_admin import FakeClock

from admenot.engine.actions import commands as C
from admenot.engine.actions import steps as S
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
from admenot.engine.actions.steps import Step
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


# --- cofanie kanałów witryn ----------------------------------------------------------------

CHROME = "com.android.chrome"
SBROWSER = "com.sec.android.app.sbrowser"
SHARED = "SBROWSER_WEBSITES_NOTIFICATION_CHANNEL"
SITE_A, SITE_B, SITE_C = "web:https://a.pl;1", "web:https://b.pl;2", "web:https://c.pl;3"
OPEN_A = C.OPEN_SITE.format(url="https://a.pl", package=CHROME)
VIEW = "am start -a android.intent.action.VIEW"


def _site_phone(*sites, package=CHROME, importance=0):
    phone = FakePhone([FakeApp(CHROME, appops={"SYSTEM_ALERT_WINDOW": "allow"}), FakeApp(SBROWSER)])
    phone.channels = {CHROME: {}, SBROWSER: {}}
    for site in sites:
        phone.channels[package][site] = importance
    phone.static[OPEN_A] = "Starting: Intent { act=android.intent.action.VIEW }\n"
    return phone


def _turn_on(*sites):
    """Serwisant włącza przełącznik na ekranie kanału (tylko wskazanych, gdy podane)."""
    def tap(phone, package, channel_id):
        if not sites or channel_id in sites:
            phone.channels[package][channel_id] = 3
    return tap


def _site_options(events=None, **kw):
    clock = FakeClock()
    return ExecOptions(clock=clock.clock, sleep=clock.sleep,
                       on_event=(events if events is not None else []).append, **kw)


def _done_row(journal, order, step, prev, inverse=None):
    """Wiersz zapisany jak przez naprawę (albo starszą wersję programu, gdy `inverse` None)."""
    action_id = journal.add_action(order.id, step.package, "fix", step.to_dict(), S.command_for(step))
    journal.record_prev_state(action_id, prev, inverse.to_dict() if inverse else None)
    journal.set_action_status(action_id, "done")
    return action_id


def _channel(site, package=CHROME, enabled=None):
    return Step("channel", package, {"channel_id": site, **({"enabled": enabled} if enabled else {})})


def _site_row(journal, order, site, package=CHROME):
    return _done_row(journal, order, _channel(site, package), {"importance": 3},
                     _channel(site, package, "1"))


def _screen(site, package=CHROME):
    return C.CHANNEL_SETTINGS.format(package=package, channel=C.quoted(site))


def _status(journal, order):
    return [(a.status, a.error) for a in journal.actions(order.id)]


def _errors(result):
    return [(row.id, key) for row, key in result]


def test_undo_opens_each_disabled_site_and_waits_for_the_toggle(journal):
    phone = _site_phone(SITE_A, SITE_B, importance=3)
    order = journal.create_order(phone.serial, "Test")
    for site in (SITE_A, SITE_B):
        journal.add_action(order.id, CHROME, "fix", _channel(site).to_dict(), S.command_for(_channel(site)))
    phone.on_channel_screen = lambda p, pkg, cid: p.channels[pkg].__setitem__(cid, 0)
    run_order(phone, journal, order.id, _site_options())
    phone.opened.clear()
    phone.on_channel_screen = _turn_on()
    assert undo(phone, journal, order.id, options=_site_options()) == []
    assert _status(journal, order) == [("undone", None), ("undone", None)]
    assert phone.opened == [_screen(SITE_A), _screen(SITE_B)]
    assert phone.channels[CHROME] == {SITE_A: 3, SITE_B: 3}
    assert journal.order(order.id).status == "undone"


def test_undo_runs_automatic_steps_before_site_screens(journal):
    phone = _site_phone(SITE_A)
    phone.apps[CHROME].appops["SYSTEM_ALERT_WINDOW"] = "deny"
    phone.on_channel_screen = _turn_on()
    order = journal.create_order(phone.serial, "Test")
    _done_row(journal, order, Step("appop", CHROME, {"op": "SYSTEM_ALERT_WINDOW", "mode": "deny"}),
              {"mode": "allow"}, Step("appop", CHROME, {"op": "SYSTEM_ALERT_WINDOW", "mode": "allow"}))
    _site_row(journal, order, SITE_A)
    assert undo(phone, journal, order.id, options=_site_options()) == []
    appops = phone.calls.index(C.APPOPS_SET.format(package=CHROME, op="SYSTEM_ALERT_WINDOW", mode="allow"))
    assert appops < phone.calls.index(_screen(SITE_A))
    assert phone.apps[CHROME].appops["SYSTEM_ALERT_WINDOW"] == "allow"


def test_undo_old_channel_row_without_inverse_opens_screen(journal):
    phone = _site_phone(SITE_A)
    phone.on_channel_screen = _turn_on()
    order = journal.create_order(phone.serial, "Test")
    _done_row(journal, order, _channel(SITE_A), {"importance": 3})
    assert undo(phone, journal, order.id, options=_site_options()) == []
    assert phone.opened == [_screen(SITE_A)] and _status(journal, order) == [("undone", None)]


def test_undo_channel_disabled_before_repair_is_silent(journal):
    phone = _site_phone(SITE_A)
    order = journal.create_order(phone.serial, "Test")
    _done_row(journal, order, _channel(SITE_A), {"importance": 0})
    assert undo(phone, journal, order.id, options=_site_options()) == []
    assert phone.opened == [] and _status(journal, order) == [("undone", None)]
    assert phone.channels[CHROME][SITE_A] == 0


def test_undo_failed_channel_row_already_enabled_is_silent(journal):
    phone = _site_phone(SITE_A, importance=3)
    order = journal.create_order(phone.serial, "Test")
    journal.add_action(order.id, CHROME, "fix", _channel(SITE_A).to_dict(), S.command_for(_channel(SITE_A)))
    run_order(phone, journal, order.id, _site_options())  # nikt nie wyłączył: user_timeout
    assert _status(journal, order) == [("failed", "user_timeout")]
    phone.opened.clear()
    assert undo(phone, journal, order.id, options=_site_options()) == []
    assert phone.opened == [] and _status(journal, order) == [("undone", None)]


def test_undo_shared_channel_opens_one_screen(journal):
    phone = _site_phone(SHARED, package=SBROWSER)
    phone.on_channel_screen = _turn_on()
    order = journal.create_order(phone.serial, "Test")
    _site_row(journal, order, SHARED, SBROWSER)
    _site_row(journal, order, SHARED, SBROWSER)
    assert undo(phone, journal, order.id, options=_site_options()) == []
    assert phone.opened == [_screen(SHARED, SBROWSER)]
    assert _status(journal, order) == [("undone", None), ("undone", None)]


def test_undo_site_timeout_keeps_row_done_and_moves_on(journal):
    phone = _site_phone(SITE_A, SITE_B)
    phone.on_channel_screen = _turn_on(SITE_B)
    order = journal.create_order(phone.serial, "Test")
    first, _ = _site_row(journal, order, SITE_A), _site_row(journal, order, SITE_B)
    result = undo(phone, journal, order.id, options=_site_options())
    assert _errors(result) == [(first, "site_timeout")]
    assert _status(journal, order) == [("done", None), ("undone", None)]
    assert journal.order(order.id).status == "partially_undone"


def test_undo_site_timeout_text_says_it_was_not_turned_on():
    from admenot.engine.texts import error_text

    assert error_text("site_timeout", "pl") == "nie włączono na czas — włączysz ją później z historii zlecenia"
    assert error_text("site_timeout", "en") == "not turned on in time — turn it on later from the order history"


def test_undo_two_timeouts_in_a_row_end_the_site_phase(journal):
    phone = _site_phone(SITE_A, SITE_B, SITE_C)
    order = journal.create_order(phone.serial, "Test")
    ids = [_site_row(journal, order, site) for site in (SITE_A, SITE_B, SITE_C)]
    result = undo(phone, journal, order.id, options=_site_options())
    assert phone.opened == [_screen(SITE_A), _screen(SITE_B)]
    assert _errors(result) == [(ids[0], "site_timeout"), (ids[1], "site_timeout")]
    assert [s for s, _ in _status(journal, order)] == ["done", "done", "done"]


def test_undo_skip_moves_to_the_next_site(journal):
    phone = _site_phone(SITE_A, SITE_B)
    phone.on_channel_screen = _turn_on(SITE_B)
    order = journal.create_order(phone.serial, "Test")
    first, _ = _site_row(journal, order, SITE_A), _site_row(journal, order, SITE_B)
    skips = iter([True])
    result = undo(phone, journal, order.id, options=_site_options(skip=lambda: next(skips, False)))
    assert _errors(result) == [(first, "site_skipped")]
    assert phone.opened == [_screen(SITE_A), _screen(SITE_B)]
    assert _status(journal, order) == [("done", None), ("undone", None)]


def test_undo_channel_gone_is_recorded_on_the_row(journal):
    phone = _site_phone("browser", importance=3)  # przeglądarka usunęła kanał witryny
    order = journal.create_order(phone.serial, "Test")
    row = _site_row(journal, order, SITE_A)
    result = undo(phone, journal, order.id, options=_site_options())
    assert _errors(result) == [(row, "channel_gone")]
    assert _status(journal, order) == [("done", "channel_gone")] and phone.opened == []


def test_undo_browser_enabled_before_its_channels(journal):
    phone = _site_phone(SITE_A)
    phone.apps[CHROME].enabled = False
    phone.on_channel_screen = _turn_on()
    order = journal.create_order(phone.serial, "Test")
    _done_row(journal, order, Step("enabled", CHROME, {"enabled": "0"}), {"enabled": True},
              Step("enabled", CHROME, {"enabled": "1"}))
    _site_row(journal, order, SITE_A)
    assert undo(phone, journal, order.id, options=_site_options()) == []
    assert phone.calls.index(C.PM_ENABLE.format(package=CHROME)) < phone.calls.index(_screen(SITE_A))


def test_undo_channel_skipped_when_browser_restore_failed(journal):
    phone = _site_phone(SITE_A)
    phone.apps[CHROME].enabled = False
    phone.fail[C.PM_ENABLE.format(package=CHROME)] = AdbError("command_failed", "Error: odd")
    order = journal.create_order(phone.serial, "Test")
    _done_row(journal, order, Step("enabled", CHROME, {"enabled": "0"}), {"enabled": True},
              Step("enabled", CHROME, {"enabled": "1"}))
    row = _site_row(journal, order, SITE_A)
    result = undo(phone, journal, order.id, options=_site_options())
    assert (row, "skipped") in _errors(result) and phone.opened == []
    assert _status(journal, order)[1] == ("done", None)


def test_undo_other_auto_failure_of_the_browser_still_opens_its_screens(journal):
    phone = _site_phone(SITE_A)
    phone.apps[CHROME].appops["SYSTEM_ALERT_WINDOW"] = "deny"
    phone.fail[C.APPOPS_SET.format(package=CHROME, op="SYSTEM_ALERT_WINDOW", mode="allow")] = AdbError(
        "command_failed", "java.lang.SecurityException: not allowed")
    phone.on_channel_screen = _turn_on()
    order = journal.create_order(phone.serial, "Test")
    _done_row(journal, order, Step("appop", CHROME, {"op": "SYSTEM_ALERT_WINDOW", "mode": "deny"}),
              {"mode": "allow"}, Step("appop", CHROME, {"op": "SYSTEM_ALERT_WINDOW", "mode": "allow"}))
    _site_row(journal, order, SITE_A)
    result = undo(phone, journal, order.id, options=_site_options())
    assert [key for _, key in result] == ["security"]
    assert phone.opened == [_screen(SITE_A)] and _status(journal, order)[1] == ("undone", None)


def test_undo_two_timeouts_emit_stopped(journal):
    phone = _site_phone(SITE_A, SITE_B, SITE_C)
    order = journal.create_order(phone.serial, "Test")
    for site in (SITE_A, SITE_B, SITE_C):
        _site_row(journal, order, site)
    events = []
    undo(phone, journal, order.id, options=_site_options(events))
    assert [e for e in events if e["type"] == "stopped"] == [{"type": "stopped"}]


def test_undo_timeout_counter_resets_after_a_success(journal):
    phone = _site_phone(SITE_A, SITE_B, SITE_C, "web:https://d.pl;4")
    phone.on_channel_screen = _turn_on(SITE_B)
    order = journal.create_order(phone.serial, "Test")
    for site in (SITE_A, SITE_B, SITE_C, "web:https://d.pl;4"):
        _site_row(journal, order, site)
    undo(phone, journal, order.id, options=_site_options())
    # timeout, włączony, timeout, timeout: sukces zeruje licznik, więc czwarta też dostaje ekran
    assert phone.opened == [_screen(s) for s in (SITE_A, SITE_B, SITE_C, "web:https://d.pl;4")]


def test_undo_stop_during_site_phase_keeps_the_rest_done(journal):
    phone = _site_phone(SITE_A, SITE_B)
    order = journal.create_order(phone.serial, "Test")
    _site_row(journal, order, SITE_A)
    _site_row(journal, order, SITE_B)
    stop = []
    phone.on_channel_screen = lambda p, pkg, cid: stop.append(cid)  # serwisant klika „Wstrzymaj”
    events = []
    undo(phone, journal, order.id, options=_site_options(events, should_stop=lambda: bool(stop)))
    assert phone.opened == [_screen(SITE_A)]
    assert [e for e in events if e["type"] == "stopped"] == [{"type": "stopped"}]
    assert [s for s, _ in _status(journal, order)] == ["done", "done"]


def test_undo_clears_stale_channel_gone_when_the_channel_is_back(journal):
    phone = _site_phone(SITE_A)
    order = journal.create_order(phone.serial, "Test")
    row = _site_row(journal, order, SITE_A)
    journal.set_action_status(row, "done", "channel_gone")  # poprzednie cofnięcie: kanału nie było
    assert _errors(undo(phone, journal, order.id, options=_site_options())) == [(row, "site_timeout")]
    assert _status(journal, order) == [("done", None)]


def test_undo_channel_gone_on_failed_row_keeps_failed(journal):
    phone = _site_phone("browser", importance=3)
    order = journal.create_order(phone.serial, "Test")
    row = _site_row(journal, order, SITE_A)
    journal.set_action_status(row, "failed", "user_timeout")
    assert _errors(undo(phone, journal, order.id, options=_site_options())) == [(row, "channel_gone")]
    assert _status(journal, order) == [("failed", "channel_gone")]


def test_undo_sites_event_lists_only_rows_that_need_a_screen(journal):
    phone = _site_phone(SITE_A, SITE_B, SITE_C)
    phone.channels[CHROME][SITE_B] = 3  # klient sam włączył po naprawie
    phone.on_channel_screen = _turn_on()
    order = journal.create_order(phone.serial, "Test")
    first = _site_row(journal, order, SITE_A)
    _site_row(journal, order, SITE_B)
    _done_row(journal, order, _channel(SITE_C), {"importance": 0})
    events = []
    undo(phone, journal, order.id, options=_site_options(events))
    sites = [e for e in events if e["type"] == "undo_sites"]
    assert sites == [{"type": "undo_sites", "sites": [{"action_id": first, "package": CHROME}]}]
    assert events.index(sites[0]) < next(i for i, e in enumerate(events) if e["type"] == "user_wait")


def test_undo_never_asks_on_site_timeout(journal):
    phone = _site_phone(SITE_A)
    order = journal.create_order(phone.serial, "Test")
    row = _site_row(journal, order, SITE_A)
    options = _site_options(on_admin_timeout=lambda package: pytest.fail("asked on undo timeout"))
    assert _errors(undo(phone, journal, order.id, options=options)) == [(row, "site_timeout")]


def test_undo_single_site_opens_the_site_after_toggle(journal):
    phone = _site_phone(SITE_A)
    phone.on_channel_screen = _turn_on()
    order = journal.create_order(phone.serial, "Test")
    _site_row(journal, order, SITE_A)
    assert undo(phone, journal, order.id, options=_site_options()) == []
    assert phone.calls.index(_screen(SITE_A)) < phone.calls.index(OPEN_A)


def test_undo_many_sites_do_not_open_sites(journal):
    phone = _site_phone(SITE_A, SITE_B)
    phone.on_channel_screen = _turn_on()
    order = journal.create_order(phone.serial, "Test")
    _site_row(journal, order, SITE_A)
    _site_row(journal, order, SITE_B)
    assert undo(phone, journal, order.id, options=_site_options()) == []
    assert not [c for c in phone.calls if c.startswith(VIEW)]


def test_undo_single_shared_channel_opens_nothing(journal):
    phone = _site_phone(SHARED, package=SBROWSER)
    phone.on_channel_screen = _turn_on()
    order = journal.create_order(phone.serial, "Test")
    _site_row(journal, order, SHARED, SBROWSER)
    assert undo(phone, journal, order.id, options=_site_options()) == []
    assert not [c for c in phone.calls if c.startswith(VIEW)]


def test_undo_site_open_failure_is_not_an_undo_error(journal):
    phone = _site_phone(SITE_A)
    phone.on_channel_screen = _turn_on()
    phone.static[OPEN_A] = AdbError("command_failed", "Error: Activity not started")
    order = journal.create_order(phone.serial, "Test")
    _site_row(journal, order, SITE_A)
    assert undo(phone, journal, order.id, options=_site_options()) == []
    assert _status(journal, order) == [("undone", None)]
