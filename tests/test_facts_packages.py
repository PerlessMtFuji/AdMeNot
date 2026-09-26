from datetime import datetime

import pytest

from demalware.engine.adb.fake import FakeAdb
from demalware.engine.adb.transport import AdbError
from demalware.engine.collectors.packages import (
    DUMPSYS_PACKAGES,
    PM_DISABLED,
    PM_LIST,
    PM_SYSTEM,
    collect_packages,
)
from demalware.engine.facts import FACT_NAMES, AppFacts
from demalware.engine.parsers.appops import AppOpState

NOW = datetime(2026, 9, 26, 14, 0, 0)


def test_appfacts_properties():
    f = AppFacts("com.x", installer="com.android.vending", notif_interruptions_24h=48,
                 appops={"SYSTEM_ALERT_WINDOW": AppOpState("allow", 30.0)})
    assert f.from_play is True
    assert f.notif_per_hour_24h == 2.0
    assert f.overlay_last_access_s == 30.0
    empty = AppFacts("com.y")
    assert (empty.from_play, empty.notif_per_hour_24h, empty.overlay_last_access_s) == (False, None, None)


def test_fact_names_include_fields_and_properties():
    assert {"package", "is_system", "granted_permissions", "from_play",
            "notif_per_hour_24h", "overlay_last_access_s"} <= FACT_NAMES


def _adb(dumpsys: str | AdbError) -> FakeAdb:
    return FakeAdb({
        PM_LIST: ("package:/data/app/~~a==/com.a-1==/base.apk=com.a  installer=com.android.chrome uid:10301\n"
                  "package:/system/app/B/B.apk=com.b  installer=null uid:10090\n"),
        PM_SYSTEM: "package:com.b\n",
        PM_DISABLED: "package:com.b\n",
        DUMPSYS_PACKAGES: dumpsys,
    })


DUMP = """Packages:
  Package [com.a] (1):
    versionCode=7 minSdk=24 targetSdk=33
    firstInstallTime=2026-09-20 14:00:00
    installerPackageName=com.android.chrome
    requested permissions:
      android.permission.SYSTEM_ALERT_WINDOW
    install permissions:
      android.permission.INTERNET: granted=true
"""


def test_collect_packages_merges_sources():
    facts = collect_packages(_adb(DUMP), NOW)
    a, b = facts["com.a"], facts["com.b"]
    assert (a.installer, a.uid, a.is_system, a.enabled, a.version_code) == (
        "com.android.chrome", 10301, False, True, 7)
    assert a.installed_days == pytest.approx(6.0)
    assert a.requested_permissions == {"android.permission.SYSTEM_ALERT_WINDOW"}
    assert a.granted_permissions == {"android.permission.INTERNET"}
    assert (b.is_system, b.enabled, b.installer) == (True, False, None)


def test_collect_packages_survives_dumpsys_failure():
    facts = collect_packages(_adb(AdbError("timeout", "slow")), NOW)
    assert set(facts) == {"com.a", "com.b"}
    assert facts["com.a"].version_code is None


def test_collect_packages_ignores_install_time_after_device_clock():
    # Zegar telefonu cofnięty (np. 2010): firstInstallTime "w przyszłości" nie może dać ujemnego wieku.
    facts = collect_packages(_adb(DUMP), datetime(2010, 1, 4, 0, 41, 0))
    assert facts["com.a"].first_install == datetime(2026, 9, 20, 14, 0, 0)
    assert facts["com.a"].installed_days is None
