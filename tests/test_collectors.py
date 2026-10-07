import threading
import time
from datetime import datetime
from unittest import mock

import pytest

from admenot.engine.adb.fake import FakeAdb
from admenot.engine.adb.transport import AdbError
from admenot.engine.collectors.base import run_collectors
from admenot.engine.collectors.behavior import (
    ALARM,
    APPOPS_GET,
    NOTIFICATIONS,
    USAGESTATS,
    AlarmCollector,
    AppOpsCollector,
    NotificationsCollector,
    UsageStatsCollector,
)
from admenot.engine.collectors.components import (
    BOOT_QUERY,
    HOME_QUERY,
    LAUNCHER_QUERY,
    ComponentsCollector,
)
from admenot.engine.collectors.registry import default_collectors
from admenot.engine.collectors.system import (
    A11Y_SERVICES,
    DEVICE_POLICY,
    NOTIF_LISTENERS,
    NOTIF_MANAGER,
    RESOLVE_HOME,
    ROLE_BROWSER,
    ROLE_HOME,
    ROLE_SMS,
    DevicePolicyCollector,
    RolesCollector,
    SecureSettingsCollector,
)
from admenot.engine.facts import AppFacts
from admenot.engine.parsers.common import UnrecognizedOutput, query_packages

NOW = datetime(2026, 9, 26, 14, 0, 0)


def _facts():
    return {
        "com.a": AppFacts("com.a"),
        "com.b": AppFacts("com.b"),
        "com.sys": AppFacts("com.sys", is_system=True),
    }


def test_components_collector():
    adb = FakeAdb({
        LAUNCHER_QUERY: "priority=0\n  com.a/.Main\n",
        HOME_QUERY: "priority=0\n  com.sys/.Home\n  com.b/.FakeHome\n",
        BOOT_QUERY: "priority=0\n  com.b/.Boot\n",
    })
    facts = _facts()
    status = run_collectors(adb, facts, [ComponentsCollector()])
    assert status["components"].ok
    assert (facts["com.a"].has_launcher_icon, facts["com.b"].has_launcher_icon) == (True, False)
    assert facts["com.b"].is_home_candidate and facts["com.b"].has_boot_receiver


def test_appops_collector_skips_system_and_failed_packages():
    adb = FakeAdb({
        APPOPS_GET.format(package="com.a"): "SYSTEM_ALERT_WINDOW: allow; time=+10s ago\n",
        APPOPS_GET.format(package="com.b"): AdbError("command_failed", "unknown package"),
    })
    facts = _facts()
    status = run_collectors(adb, facts, [AppOpsCollector()])
    assert status["appops"].ok
    assert facts["com.a"].overlay_last_access_s == 10
    assert facts["com.b"].appops == {}
    assert APPOPS_GET.format(package="com.sys") not in adb.calls


def test_notifications_and_usagestats_collectors():
    adb = FakeAdb({
        NOTIFICATIONS: ("  Notification List:\n    NotificationRecord(0x1: pkg=com.a user=0)\n"
                        "      fullscreenIntent=PendingIntent{1: x}\n"),
        USAGESTATS: ('      time="2026-09-26 13:00:00" type=NOTIFICATION_INTERRUPTION package=com.a\n'),
    })
    facts = _facts()
    status = run_collectors(adb, facts, [NotificationsCollector(), UsageStatsCollector(NOW)])
    assert status["notifications"].ok and status["usagestats"].ok
    assert (facts["com.a"].notif_active, facts["com.a"].notif_fsi) == (1, True)
    assert facts["com.a"].notif_interruptions_24h == 1
    assert facts["com.b"].notif_interruptions_24h == 0


def test_usagestats_without_events_is_not_ok():
    facts = _facts()
    status = run_collectors(FakeAdb({USAGESTATS: "user=0\n"}), facts, [UsageStatsCollector(NOW)])
    assert not status["usagestats"].ok
    assert facts["com.a"].notif_interruptions_24h is None


