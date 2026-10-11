from datetime import datetime

from admenot.engine.adb.fake import FakeAdb
from admenot.engine.device.identity import device_key, identity_of, same_device
from admenot.engine.device.info import ANDROID_ID, DeviceInfo, read_android_id


def device(**kw):
    base = {"serial": "0123456789ABCDEF", "brand": "x", "manufacturer": "x", "model": "A1",
            "device": "a1", "market_name": None, "android_release": "13", "sdk": 33,
            "security_patch": None, "uptime_s": 1.0, "local_now": datetime(2026, 10, 11),
            "imei": None, "android_id": None}
    return DeviceInfo(**{**base, **kw})


def test_same_android_id_is_the_same_phone():
    stored = identity_of(device(android_id="aaaa1111bbbb2222"))
    assert same_device(stored, device(android_id="aaaa1111bbbb2222")) is True


def test_same_serial_different_android_id_is_another_phone():
    stored = identity_of(device(android_id="aaaa1111bbbb2222"))
    assert same_device(stored, device(android_id="cccc3333dddd4444")) is False


def test_reset_phone_with_the_same_imei_is_another_device():
    """Po przywróceniu ustawień fabrycznych android_id jest nowy: stan sprzed zlecenia już nie istnieje."""
    stored = identity_of(device(android_id="aaaa1111bbbb2222", imei="356938035643809"))
    assert same_device(stored, device(android_id="cccc3333dddd4444", imei="356938035643809")) is False


def test_imei_decides_when_android_id_is_unknown():
    stored = identity_of(device(imei="356938035643809"))
    assert same_device(stored, device(imei="356938035643809", android_id="aaaa1111bbbb2222")) is True
    assert same_device(stored, device(imei="490154203237518")) is False


def test_order_without_identity_is_unknown_not_different():
    assert same_device(None, device(android_id="aaaa1111bbbb2222")) is None
    assert same_device({}, device()) is None


def test_only_a_different_model_proves_another_phone_without_ids():
    assert same_device(identity_of(device(model="A1")), device(model="A1")) is None
    assert same_device(identity_of(device(model="A1")), device(model="B2")) is False


def test_device_key_separates_phones_with_one_serial():
    assert device_key(device()) == "0123456789ABCDEF"
    assert device_key(device(android_id="aaaa1111bbbb2222")) == "0123456789ABCDEF#aaaa1111bbbb2222"


def test_read_android_id():
    assert read_android_id(FakeAdb({ANDROID_ID: "a1b2c3d4e5f60718\n"})) == "a1b2c3d4e5f60718"
    assert read_android_id(FakeAdb({ANDROID_ID: "null\n"})) is None
    assert read_android_id(FakeAdb({})) is None
