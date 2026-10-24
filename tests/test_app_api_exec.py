import pytest
from apphelpers import SlowApk, make_api, names
from conftest import SERIAL
from fakephone import FakeApp, make_cli_phone

from admenot.app.events import RecordingEmitter
from admenot.engine.actions import commands as C
from admenot.engine.journal.db import Journal
from admenot.engine.paths import journal_path

DISABLE = "pm disable-user --user 0 com.wlive.forecast"
WLIVE = {"com.wlive.forecast": "disable"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))


def _scanned(phone=None, **kw):
    phone = phone or make_cli_phone()
    api, rec = make_api(phone, **kw)
    api.start_scan(SERIAL, "Anna")
    rec.wait_for("apk:done")
    assert api._jobs.wait(5)  # skan (także w wątku) skończył się razem z job:end
    rec.events.clear()
    return phone, api, rec


def test_preview_needs_a_scan_and_shows_blocked_apps():
    api, _ = make_api(make_cli_phone())
    assert api.preview_plan(WLIVE)["error"]["key"] == "no_scan"
    _, api, _ = _scanned()
    view = api.preview_plan({"com.sec.android.app.launcher": "disable", **WLIVE}, [])
    assert view["runnable"] == 1 and view["apps"][0]["blocked"] is True


def test_execute_disables_and_reports():
    phone, api, rec = _scanned()
    assert api.execute(WLIVE, []) == {"job_id": "job-2"}
    seq = names(rec)
    assert seq[0] == "exec:order" and seq[-3:] == ["exec:verify", "exec:done", "job:end"]
    order = rec.of("exec:order")[0]
    assert order["order"].startswith("ZS/2026/0926/") and order["plan"]["runnable"] == 1
    steps = rec.of("exec:step")
    assert {s["status"] for s in steps} == {"running", "done"}
    assert "wyłączenie aplikacji" in {s["label"] for s in steps}
    done = rec.of("exec:done")[0]
    assert done["apps"][0]["outcome"] == "ok" and done["stopped"] is False
    assert phone.apps["com.wlive.forecast"].enabled is False
    (o,) = api.history()["orders"]
    assert o["client"] == "Anna" and o["number"] == order["order"]


def test_admin_path_with_the_user_tapping_deactivate():
    phone = make_cli_phone()
    phone.on_admin_screen = lambda p: setattr(p.apps["com.clean.pro.boost"], "admin", False)
    phone, api, rec = _scanned(phone)
    api.execute({"com.clean.pro.boost": "remove"}, [])
    wait = rec.of("exec:user_wait")[0]
    assert (wait["package"], wait["kind"], wait["timeout"]) == ("com.clean.pro.boost", "admin", 180.0)
    assert wait["name"] and "site" not in wait
    assert rec.of("exec:user_done") == [{"package": "com.clean.pro.boost", "status": "done"}]
    assert not rec.of("exec:admin_wait") and not rec.of("exec:admin_done")
    assert rec.of("exec:done")[0]["firefox_debugging"] is False
    assert rec.of("exec:done")[0]["apps"][0]["outcome"] == "ok"
    assert phone.apps["com.clean.pro.boost"].installed is False


def test_admin_timeout_question_skip():
    _phone, api, rec = _scanned(sync=False, admin_timeout=0)
    job = api.execute({"com.clean.pro.boost": "disable"}, [])["job_id"]
    question = rec.wait_for("exec:question")
    assert question["job_id"] == job and question["kind"] == "user_timeout"
    assert api.answer(job, "skip") == {"ok": True}
    done = rec.wait_for("exec:done")
    assert done["apps"][0]["outcome"] == "failed"
    assert any("administrator" in e for e in done["apps"][0]["errors"])


def test_stop_then_resume():
    phone = make_cli_phone()
    phone, api, rec = _scanned(phone)

    class StopAfterFirstDone(RecordingEmitter):
        def emit(self, name, detail=None):
            super().emit(name, detail)
            if name == "exec:step" and detail["status"] == "done":
                api.stop(api._jobs.current().id)

    stopper = StopAfterFirstDone()
    api._emitter = stopper
    api._jobs._emitter = stopper
    api.execute(WLIVE, [])
    number = stopper.of("exec:order")[0]["order"]
    assert stopper.of("exec:stopped") == [{"order": number}]
    assert stopper.of("exec:done")[0]["stopped"] is True
    assert phone.apps["com.wlive.forecast"].enabled
    assert api.history()["orders"][0]["interrupted"] is True

    api._emitter = rec
    api._jobs._emitter = rec
    api.resume(number)
    assert rec.of("exec:order")[-1] == {"order": number, "plan": None}
    assert rec.of("exec:done")[-1]["apps"][0]["outcome"] == "ok"
    assert phone.apps["com.wlive.forecast"].enabled is False
    assert api.resume(number)["error"]["key"] == "nothing_to_resume"