def test_system_collectors_with_home_fallback():
    adb = FakeAdb({
        DEVICE_POLICY: ("Current Device Policy Manager state:\n"
                        "  Enabled Device Admins (User 0, provisioningState: 0):\n"
                        "    com.b/.Admin:\n      uid=1\n"),
        ROLE_HOME: AdbError("command_failed", "Unknown command"),
        RESOLVE_HOME: "priority=0\n  com.b/.FakeHome\n",
        A11Y_SERVICES: "com.a/.Svc\n",
        NOTIF_LISTENERS: "null\n",
    })
    facts = _facts()
    status = run_collectors(
        adb, facts, [DevicePolicyCollector(), RolesCollector(), SecureSettingsCollector()]
    )
    assert all(s.ok for s in status.values())
    assert facts["com.b"].is_device_admin and facts["com.b"].is_home_holder
    assert facts["com.a"].accessibility_enabled and not facts["com.a"].notification_listener


def test_listener_access_from_notification_manager_not_the_stale_setting():
    # To samo źródło co krok naprawy: wpis tylko w kopii nie daje dostępu i nie ma czego odebrać.
    adb = FakeAdb({
        A11Y_SERVICES: "null\n",
        NOTIF_LISTENERS: "com.b/.Listener\n",
        NOTIF_MANAGER: ("  Notification listeners:\n    Allowed notification listeners:\n"
                        "      com.a/.Listener (user: 0 isPrimary: true)\n"),
    })
    facts = _facts()
    run_collectors(adb, facts, [SecureSettingsCollector()])
    assert facts["com.a"].notification_listener and not facts["com.b"].notification_listener


def test_listener_access_from_setting_when_notification_manager_unreadable():
    adb = FakeAdb({
        A11Y_SERVICES: "null\n",
        NOTIF_LISTENERS: "com.b/.Listener\n",
        NOTIF_MANAGER: ("  Notification listeners:\n    Allowed notification listeners:\n"
                        "      com.a/.Listener [user 0, primary]\n"),
    })
    facts = _facts()
    run_collectors(adb, facts, [SecureSettingsCollector()])
    assert facts["com.b"].notification_listener and not facts["com.a"].notification_listener


class _Exploding:
    name = "exploding"

    def collect(self, adb, apps):
        raise IndexError("unexpected OEM format")

    def apply(self, facts, data):
        raise AssertionError("apply must not run")


def test_broken_collector_does_not_stop_others():
    adb = FakeAdb({NOTIFICATIONS: "  Notification List:\n"})
    status = run_collectors(adb, _facts(), [_Exploding(), NotificationsCollector()])
    assert not status["exploding"].ok
    assert "IndexError" in status["exploding"].error
    assert status["notifications"].ok


def test_appops_collector_handles_parser_errors():
    """Malformed appops output for one package doesn't fail the collector."""
    original_parse_appops = __import__('admenot.engine.parsers.appops', fromlist=['parse_appops']).parse_appops

    def patched_parse(text):
        if "BROKEN" in text:
            raise ValueError("malformed appops output")
        return original_parse_appops(text)

    with mock.patch('admenot.engine.collectors.behavior.parse_appops', side_effect=patched_parse):
        adb = FakeAdb({
            APPOPS_GET.format(package="com.a"): "SYSTEM_ALERT_WINDOW: allow; time=+10s ago\n",
            APPOPS_GET.format(package="com.b"): "BROKEN\n",
        })
        facts = _facts()
        status = run_collectors(adb, facts, [AppOpsCollector()])
        assert status["appops"].ok
        assert facts["com.a"].overlay_last_access_s == 10
        assert facts["com.b"].appops == {}


