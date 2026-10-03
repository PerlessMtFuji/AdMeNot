"""Syntetyczny Galaxy A14: adware (com.clean.pro.boost), spam powiadomień (com.wlive.forecast),
zaufany komunikator (com.whatsapp) i systemowy launcher (com.sec.android.app.launcher)."""

from datetime import datetime, timedelta

import pytest

from admenot.engine.adb.fake import FakeAdb
from admenot.engine.collectors.behavior import ALARM, APPOPS_GET, NOTIFICATIONS, USAGESTATS
from admenot.engine.collectors.components import BOOT_QUERY, HOME_QUERY, LAUNCHER_QUERY
from admenot.engine.collectors.packages import (
    DUMPSYS_PACKAGES,
    PM_DISABLED,
    PM_LIST,
    PM_SYSTEM,
)
from admenot.engine.collectors.system import (
    A11Y_SERVICES,
    DEVICE_POLICY,
    NOTIF_LISTENERS,
    ROLE_BROWSER,
    ROLE_HOME,
    ROLE_SMS,
)
from admenot.engine.device.info import GETPROP, LOCAL_NOW, UPTIME

SERIAL = "R58T00TEST"
NOW = datetime(2026, 9, 26, 14, 0, 0)

SYNTHETIC_DEVICES = (
    "List of devices attached\n"
    f"{SERIAL}             device usb:1-1 product:a14xx model:SM_A145R device:a14 transport_id:3\n"
)

GETPROP_OUT = f"""[ro.product.brand]: [samsung]
[ro.product.manufacturer]: [samsung]
[ro.product.model]: [SM-A145R]
[ro.product.device]: [a14]
[ro.build.version.release]: [14]
[ro.build.version.sdk]: [34]
[ro.build.version.security_patch]: [2026-07-01]
[ro.serialno]: [{SERIAL}]
[persist.sys.device_name]: [Telefon Anny]
"""

PM_LIST_OUT = (
    "package:/data/app/~~Rg8wIz5ZcWJ2cUNYmbzZ2w==/com.clean.pro.boost-a1B2==/base.apk="
    "com.clean.pro.boost  installer=com.android.chrome uid:10301\n"
    "package:/data/app/~~x9==/com.whatsapp-q==/base.apk=com.whatsapp"
    "  installer=com.android.vending uid:10250\n"
    "package:/data/app/~~y7==/com.wlive.forecast-z==/base.apk=com.wlive.forecast"
    "  installer=com.android.vending uid:10260\n"
    "package:/system/priv-app/TouchWizHome/TouchWizHome.apk=com.sec.android.app.launcher"
    "  installer=null uid:10090\n"
)

DUMPSYS_PACKAGES_OUT = """Packages:
  Package [com.clean.pro.boost] (b1a2c3):
    userId=10301
    versionCode=7 minSdk=24 targetSdk=33
    firstInstallTime=2026-09-20 10:00:00
    lastUpdateTime=2026-09-20 10:00:00
    installerPackageName=com.android.chrome
    requested permissions:
      android.permission.INTERNET
      android.permission.SYSTEM_ALERT_WINDOW
      android.permission.RECEIVE_BOOT_COMPLETED
      android.permission.QUERY_ALL_PACKAGES
      android.permission.USE_FULL_SCREEN_INTENT
      android.permission.POST_NOTIFICATIONS
    install permissions:
      android.permission.INTERNET: granted=true
      android.permission.RECEIVE_BOOT_COMPLETED: granted=true
      android.permission.QUERY_ALL_PACKAGES: granted=true
    User 0: ceDataInode=1 installed=true enabled=0
      runtime permissions:
        android.permission.POST_NOTIFICATIONS: granted=true, flags=[ USER_SET ]
  Package [com.whatsapp] (c1):
    versionCode=242000 minSdk=21 targetSdk=34
    firstInstallTime=2025-01-10 09:00:00
    installerPackageName=com.android.vending
    requested permissions:
      android.permission.POST_NOTIFICATIONS
  Package [com.wlive.forecast] (d1):
    versionCode=31 minSdk=23 targetSdk=34
    firstInstallTime=2026-06-01 12:00:00
    installerPackageName=com.android.vending
    requested permissions:
      android.permission.POST_NOTIFICATIONS
  Package [com.sec.android.app.launcher] (e1):
    versionCode=150000 minSdk=34 targetSdk=34
    firstInstallTime=2008-12-31 16:00:00
    installerPackageName=null
    requested permissions:
      android.permission.QUERY_ALL_PACKAGES

Hidden system packages:
  Package [com.sec.android.app.launcher] (f1):
    versionCode=1
"""

