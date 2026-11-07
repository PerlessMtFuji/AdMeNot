from fakephone import make_cli_phone

from admenot.engine.actions.steps import check_step
from admenot.engine.adb.transport import AdbError
from admenot.engine.device_checks import (
    APP_BROWSER_QUERY,
    APP_BROWSER_QUERY_PLAIN,
    BROWSER_QUERY,
    BROWSER_QUERY_PLAIN,
    fix_steps,
    read_device_checks,
    read_site_notifications,
)
from admenot.engine.session import report_to_dict, run_scan

CHROME = "com.android.chrome"
SBROWSER = "com.sec.android.app.sbrowser"
SB_CHANNEL = "SBROWSER_WEBSITES_NOTIFICATION_CHANNEL"
FIREFOX = "org.mozilla.firefox"
FF_CHANNEL = "mozac.feature.webnotifications.generic.channel"
DUMP = "dumpsys notification --noredact"


def _phone(**kw):
    phone = make_cli_phone()
    phone.channels = {CHROME: {"web:https://a.pl;1": 3, "web:https://b.pl;2": 3}}
    for key, value in kw.items():
        setattr(phone, key, value)
    return phone


def test_chrome_sites_listed_with_active_first():
    phone = _phone(active=[(CHROME, "web:https://b.pl;2", "", None)])
    check = read_site_notifications(phone)
    (chrome,) = check.browsers
    assert (chrome.package, chrome.name, chrome.mode, chrome.read) == (CHROME, "Chrome", "per_site", "ok")
    assert [(s.host, s.active) for s in chrome.sites] == [("b.pl", True), ("a.pl", False)]
    assert chrome.sites[1].fix == f"site:{CHROME}:web:https://a.pl;1"


def test_blocked_site_has_no_fix():
    phone = _phone()
    phone.channels[CHROME]["web:https://a.pl;1"] = 0
    sites = {s.host: s for s in read_site_notifications(phone).browsers[0].sites}
    assert sites["a.pl"].blocked and sites["a.pl"].fix is None
    assert not sites["b.pl"].blocked and sites["b.pl"].fix


def test_state_review_when_any_site_enabled_and_ok_when_none():
    phone = _phone()
    assert read_site_notifications(phone).state == "review"
    phone.channels[CHROME] = {"web:https://a.pl;1": 0}
    assert read_site_notifications(phone).state == "ok"


def test_chromium_browser_without_sites_is_listed_as_checked():
    phone = _phone(browsers=[CHROME, "com.vivaldi.browser"])
    phone.channels["com.vivaldi.browser"] = {"browser": 2}
    phone.channel_groups = {"com.vivaldi.browser": ["general", "sites"]}
    check = read_site_notifications(phone, {"com.vivaldi.browser": "Vivaldi"})
    vivaldi = next(b for b in check.browsers if b.package == "com.vivaldi.browser")
    assert (vivaldi.name, vivaldi.mode, vivaldi.read, vivaldi.sites) == ("Vivaldi", "per_site", "ok", [])
    assert [b.package for b in check.browsers].count(CHROME) == 1


def test_browser_read_neither_way_is_unsupported_not_hidden():
    phone = _phone(browsers=["com.example.odd"], app_browsers=["com.example.odd"])
    phone.channels = {"com.example.odd": {"push": 3}}
    check = read_site_notifications(phone, {"com.example.odd": "Odd"})
    (odd,) = check.browsers
    assert (odd.name, odd.mode, odd.read, odd.all_fix) == ("Odd", "unknown", "unsupported", None)
    assert check.state == "review"


def test_link_handler_that_is_not_a_browser_is_skipped():
    """Otwieracz linków albo menedżer plików przechwytuje każdy link http, ale nie jest przeglądarką."""
    handlers = ["app.traced", "filemanager.files.fileexplorer.android.folder"]
    phone = _phone(browsers=handlers)
    phone.channels.update({"app.traced": {"service": 3},
                           "filemanager.files.fileexplorer.android.folder": {"downloads": 3}})
    check = read_site_notifications(phone)
    assert [b.package for b in check.browsers] == [CHROME]


def test_named_browser_without_app_browser_category_is_still_unsupported():
    phone = _phone(browsers=["com.yandex.browser"])
    phone.channels = {"com.yandex.browser": {"push": 3}}
    (yandex,) = read_site_notifications(phone).browsers
    assert (yandex.name, yandex.read) == ("Yandex Browser", "unsupported")


