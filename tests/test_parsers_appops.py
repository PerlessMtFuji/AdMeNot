import pytest

from admenot.engine.parsers.appops import AppOpState, parse_appops

LEGACY = """SYSTEM_ALERT_WINDOW: allow; time=+4m12s123ms ago; duration=+2s
POST_NOTIFICATION: allow; time=+1h ago; rejectTime=+2d ago
RUN_IN_BACKGROUND: ignore
"""

MODERN = """Uid mode: SYSTEM_ALERT_WINDOW: allow
Uid mode: COARSE_LOCATION: foreground
POST_NOTIFICATION: allow
  null=[
    Access: [top-s] 2026-09-26 13:00:00.000 (-1h0m0s0ms)
  ]
SYSTEM_ALERT_WINDOW: allow
  null=[
    Access: [bg-s] 2026-09-26 13:55:48.123 (-4m11s877ms)
    Access: [bg-s] 2026-09-26 12:00:00.000 (-2h0m0s0ms)
    Reject: [bg-s] 2026-09-26 13:59:00.000 (-1m0s0ms)
  ]
"""


def test_parse_legacy_format():
    ops = parse_appops(LEGACY)
    assert ops["SYSTEM_ALERT_WINDOW"].mode == "allow"
    assert ops["SYSTEM_ALERT_WINDOW"].last_access_s == pytest.approx(252.123)
    assert ops["POST_NOTIFICATION"].last_access_s == 3600
    assert ops["RUN_IN_BACKGROUND"] == AppOpState("ignore", None)


def test_parse_modern_format_takes_most_recent_access_and_package_mode():
    ops = parse_appops(MODERN)
    saw = ops["SYSTEM_ALERT_WINDOW"]
    assert saw.mode == "allow"
    assert saw.last_access_s == pytest.approx(251.877)
    assert ops["POST_NOTIFICATION"].last_access_s == 3600
    assert ops["COARSE_LOCATION"] == AppOpState("foreground", None)


def test_uid_mode_does_not_override_package_mode():
    ops = parse_appops("SYSTEM_ALERT_WINDOW: deny\nUid mode: SYSTEM_ALERT_WINDOW: allow\n")
    assert ops["SYSTEM_ALERT_WINDOW"].mode == "deny"


def test_garbage_returns_empty():
    assert parse_appops("Error: Unknown package: com.nope\n") == {}
