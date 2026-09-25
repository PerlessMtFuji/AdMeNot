from datetime import datetime

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


def test_parse_notifications_without_section():
    assert parse_notifications("Current Notification Manager state:\n") == {}


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
