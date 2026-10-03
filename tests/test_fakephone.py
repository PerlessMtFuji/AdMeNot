import pytest
from fakephone import GEARHEAD, LISTENERS, FakeApp, FakePhone

from admenot.engine.actions import commands as C
from admenot.engine.adb.transport import AdbError
from admenot.engine.collectors.packages import PM_DISABLED


def _phone(**kw):
    apps = [
        FakeApp("com.ad", home_activity=".Home", admin=True),
        FakeApp("com.android.launcher", system=True, home_activity=".Launcher", keeps_apk=True),
    ]
    return FakePhone(apps, **kw)


def test_disable_changes_disabled_list():
    phone = _phone()
    assert phone.shell(PM_DISABLED) == ""
    phone.shell(C.PM_DISABLE.format(package="com.android.launcher"))
    assert phone.shell(PM_DISABLED) == "package:com.android.launcher\n"


def test_unquoted_dollar_is_expanded_like_a_real_shell():
    phone = _phone()
    phone.shell(f"settings put secure {LISTENERS} {GEARHEAD}")
    assert "$" not in phone.secure[LISTENERS]
    phone.shell(C.SETTINGS_PUT.format(key=LISTENERS, value=GEARHEAD))
    assert phone.secure[LISTENERS] == GEARHEAD


def test_uninstall_of_device_admin_fails():
    phone = _phone()
    with pytest.raises(AdbError, match="DELETE_FAILED_DEVICE_POLICY_MANAGER"):
        phone.shell(C.PM_UNINSTALL.format(package="com.ad"))
    assert phone.apps["com.ad"].installed


def test_install_existing_needs_kept_apk():
    phone = _phone()
    phone.apps["com.ad"].admin = False
    for package in ("com.ad", "com.android.launcher"):
        phone.shell(C.PM_UNINSTALL.format(package=package))
    with pytest.raises(AdbError, match="doesn't exist"):
        phone.shell(C.PM_INSTALL_EXISTING.format(package="com.ad"))
    assert "installed for user" in phone.shell(C.PM_INSTALL_EXISTING.format(package="com.android.launcher"))


def test_lost_response_applies_command_then_disconnects():
    phone = _phone()
    command = C.PM_DISABLE.format(package="com.ad")
    phone.lose_response.add(command)
    with pytest.raises(AdbError) as exc:
        phone.shell(command)
    assert exc.value.kind == "no_device"
    assert phone.apps["com.ad"].enabled is False
    with pytest.raises(AdbError):
        phone.shell(PM_DISABLED)


def test_static_fallback_and_host_commands():
    phone = _phone(static={"getprop": "[ro.product.model]: [X]\n"}, host={"devices -l": "List\n"})
    assert phone.shell("getprop") == "[ro.product.model]: [X]\n"
    assert phone.run(["devices", "-l"]) == "List\n"
    with pytest.raises(AdbError, match="no response"):
        phone.shell("dumpsys unknown")


def test_fake_phone_takes_a_screenshot():
    from fakephone import make_cli_phone, png_bytes

    phone = make_cli_phone()
    assert phone.run_bytes(["exec-out", "screencap", "-p"]) == phone.screen
    assert phone.screen == png_bytes() and phone.screen.startswith(b"\x89PNG")
    phone.disconnected = True
    with pytest.raises(AdbError):
        phone.run_bytes(["exec-out", "screencap", "-p"])