def test_disconnect_during_execute_then_resume():
    phone, api, rec = _scanned()
    phone.lose_response.add(DISABLE)
    api.execute(WLIVE, [])
    (lost,) = rec.of("exec:disconnected")
    assert "exec:done" not in rec.names()
    phone.lose_response.clear()
    phone.disconnected = False
    api.resume(lost["order"])
    assert rec.of("exec:done")[-1]["apps"][0]["outcome"] == "ok"
    assert phone.calls.count(DISABLE) == 1


def test_execute_during_apk_analysis_abandons_it():
    slow = SlowApk()
    phone = make_cli_phone()
    api, rec = make_api(phone, sync=False, apk=slow)
    api.start_scan(SERIAL)
    rec.wait_for("apk:progress")
    result = api.execute(WLIVE, [])
    assert "job_id" in result
    rec.wait_for("exec:done")
    slow.release.set()
    rec.wait_for("apk:stopped")
    assert "apk:done" not in rec.names()
    assert phone.apps["com.wlive.forecast"].enabled is False


def test_abandoning_the_analysis_tells_the_ui_at_once():
    # Cofnięcie i wznowienie porzucają analizę; UI zna już ich zadanie, więc zdarzenie idzie bez `job_id`.
    slow = SlowApk()
    api, rec = make_api(make_cli_phone(), sync=False, apk=slow)
    api.start_scan(SERIAL)
    rec.wait_for("apk:progress")
    api._abandon_apk()
    assert rec.of("apk:stopped")[0] == {}
    slow.release.set()


def test_undoing_an_interrupted_order_clears_it_from_the_interrupted_list():
    phone, api, rec = _scanned()
    phone.lose_response.add(DISABLE)
    api.execute(WLIVE, [])
    (lost,) = rec.of("exec:disconnected")
    phone.lose_response.clear()
    phone.disconnected = False
    api.undo(lost["order"])
    assert rec.of("undo:done")[-1]["interrupted"] == []


def test_reopen_screen_needs_an_order_in_progress():
    _, api, _ = _scanned()
    assert api.reopen_screen() == {"ok": False}
    assert not api._reopen.is_set()


def test_nothing_runnable_is_an_error():
    _, api, rec = _scanned()
    api.execute({"com.sec.android.app.launcher": "disable"}, [])
    assert rec.of("job:error")[0]["key"] == "nothing_to_do"


def test_undo_whole_order_and_single_action():
    phone, api, rec = _scanned()
    api.execute(WLIVE, [])
    number = rec.of("exec:order")[0]["order"]
    actions = api.history()["orders"][0]["actions"]
    enabled = next(a for a in actions if a["kind"] == "enabled")
    api.undo(number, enabled["id"], None)
    assert rec.of("undo:done")[-1]["status"] == "partially_undone"
    assert phone.apps["com.wlive.forecast"].enabled
    api.undo(number, None, None)
    done = rec.of("undo:done")[-1]
    assert done["status"] == "undone" and done["status_label"] == "cofnięte"
    assert done["admin_not_restored"] is False and done["errors"] == []
    assert {s["status"] for s in rec.of("undo:step")} == {"running", "undone"}
    assert api.undo("ZS/1999/0101/01")["error"]["key"] == "unknown_order"


def test_history_and_undo_with_another_phone_connected():
    phone, api, rec = _scanned()
    api.execute(WLIVE, [])
    number = rec.of("exec:order")[0]["order"]
    phone.host["devices -l"] = "List of devices attached\nOTHER1 device usb:1-2 model:X\n"
    fresh, _ = make_api(phone)
    history = fresh.history()
    assert history["serial"] == SERIAL and history["serials"] == [SERIAL]
    error = fresh.undo(number)["error"]
    assert error["key"] == "wrong_device" and error["serial"] == SERIAL
    device = fresh.history()["devices"][0]
    assert error["device"] == device["name"] != SERIAL  # nazwa i IMEI jak w historii
    assert error["imei"] == device["imei"]
    assert phone.apps["com.wlive.forecast"].enabled is False
    assert fresh.history("NOPE")["orders"] == []