def test_run_collectors_respects_deadline():
    """Timeout is an overall deadline; timed-out collectors don't apply."""
    event = threading.Event()

    class BlockingCollector:
        name = "blocking"

        def collect(self, adb, apps):
            event.wait(timeout=5.0)  # Wait up to 5 seconds
            return "data"

        def apply(self, facts, data):
            raise AssertionError("apply must not run if collect timed out")

    adb = FakeAdb({NOTIFICATIONS: "  Notification List:\n"})
    start = time.monotonic()
    status = run_collectors(
        adb, _facts(), [BlockingCollector(), NotificationsCollector()], timeout=0.3
    )
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"function took {elapsed}s, should return quickly"
    assert not status["blocking"].ok
    assert status["blocking"].error == "timeout"
    assert status["notifications"].ok

    event.set()  # Let the blocking thread exit


def test_failed_collector_marks_gaps_only_for_covered_apps():
    facts = _facts()
    status = run_collectors(FakeAdb({APPOPS_GET.format(package="com.a"): AdbError("timeout", "x"),
                                     APPOPS_GET.format(package="com.b"): AdbError("timeout", "x")}),
                            facts, [AppOpsCollector()])
    assert not status["appops"].ok
    assert "appops" in facts["com.a"].gaps and "appops" in facts["com.b"].gaps
    assert "appops" not in facts["com.sys"].gaps  # AppOps nie obejmuje aplikacji systemowych


def test_appops_failure_for_one_app_is_a_gap_of_that_app():
    adb = FakeAdb({
        APPOPS_GET.format(package="com.a"): "SYSTEM_ALERT_WINDOW: allow; time=+10s ago\n",
        APPOPS_GET.format(package="com.b"): AdbError("command_failed", "unknown package"),
    })
    facts = _facts()
    status = run_collectors(adb, facts, [AppOpsCollector()])
    assert status["appops"].ok and status["appops"].partial == ["com.b"]
    assert facts["com.a"].gaps == set() and facts["com.b"].gaps == {"appops"}


def test_whole_collector_failure_marks_every_app():
    facts = _facts()
    run_collectors(FakeAdb({NOTIFICATIONS: AdbError("timeout", "slow")}), facts,
                   [NotificationsCollector()])
    assert all("notifications" in f.gaps for f in facts.values())


def test_default_collectors_names():
    names = [c.name for c in default_collectors(NOW, uptime_s=3600)]
    assert names == ["components", "appops", "notifications", "usagestats", "alarm",
                     "device_policy", "roles", "secure_settings"]


def test_alarm_collector_window_uses_uptime_and_install_age():
    adb = FakeAdb({ALARM: "  Alarm Stats:\n  u0a1:com.a +1s running, 30 wakeups:\n"
                          "  u0a2:com.b +1s running, 30 wakeups:\n"})
    facts = _facts()
    facts["com.b"].installed_days = 0.01  # 14 min temu → okno ograniczone do 1 h
    status = run_collectors(adb, facts, [AlarmCollector(uptime_s=10 * 3600)])
    assert status["alarm"].ok
    assert facts["com.a"].alarm_wakeups_per_hour == 3.0
    assert facts["com.b"].alarm_wakeups_per_hour == 30.0
    assert facts["com.sys"].alarm_wakeups == 0


def test_alarm_collector_unknown_format_is_not_ok():
    status = run_collectors(FakeAdb({ALARM: "garbage\n"}), _facts(), [AlarmCollector(3600)])
    assert not status["alarm"].ok


def test_roles_collector_reads_browser_and_sms():
    adb = FakeAdb({ROLE_HOME: "com.sys\n", ROLE_BROWSER: "com.a\n", ROLE_SMS: "com.b\n"})
    facts = _facts()
    status = run_collectors(adb, facts, [RolesCollector()])
    assert status["roles"].ok
    assert facts["com.sys"].is_home_holder
    assert facts["com.a"].is_browser_holder and not facts["com.a"].is_sms_holder
    assert facts["com.b"].is_sms_holder


def test_roles_collector_tolerates_missing_browser_and_sms():
    adb = FakeAdb({ROLE_HOME: "com.sys\n"})  # starsze nagranie / Android < 10
    facts = _facts()
    status = run_collectors(adb, facts, [RolesCollector()])
    assert status["roles"].ok and facts["com.sys"].is_home_holder
    assert not any(f.is_browser_holder or f.is_sms_holder for f in facts.values())


