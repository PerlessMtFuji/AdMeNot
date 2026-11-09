import dataclasses
import json
import re
from datetime import UTC, datetime, timedelta, timezone

from conftest import SERIAL

from admenot.app import telemetry_events as ev
from admenot.engine.actions.planner import FIX_LEVEL, AppPlan
from admenot.engine.apk.timing import Eta
from admenot.engine.journal.db import Action
from admenot.engine.session import run_scan
from admenot.engine.workflow import AppStatus, OrderResult

PKG_RE = re.compile(r"^[A-Za-z0-9_.]{1,255}$")


def test_hour_rounds_down_in_utc():
    local = datetime(2026, 10, 10, 16, 59, 59, tzinfo=timezone(timedelta(hours=2)))
    assert ev.hour(local) == "2026-10-10T14:00:00Z"


def test_common_fields():
    c = ev.common("id", "scan", datetime(2026, 10, 10, 14, 5, tzinfo=UTC), "pl")
    assert set(c) == {"install", "type", "t", "app", "os", "lang"}
    assert c["t"] == "2026-10-10T14:00:00Z" and c["type"] == "scan"


def test_scan_event_counts_verdicts_without_packages(synthetic_adb):
    report = run_scan(synthetic_adb)
    e = ev.scan_event(report, "ab12cd34", 41, packages=False)
    flagged = [r for r in report.results if r.verdict != "safe"]
    assert e["apps"] == len(report.results)
    assert sum(e["verdicts"].values()) == len(flagged)
    assert set(e["verdicts"]) == {"malicious", "suspicious", "review"}
    assert e["packages"] is None and e["seconds"] == 41 and e["apk_stage"] is False
    assert e["device"] == {"manufacturer": "samsung", "model": "SM-A145R", "android": "14"}


def test_scan_event_lists_only_flagged_packages(synthetic_adb):
    report = run_scan(synthetic_adb)
    e = ev.scan_event(report, "ab12cd34", 41, packages=True)
    flagged = {r.facts.package for r in report.results if r.verdict != "safe"}
    assert {p["package"] for p in e["packages"]} == flagged
    assert set(e["packages"][0]) == {"package", "verdict", "score", "confidence", "system"}


def test_no_serial_or_device_name_anywhere(synthetic_adb):
    report = run_scan(synthetic_adb)
    text = json.dumps(ev.scan_event(report, "ab12cd34", 1, packages=True))
    assert SERIAL not in text and "Telefon Anny" not in text


def _plans():
    return [AppPlan("com.clean.pro.boost", "remove", []), AppPlan("com.user.notes", "disable", [])]


def test_repair_event_sources_levels_and_errors(synthetic_adb):
    device = run_scan(synthetic_adb).device
    result = OrderResult(order=None, stopped=False, apps=[
        AppStatus("com.clean.pro.boost", "ok"),
        AppStatus("com.user.notes", "failed", errors=["admin_refused", "admin_refused"]),
    ])
    verdicts = {"com.clean.pro.boost": "malicious", "com.user.notes": "safe"}
    e = ev.repair_event(device, "ab12cd34", _plans(), verdicts, result, None, packages=True)
    assert e["levels"] == {"silence": 0, "disable": 1, "remove": 1}
    assert e["sources"] == {"flagged": 1, "manual": 1, "blind": 0}
    assert e["failed"] == 1 and e["errors"] == ["admin_refused"] and e["interrupted"] is None
    assert e["packages"] == [
        {"package": "com.clean.pro.boost", "source": "flagged", "level": "remove", "ok": True},
        {"package": "com.user.notes", "source": "manual", "level": "disable", "ok": False},
    ]


def test_repair_event_disconnected_has_unknown_outcome(synthetic_adb):
    device = run_scan(synthetic_adb).device
    e = ev.repair_event(device, "ab12cd34", _plans(), {}, None, "disconnected", packages=True)
    assert e["interrupted"] == "disconnected" and e["failed"] == 0
    assert all(p["ok"] is None for p in e["packages"])


def test_packages_are_capped_and_filtered(synthetic_adb):
    device = run_scan(synthetic_adb).device
    plans = [AppPlan(f"com.app.n{i}", "disable", []) for i in range(250)]
    plans.append(AppPlan("bad name/../x", "disable", []))
    e = ev.repair_event(device, "s", plans, {}, None, None, packages=True)
    assert len(e["packages"]) == ev.MAX_PACKAGES
    assert all(PKG_RE.match(p["package"]) for p in e["packages"])
    assert e["sources"]["manual"] == 251  # liczby obejmują wszystko, lista jest tylko przycięta


