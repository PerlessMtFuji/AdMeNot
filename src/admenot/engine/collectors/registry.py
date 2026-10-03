from __future__ import annotations

from datetime import datetime

from admenot.engine.collectors.base import Collector
from admenot.engine.collectors.behavior import (
    AlarmCollector,
    AppOpsCollector,
    NotificationsCollector,
    UsageStatsCollector,
)
from admenot.engine.collectors.components import ComponentsCollector
from admenot.engine.collectors.system import (
    DevicePolicyCollector,
    RolesCollector,
    SecureSettingsCollector,
)


def default_collectors(now: datetime, uptime_s: float = 0.0) -> list[Collector]:
    return [
        ComponentsCollector(),
        AppOpsCollector(),
        NotificationsCollector(),
        UsageStatsCollector(now),
        AlarmCollector(uptime_s),
        DevicePolicyCollector(),
        RolesCollector(),
        SecureSettingsCollector(),
    ]
