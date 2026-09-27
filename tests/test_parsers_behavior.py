from datetime import datetime

import pytest

from demalware.engine.parsers.common import UnrecognizedOutput
from demalware.engine.parsers.notifications import NotifStats, parse_notifications
from demalware.engine.parsers.usagestats import UsageCounts, parse_usage_events

NOTIF = """Current Notification Manager state:
  Notification List:
    NotificationRecord(0x0a1: pkg=com.clean.pro user=UserHandle{0} id=7 tag=null importance=4 key=0|com.clean.pro|7|null|10301: Notification(channel=ads))
      uid=10301 userId=0
      fullscreenIntent=PendingIntent{5f3: android.os.BinderProxy@1}
    NotificationRecord(0x0a2: pkg=com.clean.pro user=UserHandle{0} id=8 tag=null importance=4 key=0|com.clean.pro|8|null|10301: Notification(channel=ads))
      fullscreenIntent=null
    NotificationRecord(0x0b2: pkg=com.whatsapp user=UserHandle{0} id=1 tag=null importance=4 key=0|com.whatsapp|1|null|10250: Notification(channel=msg))
      fullscreenIntent=null
  Snoozed notifications:
    NotificationRecord(0x0c3: pkg=com.whatsapp user=UserHandle{0} id=2 tag=null)
      fullscreenIntent=PendingIntent{9: x}
"""


def test_parse_notifications_counts_only_notification_list():
    stats = parse_notifications(NOTIF)
    assert stats == {
        "com.clean.pro": NotifStats(active=2, fsi=True),
        "com.whatsapp": NotifStats(active=1, fsi=False),
    }


def test_parse_notifications_without_section_is_unrecognized():
    with pytest.raises(UnrecognizedOutput):
        parse_notifications("Current Notification Manager state:\n")


def test_parse_notifications_empty_list_is_a_confirmed_absence():
    assert parse_notifications("  Notification List:\n  Snoozed notifications:\n") == {}


def test_parse_notifications_records_without_package_are_unrecognized():
    with pytest.raises(UnrecognizedOutput):
        parse_notifications("  Notification List:\n    NotificationRecord(0x1: something)\n")


NOW = datetime(2026, 9, 26, 14, 0, 0)

USAGE = """user=0
  In-memory daily stats
    events
      time="2026-09-26 13:00:00" type=NOTIFICATION_INTERRUPTION package=com.wlive channelId=ads
      time="2026-09-26 12:00:00" type=NOTIFICATION_INTERRUPTION package=com.wlive channelId=ads
      time="2026-09-26 11:00:00" type=ACTIVITY_RESUMED package=com.whatsapp class=com.whatsapp.Main
      time="2026-09-24 11:00:00" type=NOTIFICATION_INTERRUPTION package=com.wlive channelId=ads
  In-memory weekly stats
    events
      time="2026-09-26 13:00:00" type=NOTIFICATION_INTERRUPTION package=com.wlive channelId=ads
      time="2026-09-26 12:00:00" type=NOTIFICATION_INTERRUPTION package=com.wlive channelId=ads
      time="2026-09-25 20:00:00" type=MOVE_TO_FOREGROUND package=com.whatsapp class=com.whatsapp.Main
"""


def test_parse_usage_events_dedupes_and_windows():
    counts = parse_usage_events(USAGE, NOW)
    assert counts == {
        "com.wlive": UsageCounts(notif_interruptions=2, foreground=0),
        "com.whatsapp": UsageCounts(notif_interruptions=0, foreground=2),
    }


def test_parse_usage_events_returns_none_without_events():
    assert parse_usage_events("user=0\n  In-memory daily stats\n", NOW) is None


UNLOCK_NOW = datetime(2026, 9, 26, 14, 0, 0)


def _ev(hms, event_type, package="android"):
    return f'    time="2026-09-26 {hms}" type={event_type} package={package} flags=0x0'


def _usage(*events):
    body = "\n".join(events)
    return f"  In-memory daily stats\n    events\n{body}\n  In-memory weekly stats\n    events\n{body}\n"


def test_unlock_launch_counted_once_despite_duplicate_sections():
    text = _usage(
        _ev("10:00:00", "ACTIVITY_RESUMED", "com.user.chat"),
        _ev("10:01:00", "SCREEN_NON_INTERACTIVE"),
        _ev("11:00:00", "SCREEN_INTERACTIVE"),
        _ev("11:00:02", "ACTIVITY_RESUMED", "com.clean.x"),
        _ev("11:00:03", "ACTIVITY_RESUMED", "com.other.ad"),  # tylko pierwsza aktywność się liczy
        _ev("12:00:00", "SCREEN_NON_INTERACTIVE"),
        _ev("12:30:00", "KEYGUARD_HIDDEN"),
        _ev("12:30:05", "ACTIVITY_RESUMED", "com.clean.x"),
    )
    counts = parse_usage_events(text, UNLOCK_NOW)
    assert counts["com.clean.x"].unlock_launches == 2
    assert "com.other.ad" not in counts or counts["com.other.ad"].unlock_launches == 0


def test_returning_to_previous_app_after_unlock_is_not_counted():
    text = _usage(
        _ev("10:00:00", "ACTIVITY_RESUMED", "com.user.chat"),
        _ev("10:01:00", "SCREEN_NON_INTERACTIVE"),
        _ev("11:00:00", "SCREEN_INTERACTIVE"),
        _ev("11:00:01", "ACTIVITY_RESUMED", "com.user.chat"),
    )
    assert parse_usage_events(text, UNLOCK_NOW)["com.user.chat"].unlock_launches == 0


def test_late_resume_after_unlock_is_not_counted():
    text = _usage(
        _ev("11:00:00", "SCREEN_INTERACTIVE"),
        _ev("11:00:30", "ACTIVITY_RESUMED", "com.clean.x"),
    )
    assert parse_usage_events(text, UNLOCK_NOW)["com.clean.x"].unlock_launches == 0


def test_unlock_launches_outside_24h_window_ignored():
    text = _usage(
        '    time="2026-09-24 11:00:00" type=SCREEN_INTERACTIVE package=android flags=0x0',
        '    time="2026-09-24 11:00:01" type=ACTIVITY_RESUMED package=com.clean.x flags=0x0',
    )
    counts = parse_usage_events(text, UNLOCK_NOW)
    assert "com.clean.x" not in counts or counts["com.clean.x"].unlock_launches == 0
