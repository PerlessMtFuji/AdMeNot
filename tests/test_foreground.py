from pathlib import Path

import pytest

from admenot.engine.adb.fake import FakeAdb
from admenot.engine.adb.transport import AdbError
from admenot.engine.foreground import (
    ACTIVITIES,
    WINDOWS,
    Foreground,
    parse_overlay_windows,
    parse_resumed,
    read_foreground,
)

REC = Path(__file__).parent / "fixtures" / "foreground"

ACT_12 = """ACTIVITY MANAGER ACTIVITIES (dumpsys activity activities)
Display #0 (activities from top to bottom):
  topResumedActivity=ActivityRecord{e3a1b u0 com.clean.x/.ui.AdActivity t812}
"""
ACT_OLD = "  mResumedActivity: ActivityRecord{77 u0 com.old.app/.Main t5}\n"
WIN = """WINDOW MANAGER WINDOWS (dumpsys window windows)
  Window #4 Window{aa1 u0 com.clean.x}:
    mOwnerUid=10301 showForAllUsers=false package=com.clean.x appop=SYSTEM_ALERT_WINDOW
    mAttrs={(0,0)(fillxfill) ty=APPLICATION_OVERLAY fmt=TRANSLUCENT}
    mViewVisibility=0x0 mHaveFrame=true mObscured=false
    isOnScreen=true
  Window #3 Window{bb2 u0 com.chat.heads}:
    mAttrs={(0,0)(wrapxwrap) ty=APPLICATION_OVERLAY fmt=TRANSLUCENT}
    mViewVisibility=0x8 mHaveFrame=true
    isOnScreen=false
  Window #2 Window{cc3 u0 com.clean.x}:
    mAttrs={(0,0)(fillxfill) ty=2038 fmt=TRANSLUCENT}
    isOnScreen=true
  Window #1 Window{dd4 u0 com.android.systemui}:
    mAttrs={(0,0)(fillxwrap) ty=STATUS_BAR fmt=TRANSLUCENT}
    isOnScreen=true
"""

# Układ z nagrania OPPO (Android 12): tytuł okna to nie pakiet, właściciel jest w `package=`,
# `isOnScreen` rozstrzyga nad `mViewVisibility`, a sekcja „Destroy #” to okna w trakcie usuwania.
WIN_OPPO_LAYOUT = """WINDOW MANAGER WINDOWS (dumpsys window windows)
  Window #3 Window{1a u0 FloatingBall}:
    mOwnerUid=10301 showForAllUsers=false package=com.float.ads appop=SYSTEM_ALERT_WINDOW
    mAttrs={(0,0)(wrapxwrap) gr=TOP LEFT ty=APPLICATION_OVERLAY fmt=TRANSLUCENT
      fl=NOT_FOCUSABLE LAYOUT_IN_SCREEN}
    mViewVisibility=0x0 mHaveFrame=true mObscured=false
    isOnScreen=true
    isVisible=true
  Window #2 Window{2b u0 HiddenBubble}:
    mOwnerUid=10302 showForAllUsers=false package=com.hidden.bubble appop=SYSTEM_ALERT_WINDOW
    mAttrs={(0,0)(wrapxwrap) ty=APPLICATION_OVERLAY fmt=TRANSLUCENT}
    mViewVisibility=0x0 mHaveFrame=true mObscured=false
    isOnScreen=false
  Window #1 Window{3c u10 com.work.overlay}:
    mOwnerUid=1010303 showForAllUsers=false package=com.work.overlay appop=SYSTEM_ALERT_WINDOW
    mAttrs={(0,0)(wrapxwrap) ty=APPLICATION_OVERLAY fmt=TRANSLUCENT}
    isOnScreen=true

  Windows waiting to destroy their surface:
  Destroy #0 Window{4d u0 com.gone.ads}:
    mOwnerUid=10304 showForAllUsers=false package=com.gone.ads appop=SYSTEM_ALERT_WINDOW
    mAttrs={(0,0)(wrapxwrap) ty=APPLICATION_OVERLAY fmt=TRANSLUCENT}
    isOnScreen=true
"""


def test_parse_resumed_android_12_and_older():
    assert parse_resumed(ACT_12) == "com.clean.x"
    assert parse_resumed(ACT_OLD) == "com.old.app"
    assert parse_resumed("nothing") is None


def test_parse_resumed_oppo_android_12_line():
    line = "  ResumedActivity: ActivityRecord{56183b3 u0 com.intelli.clean/com.star.Launcher t94}\n"
    assert parse_resumed(line) == "com.intelli.clean"


def test_parse_overlay_windows_only_visible_overlays_once():
    assert parse_overlay_windows(WIN) == ["com.clean.x"]


def test_parse_overlay_windows_uses_owner_package_and_skips_destroyed_and_other_users():
    assert parse_overlay_windows(WIN_OPPO_LAYOUT) == ["com.float.ads"]


def test_read_foreground_tolerates_failures():
    fg = read_foreground(FakeAdb({ACTIVITIES: ACT_12, WINDOWS: AdbError("timeout", "slow")}))
    assert fg.resumed == "com.clean.x" and fg.overlays is None and fg.errors == ["windows: slow"]


def test_read_foreground_empty_overlays_only_when_windows_were_read():
    fg = read_foreground(FakeAdb({ACTIVITIES: AdbError("timeout", "slow"), WINDOWS: WIN.splitlines()[0]}))
    assert fg.resumed is None and fg.overlays == [] and fg.errors == ["activities: slow"]


@pytest.mark.skipif(not (REC / "oppo-windows.txt").exists(), reason="brak nagrania z telefonu")
def test_recorded_oppo_output_parses():
    # Nagranie z OPPO CPH2271 (Android 12) z wygaszonym ekranem: aplikacja na pierwszym planie
    # to ostatnio wznowiona aktywność, żadne okno nie jest narysowane nad innymi.
    activities = (REC / "oppo-activities.txt").read_text("utf-8")
    windows = (REC / "oppo-windows.txt").read_text("utf-8")
    assert parse_resumed(activities) == "com.intelli.clean"
    assert parse_overlay_windows(windows) == []


def test_foreground_default_overlays_are_unknown_not_empty():
    """Przegląd końcowy M6: domyślnie „nie wiadomo”, nigdy „brak okien nad innymi”."""
    assert Foreground("com.x").overlays is None