def test_execute_stores_the_snapshot_from_the_scan():
    _, api, rec = _scanned()
    api.execute(WLIVE, [])
    number = rec.of("exec:order")[0]["order"]
    with Journal(journal_path()) as j:
        order = j.order_by_number(number)
        snap = j.scan(order.id)
        assert snap["device"]["serial"] == SERIAL and snap["phone"]["confidence"] == "none"
        assert snap["app_count"] == len(api._report.results)
        assert j.verification(order.id) == {}


def test_finished_repair_clears_the_apk_cache_when_enabled():
    from admenot.engine.apk.fetch import default_cache_dir
    _, api, rec = _scanned()
    api.save_settings({"apk_cache_clear_after_repair": True})
    entry = default_cache_dir() / "com.old" / "id"
    entry.mkdir(parents=True)
    (entry / "base.apk").write_bytes(b"x")
    api.execute(WLIVE, [])
    assert rec.of("exec:done") and not entry.exists()


def test_stopped_repair_keeps_the_apk_cache():
    from admenot.engine.apk.fetch import default_cache_dir
    _, api, _ = _scanned()
    api.save_settings({"apk_cache_clear_after_repair": True})
    entry = default_cache_dir() / "com.old" / "id"
    entry.mkdir(parents=True)
    (entry / "base.apk").write_bytes(b"x")

    class StopAfterFirstDone(RecordingEmitter):  # jak w test_stop_then_resume
        def emit(self, name, detail=None):
            super().emit(name, detail)
            if name == "exec:step" and detail["status"] == "done":
                api.stop(api._jobs.current().id)

    stopper = StopAfterFirstDone()
    api._emitter = stopper
    api._jobs._emitter = stopper
    api.execute(WLIVE, [])
    assert stopper.of("exec:done")[0]["stopped"] is True
    assert entry.exists()


def test_failing_cache_clear_does_not_fail_a_finished_repair(monkeypatch):
    from admenot.engine import workflow

    def boom(cache_dir):
        raise OSError("locked")

    monkeypatch.setattr(workflow, "clear_cache", boom)
    _, api, rec = _scanned()
    api.save_settings({"apk_cache_clear_after_repair": True})
    api.execute(WLIVE, [])
    assert rec.of("exec:done") and rec.of("job:error") == []


ID_A, ID_B = "1111222233334444", "9999888877776666"


def _phone_with_id(android_id):
    phone = make_cli_phone()
    phone.secure["android_id"] = android_id
    return phone


def test_undo_and_resume_refuse_another_phone_with_the_same_serial():
    phone, api, rec = _scanned(_phone_with_id(ID_A))
    api.execute(WLIVE, [])
    number = rec.of("exec:order")[0]["order"]
    phone.secure["android_id"] = ID_B  # inny egzemplarz z tym samym numerem seryjnym
    error = api.undo(number)["error"]
    assert error["key"] == "device_mismatch" and error["serial"] == SERIAL
    assert api.resume(number)["error"]["key"] == "device_mismatch"
    assert phone.apps["com.wlive.forecast"].enabled is False  # nic nie zostało cofnięte


def test_undo_on_the_same_phone_with_a_known_android_id():
    _, api, rec = _scanned(_phone_with_id(ID_A))
    api.execute(WLIVE, [])
    number = rec.of("exec:order")[0]["order"]
    assert "error" not in api.undo(number)
    assert rec.of("undo:done")[-1]["status"] == "undone"


def test_scan_hides_interrupted_orders_of_another_phone_with_the_same_serial():
    phone, api, rec = _scanned(_phone_with_id(ID_A))
    phone.lose_response.add(DISABLE)
    api.execute(WLIVE, [])
    phone.lose_response.clear()
    phone.disconnected = False
    phone.secure["android_id"] = ID_B
    api.start_scan(SERIAL)
    assert rec.of("scan:done")[-1]["interrupted"] == []
    phone.secure["android_id"] = ID_A
    api.start_scan(SERIAL)
    assert len(rec.of("scan:done")[-1]["interrupted"]) == 1


CHROME = "com.android.chrome"
FIREFOX = "org.mozilla.firefox"
SITE = "web:https://www.example.com;1"
FIX = f"site:{CHROME}:{SITE}"