def test_without_the_app_browser_list_only_named_browsers_count():
    phone = _phone(browsers=["com.yandex.browser", "com.example.odd"], app_browsers=["com.example.odd"])
    phone.channels = {"com.yandex.browser": {"push": 3}, "com.example.odd": {"push": 3}}
    phone.fail[APP_BROWSER_QUERY] = AdbError("command_failed", "boom")
    phone.fail[APP_BROWSER_QUERY_PLAIN] = "garbage"
    assert [b.package for b in read_site_notifications(phone).browsers] == ["com.yandex.browser"]


def test_browser_without_site_notifications_is_skipped():
    phone = _phone(browsers=["com.opera.mini.native", "com.mi.globalbrowser"])
    phone.channels["com.opera.mini.native"] = {"status_saver": 3}
    phone.channels["com.mi.globalbrowser"] = {"downloads": 3}
    assert [b.package for b in read_site_notifications(phone).browsers] == [CHROME]


def test_browser_without_channels_or_unreadable_list_adds_nothing():
    phone = _phone(browsers=["com.example.fresh"])
    assert [b.package for b in read_site_notifications(phone).browsers] == [CHROME]
    phone.fail[BROWSER_QUERY] = "garbage"
    phone.fail[BROWSER_QUERY_PLAIN] = AdbError("command_failed", "boom")
    phone.browsers = ["com.example.odd"]
    phone.channels["com.example.odd"] = {"push": 3}
    assert [b.package for b in read_site_notifications(phone).browsers] == [CHROME]


def test_browser_list_falls_back_to_plain_query_without_query_flags():
    phone = _phone(browsers=["com.example.odd"], app_browsers=["com.example.odd"])
    phone.channels["com.example.odd"] = {"push": 3}
    phone.fail[BROWSER_QUERY] = "Error: Unknown option: --query-flags\n"
    phone.fail[APP_BROWSER_QUERY] = "Error: Unknown option: --query-flags\n"
    packages = [b.package for b in read_site_notifications(phone).browsers]
    assert packages == [CHROME, "com.example.odd"]
    assert phone.calls.index(BROWSER_QUERY) < phone.calls.index(BROWSER_QUERY_PLAIN)
    assert phone.calls.index(APP_BROWSER_QUERY) < phone.calls.index(APP_BROWSER_QUERY_PLAIN)


def test_unknown_package_with_web_channels_is_per_site_named_by_package_or_label():
    phone = _phone()
    phone.channels = {"org.example.browser": {"web:https://a.pl;1": 3}}
    assert read_site_notifications(phone).browsers[0].name == "org.example.browser"
    named = read_site_notifications(phone, {"org.example.browser": "Przeglądarka"})
    assert named.browsers[0].name == "Przeglądarka"


def test_sbrowser_is_partial_with_sites_from_active_notifications_and_all_fix():
    phone = _phone()
    phone.channels = {SBROWSER: {SB_CHANNEL: 3}}
    phone.active = [(SBROWSER, SB_CHANNEL, "p#https://web-push-book.gauntface.com/#1",
                     "web-push-book.gauntface.com")]
    check = read_site_notifications(phone)
    (sb,) = check.browsers
    assert (sb.mode, sb.read, sb.rdp_hint) == ("shared", "partial", False)
    assert [(s.origin, s.active, s.fix) for s in sb.sites] == [
        ("https://web-push-book.gauntface.com", True, None)]
    assert sb.all_fix == f"site_all:{SBROWSER}"
    assert check.state == "review"


def test_blocked_shared_channel_is_ok_without_fix():
    phone = _phone()
    phone.channels = {SBROWSER: {SB_CHANNEL: 0}}
    check = read_site_notifications(phone)
    assert check.browsers[0].all_fix is None and check.state == "ok"


def test_firefox_without_debugging_partial_with_hint():
    phone = _phone()
    phone.channels = {FIREFOX: {FF_CHANNEL: 3}}
    phone.active = [(FIREFOX, FF_CHANNEL, "", "a.pl")]
    (ff,) = read_site_notifications(phone).browsers
    assert (ff.mode, ff.read, ff.rdp_hint) == ("shared", "partial", True)
    assert [s.origin for s in ff.sites] == ["https://a.pl"]
    assert ff.all_fix == f"site_all:{FIREFOX}"


