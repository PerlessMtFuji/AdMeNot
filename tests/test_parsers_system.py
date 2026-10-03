from admenot.engine.parsers.common import parse_components
from admenot.engine.parsers.system import (
    parse_device_admins,
    parse_resolved_component,
    parse_resolved_home,
    parse_role_holders,
    parse_users,
)

POLICY_SECTION = """Current Device Policy Manager state:
  Immutable state:
    mHasFeature=true
  User 0:
    Enabled Device Admins (User 0, provisioningState: 0):
      com.clean.pro/.AdminReceiver:
        uid=10301
        testOnlyAdmin=false
      com.google.android.gms/com.google.android.gms.mdm.receivers.MdmDeviceAdminReceiver:
        uid=10150
    mPasswordOwner=-1
    restrictionsProvider=ComponentInfo{com.unrelated/.Provider}
"""

POLICY_COMPONENTINFO = """Current Device Policy Manager state:
  Active admin: ComponentInfo{com.evil.ads/com.evil.ads.Admin}
"""


def test_parse_device_admins_from_section():
    assert parse_device_admins(POLICY_SECTION) == {"com.clean.pro", "com.google.android.gms"}


def test_parse_device_admins_from_componentinfo_lines_mentioning_admin():
    assert parse_device_admins(POLICY_COMPONENTINFO) == {"com.evil.ads"}


def test_parse_role_holders_ignores_errors():
    assert parse_role_holders("com.sec.android.app.launcher\n") == {"com.sec.android.app.launcher"}
    assert parse_role_holders("Unknown command: get-role-holders\n") == set()
    assert parse_role_holders("\n") == set()


def test_parse_resolved_home_skips_resolver():
    assert parse_resolved_home("priority=0\n  com.nova/.Launcher\n") == {"com.nova"}
    assert parse_resolved_home(
        "priority=0\n  android/com.android.internal.app.ResolverActivity\n"
    ) == set()


RESOLVED_HOME_OPPO = (
    "priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true\n"
    "com.intelli.clean/com.star.james.ui.activity.launcher.LauncherActivity\n"
)


def test_parse_resolved_component():
    assert parse_resolved_component(RESOLVED_HOME_OPPO) == (
        "com.intelli.clean/com.star.james.ui.activity.launcher.LauncherActivity")
    no_default = "priority=0\nandroid/com.android.internal.app.ResolverActivity\n"
    assert parse_resolved_component(no_default) is None


def test_parse_components_keeps_class_names_with_dollar():
    text = ("priority=0 preferredOrder=0\n  com.android.launcher/.Launcher\n"
            "  com.x/com.x.Outer$Inner\n")
    assert parse_components(text) == ["com.android.launcher/.Launcher", "com.x/com.x.Outer$Inner"]


def test_parse_users():
    text = "Users:\n\tUserInfo{0:Właściciel:c13} running\n\tUserInfo{10:Praca:1030} running\n"
    assert parse_users(text) == [0, 10]
    assert parse_users("garbage") == []


def test_device_admins_of_other_users_are_ignored():
    text = ("Current Device Policy Manager state:\n"
            "  Enabled Device Admins (User 0, provisioningState: 0):\n"
            "    com.a/.Admin:\n      uid=10100\n"
            "  Enabled Device Admins (User 10, provisioningState: 3):\n"
            "    com.work/.Admin:\n      uid=1010100\n")
    assert parse_device_admins(text) == {"com.a"}