def _chrome_phone():
    phone = make_cli_phone()
    phone.channels = {CHROME: {SITE: 3}}

    def switch_off(p, package, channel_id):
        p.channels[package][channel_id] = 0

    phone.on_channel_screen = switch_off
    return phone


def test_preview_and_execute_take_fixes():
    phone, api, rec = _scanned(_chrome_phone())
    view = api.preview_plan({}, [], [FIX])
    assert view["runnable"] == 1 and view["apps"][0]["level"] == "fix"
    api.execute({}, [], None, [FIX])
    wait = rec.of("exec:user_wait")[0]
    assert wait == {"package": CHROME, "name": "Chrome", "kind": "channel", "site": "www.example.com",
                    "browser": "Chrome", "timeout": 180.0, "action_id": wait["action_id"]}
    assert isinstance(wait["action_id"], int)
    assert rec.of("exec:user_done") == [{"package": CHROME, "status": "done"}]
    done = rec.of("exec:done")[0]
    assert done["apps"][0]["outcome"] == "ok" and done["firefox_debugging"] is False
    assert phone.channels[CHROME][SITE] == 0
    (o,) = api.history()["orders"]
    (action,) = o["actions"]
    assert action["manual_undo"] is None  # cofnięcie jest automatyczne, ścieżka tylko dla zniknięcia kanału
    assert o["apps"][CHROME]["name"] == "Chrome"


def test_channel_timeout_asks_with_the_generic_user_timeout_kind():
    _phone, api, rec = _scanned(_chrome_phone(), sync=False, admin_timeout=0)
    _phone.on_channel_screen = None  # przełącznik na telefonie nie zostaje wyłączony
    job = api.execute({}, [], None, [FIX])["job_id"]
    question = rec.wait_for("exec:question")
    assert question["kind"] == "user_timeout" and question["job_id"] == job
    api.answer(job, "skip")
    done = rec.wait_for("exec:done")
    assert done["apps"][0]["outcome"] == "failed"
    assert any("na telefonie" in e for e in done["apps"][0]["errors"])


def test_firefox_site_permission_marks_the_done_event_for_the_debugging_reminder(monkeypatch):
    from admenot.engine import device_checks
    from admenot.engine.actions import steps

    phone = make_cli_phone()
    phone.channels = {CHROME: {SITE: 0}}  # zrzut z jakimikolwiek kanałami jest „rozpoznany”
    phone.firefox_debugging = True
    phone.firefox_perms = {"https://www.example.com": 1}
    # Sesja adb nie przekazuje `rdp_connect` atrapy; prawdziwy `tcp_connect` łączy się z portem forward.
    monkeypatch.setattr(device_checks, "tcp_connect", phone.rdp_connect)
    monkeypatch.setattr(steps, "tcp_connect", phone.rdp_connect)
    phone, api, rec = _scanned(phone)
    api.execute({}, [], None, [f"site_perm:{FIREFOX}:https://www.example.com"])
    assert not rec.of("exec:user_wait")
    assert rec.of("exec:done")[0]["firefox_debugging"] is True
    assert phone.firefox_perms["https://www.example.com"] == 2


OPEN_URL = C.OPEN_SITE.format(url="https://www.example.com", package=CHROME)


def _undo_phone():
    """Telefon po naprawie witryny: Chrome zainstalowany, ekran kanału na cofaniu włącza kanał."""
    phone = _chrome_phone()
    phone.apps[CHROME] = FakeApp(CHROME)
    phone.static[OPEN_URL] = "Starting: Intent { act=android.intent.action.VIEW }\n"
    return phone


def _repaired(phone=None, **kw):
    phone, api, rec = _scanned(phone or _undo_phone(), **kw)
    api.execute(WLIVE, [], None, [FIX])
    number = rec.of("exec:order")[0]["order"]
    assert phone.channels[CHROME][SITE] == 0
    rec.events.clear()
    return phone, api, rec, number


def _turn_on(p, package, channel_id):
    p.channels[package][channel_id] = 3


def test_undo_emits_site_queue_with_names():
    phone, api, rec, number = _repaired()
    phone.on_channel_screen = _turn_on
    api.undo(number, None, None)
    (queue,) = rec.of("undo:sites")
    (site,) = queue["sites"]
    assert queue["order"] == number
    assert site == {"action_id": site["action_id"], "package": CHROME, "browser": "Chrome",
                    "site": "www.example.com"}
    assert isinstance(site["action_id"], int)
    assert rec.names().index("undo:sites") < rec.names().index("exec:user_wait")


