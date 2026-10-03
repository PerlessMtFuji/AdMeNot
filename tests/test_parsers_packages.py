from datetime import datetime

import pytest

from admenot.engine.parsers.common import (
    component_packages,
    parse_duration,
    parse_package_list,
    split_components,
)
from admenot.engine.parsers.packages import parse_dumpsys_packages, parse_pm_list


def test_parse_duration():
    assert parse_duration("+4m12s123ms") == pytest.approx(252.123)
    assert parse_duration("-1d2h") == 86400 + 7200
    assert parse_duration("2m") == 120
    assert parse_duration("0ms") == 0
    assert parse_duration("never") is None


def test_component_packages():
    text = (
        "priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\n"
        "  com.whatsapp/.Main\n"
        "  com.foo.bar/com.foo.bar.Receiver$Inner\n"
        "    com.admin.app/.AdminReceiver:\n"
        "random text / with slash\n"
    )
    assert component_packages(text) == {"com.whatsapp", "com.foo.bar", "com.admin.app"}


def test_split_components():
    assert split_components("com.a/.S:com.b/com.b.X\n") == {"com.a", "com.b"}
    assert split_components("null\n") == set()
    assert split_components("") == set()


def test_parse_package_list():
    assert parse_package_list("package:com.a\npackage:com.b\n\n") == {"com.a", "com.b"}


def test_parse_pm_list_handles_base64_paths_and_missing_fields():
    text = (
        "package:/data/app/~~Rg8wIz5ZcWJ2cUNYmbzZ2w==/com.clean.pro-a1B2==/base.apk="
        "com.clean.pro  installer=com.android.chrome uid:10301\n"
        "package:/system/priv-app/Launcher/Launcher.apk=com.sec.android.app.launcher"
        "  installer=null uid:10090\n"
        "package:/system/framework/framework-res.apk=android uid:1000\n"
    )
    entries = parse_pm_list(text)
    clean = entries["com.clean.pro"]
    assert clean.apk_path == "/data/app/~~Rg8wIz5ZcWJ2cUNYmbzZ2w==/com.clean.pro-a1B2==/base.apk"
    assert (clean.installer, clean.uid) == ("com.android.chrome", 10301)
    assert entries["com.sec.android.app.launcher"].installer is None
    assert entries["android"].uid == 1000


DUMPSYS = """Database versions:
  Internal:
    sdkVersion=34 databaseVersion=3
Packages:
  Package [com.clean.pro] (b1a2c3):
    userId=10301
    versionCode=7 minSdk=24 targetSdk=33
    firstInstallTime=2026-09-20 10:00:00
    lastUpdateTime=2026-09-21 11:00:00
    installerPackageName=com.android.chrome
    requested permissions:
      android.permission.INTERNET
      android.permission.SYSTEM_ALERT_WINDOW
      android.permission.READ_PHONE_STATE: restricted=true
    install permissions:
      android.permission.INTERNET: granted=true
      android.permission.WAKE_LOCK: granted=false
    User 0: ceDataInode=1 installed=true hidden=false enabled=0
      runtime permissions:
        android.permission.POST_NOTIFICATIONS: granted=true, flags=[ USER_SET ]
        android.permission.CAMERA: granted=false, flags=[ ]
  Package [com.other] (c1):
    versionCode=1 minSdk=21 targetSdk=34
    installerPackageName=null
    User 0: ceDataInode=2 installed=true enabled=0
      firstInstallTime=2025-01-10 09:00:00

Hidden system packages:
  Package [com.clean.pro] (f1):
    versionCode=999
"""


def test_parse_dumpsys_packages():
    dumps = parse_dumpsys_packages(DUMPSYS)
    assert set(dumps) == {"com.clean.pro", "com.other"}
    clean = dumps["com.clean.pro"]
    assert clean.version_code == 7
    assert clean.first_install == datetime(2026, 9, 20, 10, 0, 0)
    assert clean.last_update == datetime(2026, 9, 21, 11, 0, 0)
    assert clean.installer == "com.android.chrome"
    # Uprawnienie z sekcji install/runtime też jest żądane, nawet nieprzyznane.
    assert clean.requested == {
        "android.permission.INTERNET",
        "android.permission.SYSTEM_ALERT_WINDOW",
        "android.permission.READ_PHONE_STATE",
        "android.permission.WAKE_LOCK",
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.CAMERA",
    }
    assert clean.granted == {"android.permission.INTERNET", "android.permission.POST_NOTIFICATIONS"}
    other = dumps["com.other"]
    assert other.installer is None
    assert other.first_install == datetime(2025, 1, 10, 9, 0, 0)


# Android 12 (OPPO CPH2271): `dumpsys package packages` nie wypisuje sekcji „requested permissions:”.
DUMPSYS_NO_REQUESTED = """Packages:
  Package [com.intelli.clean] (4fd82fa):
    versionCode=25 minSdk=23 targetSdk=36
    installerPackageName=com.android.vending
    declared permissions:
      com.intelli.clean.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION: prot=signature, INSTALLED
    install permissions:
      android.permission.RECEIVE_BOOT_COMPLETED: granted=true
      android.permission.REQUEST_DELETE_PACKAGES: granted=true
    User 0: ceDataInode=25959 installed=true hidden=false enabled=0
      runtime permissions:
        android.permission.READ_EXTERNAL_STORAGE: granted=false, flags=[ USER_SENSITIVE_WHEN_GRANTED ]
"""


def test_parse_dumpsys_packages_without_requested_section():
    d = parse_dumpsys_packages(DUMPSYS_NO_REQUESTED)["com.intelli.clean"]
    assert d.requested == {
        "android.permission.RECEIVE_BOOT_COMPLETED",
        "android.permission.REQUEST_DELETE_PACKAGES",
        "android.permission.READ_EXTERNAL_STORAGE",
    }
    assert d.granted == {"android.permission.RECEIVE_BOOT_COMPLETED",
                         "android.permission.REQUEST_DELETE_PACKAGES"}


# Android 13 MIUI (Redmi 22101316G): biblioteki współdzielone wypisują „<lib> overlay paths:”
# bez wcięcia w środku bloku pakietu — to nie jest nowa sekcja najwyższego poziomu.
DUMPSYS_MIUI_OVERLAYS = """Packages:
  Package [com.android.providers.telephony] (c754182):
    versionCode=33 minSdk=33 targetSdk=33
      firstInstallTime=2009-01-01 01:00:00
      overlay paths:
        /data/resource-cache/com.android.systemui-neutral-dR4e.frro
      
com.miui.system overlay paths:
          /data/resource-cache/com.android.systemui-neutral-dR4e.frro
      
micloud-sdk overlay paths:
          /data/resource-cache/com.android.systemui-accent-wQgI.frro
  Package [com.clean.pro] (bba4d21):
    versionCode=7 minSdk=24 targetSdk=33
    install permissions:
      android.permission.INTERNET: granted=true

Hidden system packages:
  Package [com.clean.pro] (f1):
    versionCode=999
"""


def test_parse_dumpsys_packages_miui_unindented_overlay_lines():
    dumps = parse_dumpsys_packages(DUMPSYS_MIUI_OVERLAYS)
    assert set(dumps) == {"com.android.providers.telephony", "com.clean.pro"}
    assert dumps["com.clean.pro"].version_code == 7
    assert dumps["com.clean.pro"].granted == {"android.permission.INTERNET"}
