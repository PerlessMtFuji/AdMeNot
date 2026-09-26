import threading
import time
from datetime import datetime
from unittest import mock

from demalware.engine.adb.fake import FakeAdb
from demalware.engine.adb.transport import AdbError
from demalware.engine.collectors.base import run_collectors
from demalware.engine.collectors.behavior import (
    APPOPS_GET, NOTIFICATIONS, USAGESTATS, AppOpsCollector, NotificationsCollector,
    UsageStatsCollector,
)
from demalware.engine.collectors.components import (
    BOOT_QUERY, HOME_QUERY, LAUNCHER_QUERY, ComponentsCollector,
)
from demalware.engine.collectors.registry import default_collectors
from demalware.engine.collectors.system import (
    A11Y_SERVICES, DEVICE_POLICY, NOTIF_LISTENERS, RESOLVE_HOME, ROLE_HOME,
    DevicePolicyCollector, HomeRoleCollector, SecureSettingsCollector,
)
from demalware.engine.facts import AppFacts

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
        DEVICE_POLICY: ("  Enabled Device Admins (User 0, provisioningState: 0):\n"
                        "    com.b/.Admin:\n      uid=1\n"),
        ROLE_HOME: AdbError("command_failed", "Unknown command"),
        RESOLVE_HOME: "priority=0\n  com.b/.FakeHome\n",
        A11Y_SERVICES: "com.a/.Svc\n",
        NOTIF_LISTENERS: "null\n",
    })
    facts = _facts()
    status = run_collectors(
        adb, facts, [DevicePolicyCollector(), HomeRoleCollector(), SecureSettingsCollector()]
    )
    assert all(s.ok for s in status.values())
    assert facts["com.b"].is_device_admin and facts["com.b"].is_home_holder
    assert facts["com.a"].accessibility_enabled and not facts["com.a"].notification_listener


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
    original_parse_appops = __import__('demalware.engine.parsers.appops', fromlist=['parse_appops']).parse_appops

    def patched_parse(text):
        if "BROKEN" in text:
            raise ValueError("malformed appops output")
        return original_parse_appops(text)

    with mock.patch('demalware.engine.collectors.behavior.parse_appops', side_effect=patched_parse):
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


def test_default_collectors_names():
    names = [c.name for c in default_collectors(NOW)]
    assert names == ["components", "appops", "notifications", "usagestats",
                     "device_policy", "home_role", "secure_settings"]