def test_query_packages_accepts_headers_and_components():
    assert query_packages("2 activities found:\n  Activity #0:\n    com.a/.Main\n") == {"com.a"}
    assert query_packages("No receivers found\n") == set()
    assert query_packages("priority=0\n  com.a/.Main\n") == {"com.a"}


def test_query_packages_rejects_unknown_formats():
    for text in ("", "Error: unknown command\n", "3 activities found:\n  Activity #0: <hidden>\n"):
        with pytest.raises(UnrecognizedOutput):
            query_packages(text)
    with pytest.raises(UnrecognizedOutput):
        query_packages("No activities found\n", expect_some=True)


def test_unrecognized_launcher_list_is_a_gap_not_hidden_icons():
    adb = FakeAdb({LAUNCHER_QUERY: "Error: something new\n", HOME_QUERY: "priority=0\n  com.sys/.Home\n",
                   BOOT_QUERY: "No receivers found\n"})
    facts = _facts()
    status = run_collectors(adb, facts, [ComponentsCollector()])
    assert not status["components"].ok
    assert all(f.has_launcher_icon is None and "components" in f.gaps for f in facts.values())


def test_unrecognized_notifications_are_a_gap():
    facts = _facts()
    status = run_collectors(FakeAdb({NOTIFICATIONS: "Totally different dump\n"}), facts,
                            [NotificationsCollector()])
    assert not status["notifications"].ok
    assert all("notifications" in f.gaps for f in facts.values())


def test_appops_unparseable_output_for_one_app_is_a_gap():
    adb = FakeAdb({
        APPOPS_GET.format(package="com.a"): "SYSTEM_ALERT_WINDOW: allow; time=+10s ago\n",
        APPOPS_GET.format(package="com.b"): "?? vendor text ??\n",
    })
    facts = _facts()
    run_collectors(adb, facts, [AppOpsCollector()])
    assert facts["com.b"].gaps == {"appops"}


def test_appops_covers_system_apps_that_can_draw_over_others():
    facts = _facts()
    facts["com.sys.saw"] = AppFacts("com.sys.saw", is_system=True,
                                    requested_permissions={"android.permission.SYSTEM_ALERT_WINDOW"})
    adb = FakeAdb({APPOPS_GET.format(package=p): "SYSTEM_ALERT_WINDOW: allow; time=+10s ago\n"
                   for p in ("com.a", "com.b", "com.sys.saw")})
    run_collectors(adb, facts, [AppOpsCollector()])
    assert facts["com.sys.saw"].overlay_last_access_s == 10
    assert APPOPS_GET.format(package="com.sys") not in adb.calls


def test_appops_no_operations_is_a_confirmed_absence():
    adb = FakeAdb({APPOPS_GET.format(package="com.a"): "No operations.\n",
                   APPOPS_GET.format(package="com.b"): "SYSTEM_ALERT_WINDOW: allow\n"})
    facts = _facts()
    run_collectors(adb, facts, [AppOpsCollector()])
    assert facts["com.a"].gaps == set() and facts["com.a"].appops == {}


def test_unrecognized_device_policy_is_a_gap():
    facts = _facts()
    status = run_collectors(FakeAdb({DEVICE_POLICY: "Permission Denial\n"}), facts,
                            [DevicePolicyCollector()])
    assert not status["device_policy"].ok
    assert all("device_policy" in f.gaps for f in facts.values())


def test_alarm_failure_is_not_a_gap_of_system_apps():
    """Przegląd końcowy M3: DM-ALARM-01 dotyczy tylko aplikacji niesystemowych."""
    facts = _facts()
    status = run_collectors(FakeAdb({ALARM: AdbError("timeout", "slow")}), facts,
                            [AlarmCollector(3600)])
    assert not status["alarm"].ok
    assert "alarm" in facts["com.a"].gaps and "alarm" in facts["com.b"].gaps
    assert "alarm" not in facts["com.sys"].gaps