def test_user_wait_carries_action_id():
    phone, api, rec, number = _repaired()
    phone.on_channel_screen = _turn_on
    api.undo(number, None, None)
    (queue,) = rec.of("undo:sites")
    (wait,) = rec.of("exec:user_wait")
    assert wait["action_id"] == queue["sites"][0]["action_id"] and wait["kind"] == "channel"
    assert wait["site"] == "www.example.com" and wait["browser"] == "Chrome"


def test_skip_site_skips_current_screen():
    phone, api, rec, number = _repaired()
    answers = []

    class SkipOnWait(RecordingEmitter):  # „Pomiń” klikane, gdy ekran już czeka
        def emit(self, name, detail=None):
            super().emit(name, detail)
            if name == "exec:user_wait":
                answers.append(api.skip_site())

    clicker = SkipOnWait()
    api._emitter = clicker
    api._jobs._emitter = clicker
    rec = clicker
    api.undo(number, None, None)
    assert answers == [{"ok": True}]
    failed = [s for s in rec.of("undo:step") if s["status"] == "failed"]
    assert failed and "włączysz ją później" in failed[0]["error"]
    assert phone.channels[CHROME][SITE] == 0
    assert rec.of("undo:done")[-1]["sites_restored"] == 0


def test_skip_clicked_before_the_screen_wait_does_not_skip_it():
    phone, api, rec, number = _repaired()

    def early(p, package, channel_id):  # „Pomiń” z poprzedniego ekranu, zanim ten zacznie czekać
        api.skip_site()
        p.channels[package][channel_id] = 3

    phone.on_channel_screen = early
    api.undo(number, None, None)
    assert rec.of("undo:done")[-1]["sites_restored"] == 1
    assert not api._skip.is_set()


def test_skip_site_without_order_is_noop():
    _, api, _ = _scanned()
    assert api.skip_site() == {"ok": False}
    assert not api._skip.is_set()


def test_skip_site_is_refused_during_repair():
    phone = _undo_phone()
    phone, api, _rec = _scanned(phone)
    results = []

    def skip(p, package, channel_id):
        results.append(api.skip_site())
        p.channels[package][channel_id] = 0

    phone.on_channel_screen = skip
    api.execute({}, [], None, [FIX])
    assert results == [{"ok": False}]
    assert not api._skip.is_set()


def test_reopen_screen_works_during_undo():
    phone, api, rec, number = _repaired()
    seen = []

    def screen(p, package, channel_id):
        seen.append(api.reopen_screen() if not seen else None)
        if len(seen) > 1:
            p.channels[package][channel_id] = 3

    phone.on_channel_screen = screen
    phone.opened.clear()
    api.undo(number, None, None)
    assert seen[0] == {"ok": True} and len(seen) == 2  # drugi raz ten sam ekran
    assert len(phone.opened) == 2 and phone.opened[0] == phone.opened[1]
    assert rec.of("undo:done")[-1]["sites_restored"] == 1


def test_undo_done_reports_site_counts():
    phone, api, rec, number = _repaired()
    phone.on_channel_screen = _turn_on
    api.undo(number, None, None)
    done = rec.of("undo:done")[-1]
    assert done["sites_total"] == 1 and done["sites_restored"] == 1
    assert "sites_not_restored" not in done
    assert done["firefox_debugging"] is False and done["errors"] == []
    assert phone.channels[CHROME][SITE] == 3
    assert phone.apps["com.wlive.forecast"].enabled
    # cofnięcie samej aplikacji (bez poprawek) nie mówi o witrynach
    api.execute(WLIVE, [])
    api.undo(rec.of("exec:order")[-1]["order"], None, None)
    assert rec.of("undo:done")[-1]["sites_total"] == 0
    assert rec.of("undo:done")[-1]["sites_restored"] == 0


def test_undo_done_lists_restored_sites_with_url():
    phone, api, rec, number = _repaired()
    phone.on_channel_screen = _turn_on
    api.undo(number, None, None)
    (site,) = rec.of("undo:done")[-1]["restored_sites"]
    (queued,) = rec.of("undo:sites")[0]["sites"]
    assert site == {"action_id": queued["action_id"], "package": CHROME, "browser": "Chrome",
                    "site": "www.example.com", "url": "https://www.example.com"}


