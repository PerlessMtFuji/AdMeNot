from datetime import datetime

from demalware.engine.adb.devices import DeviceEntry, list_devices, parse_devices
from demalware.engine.adb.fake import FakeAdb
from demalware.engine.device.info import (
    GETPROP,
    LOCAL_NOW,
    UPTIME,
    parse_getprop,
    read_device_info,
)

DEVICES = """* daemon not running; starting now at tcp:5037
* daemon started successfully
List of devices attached
R58T00TEST             device usb:1-1 product:a14xx model:SM_A145R device:a14 transport_id:3
9A1B2C3D               unauthorized usb:1-2 transport_id:4
emulator-5554          offline transport_id:5

"""


def test_parse_devices():
    assert parse_devices(DEVICES) == [
        DeviceEntry("R58T00TEST", "device", "SM_A145R"),
        DeviceEntry("9A1B2C3D", "unauthorized", None),
        DeviceEntry("emulator-5554", "offline", None),
    ]


def test_list_devices_uses_host_command():
    fake = FakeAdb(host={"devices -l": DEVICES})
    assert len(list_devices(fake)) == 3
    assert fake.calls == ["host:devices -l"]


def test_parse_getprop_handles_empty_and_brackets():
    props = parse_getprop("[ro.a]: [x]\n[ro.empty]: []\n[ro.b]: [v [1]]\ngarbage\n")
    assert props == {"ro.a": "x", "ro.empty": "", "ro.b": "v [1]"}


def _device(extra_props: str = "") -> FakeAdb:
    props = (
        "[ro.product.brand]: [Redmi]\n[ro.product.manufacturer]: [Xiaomi]\n"
        "[ro.product.model]: [23129RAA4G]\n[ro.product.device]: [sapphire]\n"
        "[ro.build.version.release]: [13]\n[ro.build.version.sdk]: [33]\n"
        "[ro.build.version.security_patch]: [2026-05-01]\n" + extra_props
    )
    return FakeAdb(
        {GETPROP: props, UPTIME: "7200.50 14000.00\n", LOCAL_NOW: "2026-09-26 14:00:00\n"},
        serial="XIAOMI1",
    )


def test_read_device_info_uses_vendor_marketname_fallback():
    info = read_device_info(_device("[ro.product.marketname]: []\n"
                                    "[ro.product.vendor.marketname]: [Redmi Note 13]\n"))
    assert info.market_name == "Redmi Note 13"
    assert (info.serial, info.brand, info.model, info.sdk) == ("XIAOMI1", "Redmi", "23129RAA4G", 33)
    assert info.uptime_s == 7200.5
    assert info.local_now == datetime(2026, 9, 26, 14, 0, 0)
    assert info.security_patch == "2026-05-01"


def test_read_device_info_without_marketname():
    assert read_device_info(_device()).market_name is None


def test_read_device_info_uses_huawei_marketing_name():
    info = read_device_info(_device("[ro.config.marketing_name]: [HUAWEI P30 lite]\n"))
    assert info.market_name == "HUAWEI P30 lite"
