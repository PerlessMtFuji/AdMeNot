from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from admenot.engine.adb.transport import AdbTransport

GETPROP = "getprop"
UPTIME = "cat /proc/uptime"
LOCAL_NOW = 'date "+%Y-%m-%d %H:%M:%S"'
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

_PROP = re.compile(r"^\[([^\]]+)\]: \[(.*)\]$")


@dataclass(frozen=True)
class DeviceInfo:
    serial: str
    brand: str
    manufacturer: str
    model: str
    device: str
    market_name: str | None
    android_release: str
    sdk: int
    security_patch: str | None
    uptime_s: float
    local_now: datetime


def parse_getprop(text: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for line in text.splitlines():
        m = _PROP.match(line.strip())
        if m:
            props[m.group(1)] = m.group(2)
    return props


def read_device_info(adb: AdbTransport) -> DeviceInfo:
    props = parse_getprop(adb.shell(GETPROP))
    uptime_s = float(adb.shell(UPTIME).split()[0])
    local_now = datetime.strptime(adb.shell(LOCAL_NOW).strip(), TIME_FORMAT)

    def prop(key: str) -> str | None:
        value = props.get(key, "").strip()
        return value or None

    return DeviceInfo(
        serial=adb.serial or prop("ro.serialno") or "unknown",
        brand=prop("ro.product.brand") or "",
        manufacturer=prop("ro.product.manufacturer") or "",
        model=prop("ro.product.model") or "",
        device=prop("ro.product.device") or "",
        market_name=(prop("ro.product.marketname") or prop("ro.product.vendor.marketname")
                     or prop("ro.config.marketing_name") or prop("ro.oppo.market.name")
                     or prop("ro.vendor.oplus.market.name")),
        android_release=prop("ro.build.version.release") or "",
        sdk=int(prop("ro.build.version.sdk") or 0),
        security_patch=prop("ro.build.version.security_patch"),
        uptime_s=uptime_s,
        local_now=local_now,
    )