def test_undo_event(synthetic_adb):
    device = run_scan(synthetic_adb).device
    e = ev.undo_event(device, ["a.b", "c.d"], ["c.d"], 3, packages=False)
    assert (e["apps"], e["failed"], e["age_days"], e["packages"]) == (2, 1, 3, None)
    e = ev.undo_event(device, ["a.b", "c.d"], ["c.d"], 3, packages=True)
    assert e["packages"] == [{"package": "a.b", "ok": True}, {"package": "c.d", "ok": False}]


def test_undo_targets_leave_out_fix_only_browsers():
    # przeglądarka z samą poprawką ustawień to nie „aplikacja” i jej pakiet nie trafia do telemetrii
    targeted = [_action(1, "com.example.browser", FIX_LEVEL, "channel", "done"),
                _action(2, "com.wlive.forecast", "disable", "enabled", "done"),
                _action(3, "com.android.chrome", FIX_LEVEL, "channel", "done"),
                _action(4, "com.android.chrome", "silence", "permission", "done")]
    errors = [(targeted[0], "not_restored"), (targeted[1], "not_restored")]
    assert ev.undo_targets(targeted, errors) == (["com.android.chrome", "com.wlive.forecast"],
                                                 ["com.wlive.forecast"])


def test_undo_targets_do_not_fail_an_app_for_skipped_or_timed_out_sites():
    # niewłączone witryny liczą się w `sites`/`sites_restored`, nie jako błąd aplikacji
    targeted = [_action(1, "com.android.chrome", "silence", "channel", "done"),
                _action(2, "com.android.chrome", "silence", "channel", "done"),
                _action(3, "com.wlive.forecast", "disable", "enabled", "done")]
    errors = [(targeted[0], "site_skipped"), (targeted[1], "site_timeout"),
              (targeted[2], "site_timeout"), (targeted[2], "not_restored")]
    assert ev.undo_targets(targeted, errors) == (["com.android.chrome", "com.wlive.forecast"],
                                                 ["com.wlive.forecast"])
    assert ev.undo_targets(targeted[:2], errors[:2]) == (["com.android.chrome"], [])


def test_sample_uses_the_same_shapes():
    s = ev.sample()
    assert [e["type"] for e in s["basic"]] == ["start", "scan", "repair", "undo", "transfer_backup",
                                              "transfer_restore", "transfer_apps", "transfer_report", "explorer"]
    no_packages = ("start", "transfer_backup", "transfer_restore", "transfer_apps", "transfer_report", "explorer")  # zdarzenia bez listy pakietów
    assert all(e["packages"] is None for e in s["basic"] if e["type"] not in no_packages)
    assert all(e["packages"] for e in s["packages"] if e["type"] not in no_packages)
    assert all("packages" not in e for e in s["basic"] + s["packages"] if e["type"] in no_packages)
    assert all(e["install"] == ev.SAMPLE_INSTALL for e in s["basic"] + s["packages"])


def test_sample_scan_matches_scan_event_keys(synthetic_adb):
    real = ev.scan_event(run_scan(synthetic_adb), "s", 1, packages=True)
    shown = next(e for e in ev.sample()["packages"] if e["type"] == "scan")
    assert set(real) <= set(shown) and set(shown) - set(real) == {"install", "type", "t", "app", "os", "lang"}
    assert set(real["packages"][0]) == set(shown["packages"][0])


def test_values_fit_server_limits(synthetic_adb):
    # Serwer odrzuca całą paczkę za jedno złe pole — program wysyła tylko to, co serwer przyjmie.
    from dataclasses import replace

    report = run_scan(synthetic_adb)
    odd = replace(report.device, manufacturer="", model="M" * 100, android_release="  ")
    assert ev.device_of(odd) == {"manufacturer": "?", "model": "M" * 64, "android": "?"}
    assert ev.scan_event(replace(report, device=odd), "s", 10**6, packages=False)["seconds"] == 86_400
    long_error = AppStatus("a.b", "failed", errors=["x" * 100, ""])
    result = OrderResult(order=None, stopped=False, apps=[long_error])
    e = ev.repair_event(odd, "s", [AppPlan("a.b", "disable", [])], {}, result, None, packages=False)
    assert e["errors"] == ["x" * 64]
    assert len(ev.common("id", "start", datetime(2026, 10, 10, tzinfo=UTC), "pl")["os"]) <= 64


