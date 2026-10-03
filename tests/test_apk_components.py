import xml.etree.ElementTree as ET

from admenot.engine.apk.analyze import (
    ApkReport,
    apply_apk_report,
    report_from_json,
    report_to_json,
)
from admenot.engine.apk.components import A11yConfig, parse_components
from admenot.engine.facts import AppFacts

A = "http://schemas.android.com/apk/res/android"
MANIFEST = f"""<manifest xmlns:android="{A}" package="com.x">
  <application>
    <activity android:name="com.x.Main" android:exported="true">
      <intent-filter><action android:name="android.intent.action.MAIN"/></intent-filter>
    </activity>
    <receiver android:name=".Boot">
      <intent-filter><action android:name="android.intent.action.BOOT_COMPLETED"/></intent-filter>
    </receiver>
    <service android:name="com.x.A11y" android:permission="android.permission.BIND_ACCESSIBILITY_SERVICE">
      <intent-filter><action android:name="android.accessibilityservice.AccessibilityService"/></intent-filter>
      <meta-data android:name="android.accessibilityservice" android:resource="@xml/a11y"/>
    </service>
    <provider android:name="com.x.Files"/>
  </application>
</manifest>"""
A11Y = f"""<accessibility-service xmlns:android="{A}" android:canRetrieveWindowContent="true"
  android:canPerformGestures="true" android:accessibilityEventTypes="typeAllMask"/>"""


def _parse():
    return parse_components(ET.fromstring(MANIFEST), lambda ref: ET.fromstring(A11Y) if ref == "@xml/a11y" else None)


def test_components_with_exports_actions_and_relative_names():
    comps = {c.name: c for c in _parse()}
    assert comps["com.x.Main"].exported is True
    boot = comps["com.x.Boot"]  # nazwa względna rozwinięta pakietem
    assert boot.kind == "receiver" and boot.exported is True
    assert boot.actions == ("android.intent.action.BOOT_COMPLETED",)
    assert comps["com.x.Files"].exported is False


def test_accessibility_service_configuration_is_read():
    a11y = {c.name: c for c in _parse()}["com.x.A11y"]
    assert a11y.permission == "android.permission.BIND_ACCESSIBILITY_SERVICE"
    assert a11y.a11y == A11yConfig(retrieve_window=True, perform_gestures=True, event_types="typeAllMask")


def test_v1_report_loads_with_unknown_components():
    data = report_to_json(ApkReport("com.x", class_count=3))
    data["version"] = 1
    data.pop("components")
    report = report_from_json(data)
    assert report.components is None
    facts = AppFacts("com.x")
    apply_apk_report(facts, report)
    assert facts.apk_components is None  # „nie odczytano”, nie „brak komponentów”


def test_v2_report_round_trips_components():
    comps = _parse()
    report = ApkReport("com.x", class_count=3,
                       components=[c.to_json() for c in comps])
    again = report_from_json(report_to_json(report))
    facts = AppFacts("com.x")
    apply_apk_report(facts, again)
    assert facts.apk_components == comps
