from demalware.engine.capture import anonymize
from demalware.engine.collectors.behavior import ALARM
from demalware.engine.parsers.alarm import AlarmStats, parse_alarm_stats

ALARM_OUT = """Current Alarm Manager state:
  Pending alarm batches: 2
    RTC_WAKEUP #0: Alarm{1 type 0 com.clean.x}
      tag=*walarm*:com.clean.x/.Ad user anna.k@example.com
  Top Alarms:
    +24s264ms running, 12 wakeups, 12 alarms: u0a245:com.clean.x
      *walarm*:com.clean.x/.AdReceiver
  
  Alarm Stats:
  1000:android +2m33s171ms running, 649 wakeups:
    +1m40s616ms 0 wakes 134 alarms, last -18m46s228ms:
      *alarm*:com.android.server.action.NETWORK_STATS_POLL
    +13s730ms 234 wakes 234 alarms, last -10m54s473ms:
      *walarm*:*job.deadline*
  u0a245:com.clean.x +24s264ms running, 12 wakeups:
    +24s264ms 12 wakes 12 alarms, last -5m2s11ms:
      *walarm*:com.clean.x/.AdReceiver token=SECRET-123
  u0a250:com.whatsapp +3s running, 0 wakeups:
    +3s 0 wakes 5 alarms, last -1h2m:
      *alarm*:com.whatsapp.messaging.MessageService
  Alarm manager stats:
    Total alarms: 1
"""


def test_parse_alarm_stats():
    stats = parse_alarm_stats(ALARM_OUT)
    assert stats["android"] == AlarmStats(wakeups=649, alarms=368)
    assert stats["com.clean.x"] == AlarmStats(wakeups=12, alarms=12)
    assert stats["com.whatsapp"] == AlarmStats(wakeups=0, alarms=5)
    assert set(stats) == {"android", "com.clean.x", "com.whatsapp"}  # „Top Alarms” pominięte


def test_parse_alarm_stats_without_section():
    assert parse_alarm_stats("Current Alarm Manager state:\n  Settings:\n") is None


def test_anonymize_alarm_keeps_only_stats_lines():
    out = anonymize(ALARM, ALARM_OUT, "R58T00TEST")
    assert "SECRET-123" not in out and "anna.k" not in out and "walarm" not in out
    assert "Pending alarm" not in out
    assert parse_alarm_stats(out) == parse_alarm_stats(ALARM_OUT)