def test_scan_event_carries_mode_and_eta(scan_report):
    body = ev.scan_event(dataclasses.replace(scan_report, apk_mode="manual"), "ab12cd34", 5, False,
                         apk_stage=True, eta=Eta(600, "rough", 360, 900))
    assert body["apk_mode"] == "manual" and body["eta"] == {"kind": "rough", "seconds": 600}
    assert ev.scan_event(scan_report, "ab12cd34", 5, False)["eta"] is None


def test_repair_event_marks_blind_picks():
    plans = [AppPlan("com.a", "remove", []), AppPlan("com.b", "disable", [])]
    body = ev.repair_event(ev._SAMPLE_DEVICE, "ab12cd34", plans, {"com.a": "malicious"}, None, None,
                           True, blind=frozenset({"com.a", "com.b"}))
    assert body["sources"] == {"flagged": 0, "manual": 0, "blind": 2}
    assert {p["source"] for p in body["packages"]} == {"blind"}


def test_ui_sample_json_matches_sample_and_shows_a_quick_scan():
    # Plik „co wysyłamy” w UI (atrapa mostu) = `sample()`; wersja programu zmienia się z wydaniem.
    from pathlib import Path

    path = Path(__file__).parent.parent / "ui" / "src" / "lib" / "telemetrySample.json"
    shown = json.loads(path.read_text("utf-8"))

    def strip(s):
        return {k: [{**e, "app": None} for e in v] for k, v in s.items()}

    assert strip(shown) == strip(ev.sample())
    scan = next(e for e in ev.sample()["basic"] if e["type"] == "scan")
    assert scan["apk_stage"] is False and scan["apk_mode"] == "pending" and scan["eta"] is None
    assert scan["apk"] is None


def _site_phone():
    from fakephone import make_cli_phone

    phone = make_cli_phone()
    phone.channels = {"com.android.chrome": {"web:https://www.example.com;1": 3,
                                              "web:https://b.example.org;2": 0},
                      "com.sec.android.app.sbrowser": {"SBROWSER_WEBSITES_NOTIFICATION_CHANNEL": 3}}
    phone.active = [("com.sec.android.app.sbrowser", "SBROWSER_WEBSITES_NOTIFICATION_CHANNEL",
                     "p#https://news.example.net/#1", "news.example.net")]
    return phone


def test_scan_event_reports_check_state_and_site_counts_without_domains():
    e = ev.scan_event(run_scan(_site_phone()), "ab12cd34", 5, packages=True)
    assert e["checks"] == {"site_notifications": "review"}
    assert e["sites"] == {"per_site": 2, "shared": 1, "rdp": 0}
    assert "example" not in json.dumps(e) and "sbrowser" not in json.dumps(e)


def _action(aid, package, level, kind, status):
    return Action(aid, 1, package, level, {"kind": kind, "package": package, "params": {}}, "cmd",
                  {}, None, status, datetime(2026, 10, 10, tzinfo=UTC), None)


def test_repair_event_counts_fix_steps_and_keeps_them_out_of_app_stats():
    from admenot.engine.actions.steps import Step

    site = "web:https://www.example.com;1"
    plans = [AppPlan("com.android.chrome", FIX_LEVEL,
                     [Step("channel", "com.android.chrome", {"channel_id": site}),
                      Step("channel", "com.android.chrome", {"channel_id": "web:https://b.pl;2"})]),
             AppPlan("org.mozilla.firefox", FIX_LEVEL,
                     [Step("site_permission", "org.mozilla.firefox",
                           {"origin": "https://www.example.com", "permission": "desktop-notification",
                            "capability": "2"})]),
             AppPlan("com.wlive.forecast", "disable", [])]
    # Liczą się kroki wykonane („wykonanych” w spec), nie zaplanowane: pominięty kanał nie wchodzi.
    actions = [_action(1, "com.android.chrome", FIX_LEVEL, "channel", "done"),
               _action(2, "com.android.chrome", FIX_LEVEL, "channel", "failed"),
               _action(3, "org.mozilla.firefox", FIX_LEVEL, "site_permission", "done"),
               _action(4, "com.wlive.forecast", "disable", "enabled", "done")]
    body = ev.repair_event(ev._SAMPLE_DEVICE, "ab12cd34", plans, {}, None, None, True, actions=actions)
    assert body["fixes"] == {"channel": 1, "site_permission": 1}
    assert ev.repair_event(ev._SAMPLE_DEVICE, "s", plans, {}, None, None, False)["fixes"] == {
        "channel": 0, "site_permission": 0}  # przerwane przed pierwszym krokiem: nic nie wykonano
    assert body["levels"] == {"silence": 0, "disable": 1, "remove": 0}
    assert sum(body["sources"].values()) == 1
    assert [p["package"] for p in body["packages"]] == ["com.wlive.forecast"]
    assert "example" not in json.dumps(body)
    assert ev.repair_event(ev._SAMPLE_DEVICE, "s", [], {}, None, None, False)["fixes"] == {
        "channel": 0, "site_permission": 0}