def test_undo_timeout_leaves_the_site_and_counts_it_unrestored():
    phone, api, rec, number = _repaired()
    api._admin_timeout = 0  # po naprawie: cofanie nie ma już czekać na stuknięcie
    api.undo(number, None, None)
    done = rec.of("undo:done")[-1]
    assert done["sites_total"] == 1 and done["sites_restored"] == 0 and done["restored_sites"] == []
    assert not rec.of("exec:question")
    assert phone.channels[CHROME][SITE] == 0


def test_open_site_runs_view_intent():
    phone, api, rec, number = _repaired()
    phone.on_channel_screen = _turn_on
    api.undo(number, None, None)
    action_id = rec.of("undo:done")[-1]["restored_sites"][0]["action_id"]
    phone.calls.clear()
    assert api.open_site(number, action_id) == {"ok": True}
    assert OPEN_URL in phone.calls


def test_open_site_busy_while_job_runs():
    phone, api, _rec, number = _repaired()
    results = []

    def screen(p, package, channel_id):
        results.append(api.open_site(number, 1))
        p.channels[package][channel_id] = 3

    phone.on_channel_screen = screen
    api.undo(number, None, None)
    assert results[0]["error"]["key"] == "busy"


def test_open_site_unknown_action_is_not_ok():
    phone, api, _rec, number = _repaired()
    phone.on_channel_screen = _turn_on
    api.undo(number, None, None)
    with Journal(journal_path()) as j:
        enabled = next(a.id for a in j.actions(j.order_by_number(number).id) if a.step["kind"] == "enabled")
    assert api.open_site(number, 99999) == {"ok": False}
    assert api.open_site(number, enabled) == {"ok": False}  # wiersz bez witryny


def test_open_site_failing_adb_is_not_ok():
    from admenot.engine.adb.transport import AdbError

    phone, api, rec, number = _repaired()
    phone.on_channel_screen = _turn_on
    api.undo(number, None, None)
    action_id = rec.of("undo:done")[-1]["restored_sites"][0]["action_id"]
    phone.static[OPEN_URL] = AdbError("command_failed", "Error: Activity not started")
    assert api.open_site(number, action_id) == {"ok": False}


def test_undo_of_a_gone_channel_gives_a_manual_path():
    phone, api, rec, number = _repaired()
    phone.channels[CHROME] = {"web:https://b.pl;2": 3}  # przeglądarka usunęła kanał tej witryny
    api.undo(number, None, None)
    actions = {a["kind"]: a for a in api.history()["orders"][0]["actions"]}
    assert actions["channel"]["status"] == "done" and actions["channel"]["manual_undo"]
    assert "usunęła ten kanał" in actions["channel"]["error"]
    assert actions["channel"]["site_url"] is None
    assert actions["enabled"]["status"] == "undone"
    done = rec.of("undo:done")[-1]
    assert done["sites_total"] == 1 and done["sites_restored"] == 0
    assert not rec.of("undo:sites")  # bez ekranu nie ma kolejki


def test_undo_of_a_firefox_fix_reminds_to_turn_remote_debugging_off(monkeypatch):
    from admenot.engine import device_checks
    from admenot.engine.actions import steps

    phone = make_cli_phone()
    phone.channels = {CHROME: {SITE: 0}}
    phone.firefox_debugging = True
    phone.firefox_perms = {"https://www.example.com": 1}
    phone.apps[FIREFOX] = FakeApp(FIREFOX)  # zainstalowany: cofnięcie naprawdę przywraca zgodę
    monkeypatch.setattr(device_checks, "tcp_connect", phone.rdp_connect)
    monkeypatch.setattr(steps, "tcp_connect", phone.rdp_connect)
    phone, api, rec = _scanned(phone)
    api.execute({}, [], None, [f"site_perm:{FIREFOX}:https://www.example.com"])
    api.undo(rec.of("exec:order")[0]["order"], None, None)
    done = rec.of("undo:done")[-1]
    assert done["firefox_debugging"] is True and done["sites_total"] == 0
    assert done["status"] == "undone"
    assert phone.firefox_perms["https://www.example.com"] == 1


@pytest.mark.parametrize("bad", ["x", [1], {"a": 1}, 5])
def test_fixes_must_be_a_list_of_strings(bad):
    _phone, api, _rec = _scanned(_chrome_phone())
    for call in (lambda: api.preview_plan(WLIVE, [], bad), lambda: api.share_plan(WLIVE, [], "ui-1", bad)):
        assert call()["error"]["key"] == "bad_request"
    assert api.execute(WLIVE, [], None, bad)["error"]["key"] == "bad_request"


