from demalware.engine.parsers.system import (
    parse_device_admins,
    parse_resolved_home,
    parse_role_holders,
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