def test_undo_event_counts_sites(synthetic_adb):
    device = run_scan(synthetic_adb).device
    e = ev.undo_event(device, ["a.b"], [], 1, packages=False, sites=3, sites_restored=2)
    assert (e["sites"], e["sites_restored"]) == (3, 2)
    e = ev.undo_event(device, ["a.b"], [], 1, packages=False)
    assert (e["sites"], e["sites_restored"]) == (0, 0)


def test_repair_event_does_not_count_a_browser_with_only_a_site_fix_as_a_failed_app():
    plans = [AppPlan("com.a", "silence", []), AppPlan("com.android.chrome", FIX_LEVEL, [])]
    result = OrderResult(order=None, stopped=False, apps=[
        AppStatus("com.a", "ok"), AppStatus("com.android.chrome", "failed", errors=["user_timeout"])])
    body = ev.repair_event(ev._SAMPLE_DEVICE, "s", plans, {}, result, None, False)
    assert body["levels"]["silence"] == 1 and body["failed"] == 0 and body["errors"] == []


def _backup_result(**kw):
    from admenot.engine.transfer.backup import BackupResult
    from admenot.engine.transfer.telephony import CategoryResult

    opts = {"status": "incomplete", "copy_id": "R58T00TEST_ab12/20261025-120000",
            "telephony": {"sms": CategoryResult("ok", 3)}, "files_done": 10, "files_failed": 2,
            "apps_done": 1, "apps_failed": 1, "bytes": 2_600_000, "seconds": 75}
    opts.update(kw)
    return BackupResult(**opts)


def _selection(**kw):
    from admenot.engine.transfer.backup import Selection

    opts = {"contacts": False, "sms": True, "mms": False, "calls": False,
            "categories": frozenset({"media"}), "others": frozenset({"Music", ""}),
            "apps": frozenset({"com.whatsapp"})}
    opts.update(kw)
    return Selection(**opts)


def test_transfer_backup_event_has_only_numbers_and_flags():
    body = ev.transfer_backup_event(ev._SAMPLE_DEVICE, _backup_result(), _selection())
    assert body == {
        "device": {"manufacturer": "OPPO", "model": "CPH2483", "android": "14"},
        "status": "incomplete", "seconds": 75, "bytes_mb": 3, "files": 10, "files_failed": 2,
        "apps": 1, "apps_failed": 1,
        "categories": {"contacts": False, "sms": True, "mms": False, "calls": False, "media": True,
                       "downloads": False, "whatsapp": False, "others": True, "apps": True}}
    text = json.dumps(body)
    assert "Music" not in text and "com.whatsapp" not in text and "R58T00TEST" not in text


def test_transfer_backup_event_fits_server_limits():
    body = ev.transfer_backup_event(
        ev._SAMPLE_DEVICE, _backup_result(seconds=10**7, bytes=10**20, files_done=10**9),
        _selection(others=frozenset(), apps=frozenset()))
    assert body["seconds"] == 86_400 and body["bytes_mb"] == ev.MAX_MB
    assert body["files"] == ev.MAX_COUNT
    assert body["categories"]["others"] is False and body["categories"]["apps"] is False


def _restore_result(**kw):
    from admenot.engine.transfer.restore import RestoreResult

    opts = {"status": "incomplete", "target_serial": "R58NEW00001", "files_done": 40, "files_exists": 3,
            "files_renamed": 2, "files_denied": 1, "files_failed": 1, "files_unselected": 7,
            "apk_skipped": 1, "apk_suspicious_skipped": 2, "bytes": 2_600_000, "seconds": 75,
            "hashed": False, "media_scan": "done", "files_missing": 4}
    opts.update(kw)
    return RestoreResult(**opts)