def test_recheck_site_notifications_replaces_only_that_check():
    phone, api, _rec = _scanned(_chrome_phone())
    before = api._report.results
    phone.channels[CHROME][SITE] = 0
    view = api.recheck_site_notifications()
    (chrome,) = view["check"]["browsers"]
    assert view["check"]["id"] == "site_notifications" and view["check"]["state"] == "ok"
    assert chrome["sites"][0]["blocked"] is True and chrome["sites"][0]["fix"] is None
    assert api._report.results is before
    assert api._report.device_checks[0].state == "ok"
    assert api.rerender()["scan"]["device_checks"][0]["state"] == "ok"


def test_recheck_during_a_shown_plan_keeps_the_checks_the_plan_came_from(monkeypatch):
    from admenot.app import api as api_mod

    phone, api, _rec = _scanned(_chrome_phone())
    real = api_mod.read_site_notifications

    def read_then_open_plan(adb, labels):
        check = real(adb, labels)
        api.preview_plan(WLIVE, [], [])  # serwisant otwiera plan, zanim odczyt wróci
        return check

    monkeypatch.setattr(api_mod, "read_site_notifications", read_then_open_plan)
    phone.channels[CHROME][SITE] = 0
    assert api.recheck_site_notifications()["check"]["state"] == "ok"
    assert api._report.device_checks[0].state == "review"  # wykonanie idzie z pokazanego planu


def test_background_recheck_reads_only_the_socket_until_firefox_debugging_appears():
    phone = make_cli_phone()
    phone.channels = {FIREFOX: {"mozac.feature.webnotifications.generic.channel": 3}}
    phone, api, _rec = _scanned(phone)
    (ff,) = api._report.device_checks[0].browsers
    assert ff.rdp_hint
    assert api.recheck_site_notifications(True) == {"check": None}
    phone.firefox_debugging = True
    assert api.recheck_site_notifications(True)["check"] is not None


def test_failed_firefox_fix_does_not_ask_to_turn_debugging_off(monkeypatch):
    from admenot.engine import device_checks
    from admenot.engine.actions import steps

    phone = make_cli_phone()
    phone.channels = {CHROME: {SITE: 0}}
    phone.firefox_debugging = True
    phone.firefox_perms = {"https://www.example.com": 1}
    monkeypatch.setattr(device_checks, "tcp_connect", phone.rdp_connect)
    monkeypatch.setattr(steps, "tcp_connect", phone.rdp_connect)
    phone, api, rec = _scanned(phone)
    phone.firefox_debugging = False  # wyłączone po skanie: krok się nie udaje
    api.execute({}, [], None, [f"site_perm:{FIREFOX}:https://www.example.com"])
    assert rec.of("exec:done")[0]["firefox_debugging"] is False


def test_recheck_needs_a_scan():
    api, _ = make_api(make_cli_phone())
    assert api.recheck_site_notifications()["error"]["key"] == "no_scan"


def test_recheck_during_the_apk_analysis_survives_its_commit():
    slow = SlowApk()
    phone = _chrome_phone()
    api, rec = make_api(phone, sync=False, apk=slow)
    api.start_scan(SERIAL)
    rec.wait_for("apk:progress")
    phone.channels[CHROME][SITE] = 0
    assert api.recheck_site_notifications()["check"]["state"] == "ok"
    slow.release.set()
    done = rec.wait_for("apk:done")
    assert done["scan"]["device_checks"][0]["state"] == "ok"
    assert api._report.device_checks[0].state == "ok"


def test_step_names_use_the_browser_name_when_the_scan_has_only_the_package():
    from types import SimpleNamespace

    from admenot.app.api import Api

    vivaldi = SimpleNamespace(package="com.vivaldi.browser", name="com.vivaldi.browser")
    report = SimpleNamespace(device_checks=[SimpleNamespace(browsers=[vivaldi])])
    names = Api._with_browsers({"com.vivaldi.browser": "com.vivaldi.browser", "a.b": "Latarka"}, report)
    assert names == {"com.vivaldi.browser": "Vivaldi", "a.b": "Latarka"}
    # nazwa z etykiety aplikacji zostaje
    assert Api._with_browsers({"com.vivaldi.browser": "Moja Vivaldi"}, report) == {"com.vivaldi.browser": "Moja Vivaldi"}