def test_firefox_with_debugging_uses_rdp_permissions():
    phone = _phone(firefox_debugging=True,
                   firefox_perms={"https://a.pl": 1, "https://b.pl": 2})
    phone.channels = {FIREFOX: {FF_CHANNEL: 3}}
    phone.active = [(FIREFOX, FF_CHANNEL, "", "a.pl")]
    (ff,) = read_site_notifications(phone).browsers
    assert (ff.mode, ff.read, ff.rdp_hint) == ("rdp", "ok", False)
    by_host = {s.host: s for s in ff.sites}
    assert by_host["a.pl"].fix == f"site_perm:{FIREFOX}:https://a.pl" and by_host["a.pl"].active
    assert by_host["b.pl"].blocked and by_host["b.pl"].fix is None
    assert ff.sites[0].host == "a.pl"  # aktywna na górze


def test_firefox_rdp_failure_falls_back_to_partial_with_hint():
    phone = _phone(firefox_debugging=True)
    phone.channels = {FIREFOX: {FF_CHANNEL: 3}}

    def refuse(port):
        raise ConnectionRefusedError("nothing listens")

    phone.rdp_connect = refuse
    (ff,) = read_site_notifications(phone).browsers
    assert (ff.mode, ff.read, ff.rdp_hint) == ("shared", "partial", True)


def test_unrecognized_dump_gives_unrecognized_not_ok():
    phone = _phone()
    phone.static[DUMP] = "garbage\n"
    assert read_site_notifications(phone).state == "unrecognized"
    # lista powiadomień bez sekcji AppSettings: parser zwraca puste kanały, to nie „brak witryn”
    phone.static[DUMP] = "Current Notification Manager state:\n  Notification List:\n"
    assert read_site_notifications(phone).state == "unrecognized"
    # sekcje AppSettings są, ale kanałów w innym formacie nie da się odczytać: nie „ok”
    phone.static[DUMP] = ("Current Notification Manager state:\n  Notification List:\n"
                          "      AppSettings: com.android.chrome (10113)\n"
                          "        Channel[id=web:https://a.pl;1, importance=3]\n")
    assert read_site_notifications(phone).state == "unrecognized"


def test_read_device_checks_never_raises():
    phone = _phone()
    phone.fail[DUMP] = AdbError("no_device", "gone")
    (check,) = read_device_checks(phone)
    assert (check.id, check.state, check.browsers) == ("site_notifications", "unrecognized", [])


def test_site_with_unsafe_origin_listed_without_fix():
    phone = _phone()
    phone.channels = {CHROME: {"web:https://a.pl$(reboot);1": 3, "web:https://b.pl;2": 3}}
    sites = {s.host: s for s in read_site_notifications(phone).browsers[0].sites}
    assert sites["a.pl$(reboot)"].fix is None and sites["b.pl"].fix


def test_fix_steps_only_for_offered_fixes():
    checks = read_device_checks(_phone())
    fix = f"site:{CHROME}:web:https://a.pl;1"
    package, step = fix_steps(fix, checks)
    check_step(step)
    assert (package, step.kind, step.params) == (CHROME, "channel", {"channel_id": "web:https://a.pl;1"})
    assert fix_steps(f"site:{CHROME}:web:https://zz.pl;9", checks) is None
    assert fix_steps("site_perm:org.mozilla.firefox:https://a.pl", checks) is None
    assert fix_steps("nonsense", checks) is None


def test_site_all_and_site_perm_steps():
    phone = _phone(firefox_debugging=True, firefox_perms={"https://a.pl": 1})
    phone.channels = {SBROWSER: {SB_CHANNEL: 3}, FIREFOX: {FF_CHANNEL: 3}}
    checks = read_device_checks(phone)
    _, all_step = fix_steps(f"site_all:{SBROWSER}", checks)
    assert all_step.params == {"channel_id": SB_CHANNEL}
    _, perm = fix_steps(f"site_perm:{FIREFOX}:https://a.pl", checks)
    assert perm.params == {"origin": "https://a.pl", "permission": "desktop-notification",
                           "capability": "2"}
    check_step(all_step)
    check_step(perm)


def test_scan_report_carries_device_checks_and_serializes():
    report = run_scan(_phone())
    assert [c.id for c in report.device_checks] == ["site_notifications"]
    data = report_to_dict(report)["device_checks"]
    assert data[0]["state"] == "review" and data[0]["browsers"][0]["package"] == CHROME


def test_scan_survives_missing_notification_data():
    phone = _phone()
    phone.fail[DUMP] = AdbError("command_failed", "boom")
    report = run_scan(phone)
    assert report.device_checks[0].state == "unrecognized"