def _upload_choice(groups=("photos", "whatsapp", "other:Music"), apks_on=("/sdcard/Download/gra.apk",)):
    from admenot.engine.transfer.restore import UploadChoice

    return UploadChoice(frozenset(groups), frozenset(apks_on))


def test_transfer_restore_event_has_only_numbers_and_flags():
    body = ev.transfer_restore_event(ev._SAMPLE_DEVICE, _restore_result(), _upload_choice(), 4)
    assert body == {
        "device": {"manufacturer": "OPPO", "model": "CPH2483", "android": "14"},
        "status": "incomplete", "seconds": 75, "bytes_mb": 3, "files": 40, "exists": 3, "renamed": 2,
        "denied": 1, "failed": 1, "unselected": 7, "missing": 4, "apk_skipped": 1,
        "apk_suspicious_skipped": 2, "streams": 4, "hashed": False, "media_scan": "done",
        "groups": {"photos": True, "videos": False, "downloads": False, "whatsapp": True, "others": True}}
    text = json.dumps(body)
    for name in ("Music", "gra.apk", "Download", "sdcard", "R58NEW00001"):
        assert name not in text, name


def test_transfer_restore_event_fits_server_limits():
    body = ev.transfer_restore_event(
        ev._SAMPLE_DEVICE, _restore_result(seconds=10**7, bytes=10**20, files_done=10**9, media_scan="skipped"),
        _upload_choice(groups=("videos",)), 99)
    assert body["seconds"] == 86_400 and body["bytes_mb"] == ev.MAX_MB and body["files"] == ev.MAX_COUNT
    assert body["streams"] == 8 and body["media_scan"] == "skipped"
    assert body["groups"]["others"] is False and body["groups"]["videos"] is True


def _tel_result(stopped=False):
    from admenot.engine.transfer.phonesetup import CleanupResult
    from admenot.engine.transfer.restore_tel import TelKindResult, TelResult
    from admenot.engine.transfer.telfile import ManualStep

    kinds = {"contacts": TelKindResult(written=3, existed=1, skipped_synced=4, skipped_messenger=2, failed=0,
                                       manual=0, path="app_process", visible_warning=False),
             "sms": TelKindResult(5, 0, 0, 0, 1, 2, "file", True)}
    return TelResult(kinds, {"contacts": True, "sms": False},
                     [ManualStep("sms", "/sdcard/Download/AdMeNot-SMS-Jan Kowalski.xml")],
                     CleanupResult(True, True, False, True), {"jan.kowalski@gmail.com": 4}, 30, stopped)


def test_transfer_restore_event_with_tel_has_only_numbers():
    body = ev.transfer_restore_event(ev._SAMPLE_DEVICE, _restore_result(status="complete"), _upload_choice(), 4,
                                     _tel_result())
    assert body["tel"] == {
        "contacts": {"written": 3, "existed": 1, "skipped": 6, "failed": 0, "manual": 0, "path": "app_process",
                     "visible_warning": False},
        "sms": {"written": 5, "existed": 0, "skipped": 0, "failed": 1, "manual": 2, "path": "file",
                "visible_warning": True}}
    assert body["safety"] == {"contacts": True, "sms": False} and body["cleanup_ok"] is False
    assert body["status"] == "incomplete"  # pliki skończone, telefonia z plikiem do ręcznego importu
    text = json.dumps(body)
    for name in ("jan.kowalski", "gmail", "Kowalski", "AdMeNot-SMS", "Download"):
        assert name not in text, name


def test_transfer_restore_event_tel_status_and_limits():
    stopped = ev.transfer_restore_event(ev._SAMPLE_DEVICE, _restore_result(status="complete"), _upload_choice(),
                                        4, _tel_result(stopped=True))
    assert stopped["status"] == "stopped"
    files_only = ev.transfer_restore_event(ev._SAMPLE_DEVICE, _restore_result(), _upload_choice(), 4)
    assert not {"tel", "safety", "cleanup_ok"} & set(files_only)
    import dataclasses as dc
    big = _tel_result()
    big = dc.replace(big, kinds={"calls": dc.replace(big.kinds["sms"], written=10**9)})
    body = ev.transfer_restore_event(ev._SAMPLE_DEVICE, _restore_result(), _upload_choice(), 4, big)
    assert body["tel"]["calls"]["written"] == ev.MAX_COUNT