NOTIFICATIONS_OUT = """Current Notification Manager state:
  Notification List:
    NotificationRecord(0x0a1: pkg=com.clean.pro.boost user=UserHandle{0} id=7 tag=null importance=4 key=0|com.clean.pro.boost|7|null|10301: Notification(channel=ads))
      uid=10301 userId=0
      fullscreenIntent=PendingIntent{5f3: android.os.BinderProxy@1}
      tickerText=null
    NotificationRecord(0x0b2: pkg=com.whatsapp user=UserHandle{0} id=1 tag=null importance=4 key=0|com.whatsapp|1|null|10250: Notification(channel=msg))
      uid=10250 userId=0
      fullscreenIntent=null
      tickerText=Anna: hej, jutro o 10? pisz na anna.k@example.com
  Snoozed notifications:
"""


def _events(package: str, event_type: str, count: int, step_s: int) -> list[str]:
    lines = []
    for i in range(count):
        when = NOW - timedelta(minutes=1) - timedelta(seconds=i * step_s)
        lines.append(f'      time="{when:%Y-%m-%d %H:%M:%S}" type={event_type} package={package}')
    return lines


def _usagestats() -> str:
    events = (
        _events("com.wlive.forecast", "NOTIFICATION_INTERRUPTION", 500, 170)
        + _events("com.clean.pro.boost", "NOTIFICATION_INTERRUPTION", 20, 600)
        + _events("com.whatsapp", "NOTIFICATION_INTERRUPTION", 10, 3600)
        + _events("com.whatsapp", "ACTIVITY_RESUMED", 5, 3600)
    )
    body = "\n".join(events)
    # te same zdarzenia w sekcji daily i weekly — parser nie może liczyć ich podwójnie
    return f"user=0\n  In-memory daily stats\n    events\n{body}\n  In-memory weekly stats\n    events\n{body}\n"


def make_synthetic_adb(devices_output: str = SYNTHETIC_DEVICES) -> FakeAdb:
    responses = {
        GETPROP: GETPROP_OUT,
        UPTIME: "280000.12 500000.00\n",
        LOCAL_NOW: f"{NOW:%Y-%m-%d %H:%M:%S}\n",
        PM_LIST: PM_LIST_OUT,
        PM_SYSTEM: "package:com.sec.android.app.launcher\n",
        PM_DISABLED: "",
        DUMPSYS_PACKAGES: DUMPSYS_PACKAGES_OUT,
        LAUNCHER_QUERY: ("priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\n"
                         "  com.whatsapp/.Main\n"
                         "priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\n"
                         "  com.wlive.forecast/com.wlive.forecast.MainActivity\n"),
        HOME_QUERY: ("priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\n"
                     "  com.sec.android.app.launcher/com.android.launcher3.uioverrides.QuickstepLauncher\n"),
        BOOT_QUERY: "priority=0\n  com.clean.pro.boost/.BootReceiver\n",
        APPOPS_GET.format(package="com.clean.pro.boost"): (
            "Uid mode: SYSTEM_ALERT_WINDOW: allow\n"
            "POST_NOTIFICATION: allow\n  null=[\n"
            "    Access: [bg-s] 2026-09-26 13:50:00.000 (-10m0s0ms)\n  ]\n"
            "SYSTEM_ALERT_WINDOW: allow\n  null=[\n"
            "    Access: [bg-s] 2026-09-26 13:55:48.123 (-4m11s877ms)\n  ]\n"
        ),
        APPOPS_GET.format(package="com.whatsapp"): (
            "POST_NOTIFICATION: allow\n  null=[\n"
            "    Access: [top-s] 2026-09-26 13:00:00.000 (-1h0m0s0ms)\n  ]\n"
        ),
        APPOPS_GET.format(package="com.wlive.forecast"): "POST_NOTIFICATION: allow; time=+2m ago\n",
        NOTIFICATIONS: NOTIFICATIONS_OUT,
        USAGESTATS: _usagestats(),
        ALARM: ("Current Alarm Manager state:\n  Alarm Stats:\n"
                "  u0a301:com.clean.pro.boost +1m2s running, 600 wakeups:\n"
                "    +1m2s 600 wakes 600 alarms, last -2m1s12ms:\n"
                "      *walarm*:com.clean.pro.boost/.AdReceiver\n"
                "  u0a250:com.whatsapp +3s running, 20 wakeups:\n"
                "    +3s 20 wakes 25 alarms, last -1h2m:\n"),
        DEVICE_POLICY: ("Current Device Policy Manager state:\n  User 0:\n"
                        "    Enabled Device Admins (User 0, provisioningState: 0):\n"
                        "      com.clean.pro.boost/.AdminReceiver:\n"
                        "        uid=10301\n        testOnlyAdmin=false\n"
                        "    mPasswordOwner=-1\n"),
        ROLE_HOME: "com.sec.android.app.launcher\n",
        ROLE_BROWSER: "com.android.chrome\n",
        ROLE_SMS: "com.google.android.apps.messaging\n",
        A11Y_SERVICES: "null\n",
        NOTIF_LISTENERS: "com.whatsapp/com.whatsapp.NotificationListener\n",
    }
    return FakeAdb(responses, serial=SERIAL, host={"devices -l": devices_output})


@pytest.fixture
def synthetic_adb() -> FakeAdb:
    return make_synthetic_adb()