def test_sample_contains_explorer():
    for variant in ("basic", "packages"):
        shown = next(e for e in ev.sample()[variant] if e["type"] == "explorer")
        assert set(shown) - {"install", "type", "t", "app", "os", "lang"} == {
            "device", "seconds", "copied_files", "copied_mb", "uploaded_files", "uploaded_mb", "previews",
            "created", "errors", "mb_s"}
        assert set(shown["previews"]) == {"image", "video", "audio", "text"}
        assert set(shown["created"]) == {"folder", "text"}
        assert "packages" not in shown


def test_explorer_event_numbers_limits_and_error_keys():
    body = ev.explorer_event(ev._SAMPLE_DEVICE, 10**7, 3, 2_600_000, 10**9, 10**20, {"image": 2, "x": 5},
                             {"folder": 1}, {"explorer_denied": 2, "file_size": 1, "C:/Users/Jan/a.jpg": 1,
                                             "zero": 0},
                             [0.0, 30_000_000.0, 20_000_000.0, 50_000_000.0])
    assert body == {
        "device": {"manufacturer": "OPPO", "model": "CPH2483", "android": "14"},
        "seconds": 86_400, "copied_files": 3, "copied_mb": 3, "uploaded_files": ev.MAX_COUNT,
        "uploaded_mb": ev.MAX_MB, "previews": {"image": 2, "video": 0, "audio": 0, "text": 0},
        "created": {"folder": 1, "text": 0}, "errors": {"explorer_denied": 2, "file_size": 1}, "mb_s": 30}
    idle = ev.explorer_event(ev._SAMPLE_DEVICE, 5, 0, 0, 0, 0, {}, {}, {}, [])
    assert idle["mb_s"] is None and idle["errors"] == {}


def _apps_result(**kw):
    from admenot.engine.transfer.apps import AppsResult

    opts = {"selected": 12, "installed": 7, "exists": 2, "skipped": {"too_old": 1, "no_abi": 1},
            "failed": {"user_restricted": 1, "no_space": 1}, "codes": {"INSTALL_FAILED_USER_RESTRICTED": 1},
            "blocked": True, "stopped": False,
            "rows": [{"package": "com.secret.app", "label": "Tajna Aplikacja", "status": "failed",
                      "reason": "user_restricted"}], "play_installer": True}
    opts.update(kw)
    return AppsResult(**opts)


def test_restore_event_apps_counts_only():
    body = ev.transfer_restore_event(ev._SAMPLE_DEVICE, _restore_result(), _upload_choice(), 4,
                                     apps=_apps_result())
    assert body["apps"] == {"selected": 12, "installed": 7, "exists": 2, "skipped": 2, "failed": 2}
    assert body["apps_codes"] == {"user_restricted": 1, "no_space": 1}
    assert body["installer"] == "play" and body["apps_blocked"] is True
    text = json.dumps(body)
    for name in ("com.secret.app", "Tajna", "INSTALL_FAILED", "R58NEW00001"):
        assert name not in text, name
    plain = ev.transfer_restore_event(ev._SAMPLE_DEVICE, _restore_result(), _upload_choice(), 4)
    assert not {"apps", "apps_codes", "installer", "apps_blocked"} & set(plain)


def test_apps_event_shape_limits_and_error_keys_only():
    body = ev.transfer_apps_event(ev._SAMPLE_DEVICE, _apps_result(
        installed=10**9, play_installer=False, failed={"failed": 3, "zly klucz": 2, "INSTALL_FAILED_X": 1}))
    assert set(body) == {"device", "apps", "apps_codes", "installer", "apps_blocked"}
    assert body["apps"]["installed"] == ev.MAX_COUNT and body["installer"] == "none"
    assert body["apps_codes"] == {"failed": 3}
    many = ev.transfer_apps_event(ev._SAMPLE_DEVICE, _apps_result(failed={f"k{i}": 1 for i in range(30)}))
    assert many["apps_codes"] == {}


def test_transfer_report_event_shape():
    assert ev.transfer_report_event("warn", True) == {"status": "warn", "whatsapp_restored": True}
    assert ev.transfer_report_event("ok", False) == {"status": "ok", "whatsapp_restored": False}
