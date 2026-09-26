import json
from pathlib import Path

import pytest
from dexutil import make_apk, make_dex

from demalware.engine.apk.analyze import (
    ApkReport,
    analyze_apk,
    apply_apk_report,
    clean_label,
    report_from_json,
    report_to_json,
)
from demalware.engine.apk.manifest import ManifestInfo
from demalware.engine.apk.sdks import load_default_ad_sdks, parse_ad_sdks
from demalware.engine.facts import AppFacts

AD_CLASSES = [
    "com.applovin.sdk.AppLovinSdk", "com.mbridge.msdk.out.MBridgeSDKFactory",
    "com.bytedance.sdk.openadsdk.TTAdSdk", "com.facebook.ads.AdView",
    "com.google.android.gms.ads.MobileAds", "com.vungle.ads.VungleAds",
]


def _manifest(label="Super Cleaner"):
    def read(path: Path) -> ManifestInfo:
        return ManifestInfo("com.clean.x", 42, label, ("ab" * 32,))
    return read


def test_detect_counts_networks_not_prefixes():
    sdks = parse_ad_sdks("- {id: mintegral, name: M, prefixes: [com.mbridge.msdk, com.mintegral]}\n"
                         "- {id: applovin, name: A, prefixes: [com.applovin]}\n")
    found = sdks.detect(["com.mbridge.msdk.A", "com.mintegral.B", "com.applovinx.Fake", "com.app.Main"])
    assert found == {"mintegral"}  # "com.applovinx" nie pasuje do "com.applovin"


def test_parse_ad_sdks_rejects_duplicates_and_empty_prefixes():
    with pytest.raises(ValueError):
        parse_ad_sdks("- {id: a, name: A, prefixes: [x.y]}\n- {id: a, name: B, prefixes: [z.w]}\n")
    with pytest.raises(ValueError):
        parse_ad_sdks("- {id: a, name: A, prefixes: []}\n")


def test_default_ad_sdks_load():
    assert len(load_default_ad_sdks().sdks) >= 20


@pytest.mark.parametrize(("raw", "expected"), [
    ("Super Cleaner", ("Super Cleaner", False)),
    ("\xa0 IntelliClean", ("IntelliClean", True)),
    ("\u200b\u200bPDF Reader", ("PDF Reader", True)),
    ("Evil\u202eexe.gpj", ("Evilexe.gpj", False)),  # sterowanie kierunkiem tekstu usuwane
    ("Weather  Live ", ("Weather Live", False)),
    ("\xa0\u200b", (None, True)),                   # etykieta z samych niewidocznych znaków
    (None, (None, False)),
])
def test_clean_label(raw, expected):
    assert clean_label(raw) == expected


def test_analyze_apk_reports_sdks_labels_and_dynamic_code(tmp_path):
    base = make_apk(tmp_path / "base.apk", {
        "classes.dex": make_dex(["com.clean.x.Main", "a.b", "a.c"] + AD_CLASSES[:3],
                                extra_types=["dalvik.system.DexClassLoader"]),
        "classes2.dex": make_dex(AD_CLASSES[3:]),
    })
    split = make_apk(tmp_path / "split_config.arm64_v8a.apk", {})
    report = analyze_apk("com.clean.x", [split, base], read_manifest=_manifest("\xa0Super Cleaner"),
                         sdks=load_default_ad_sdks())
    assert report.error is None
    assert (report.package, report.version_code) == ("com.clean.x", 42)
    assert (report.label, report.label_padded) == ("Super Cleaner", True)
    assert report.ad_sdks == ["admob", "applovin", "meta", "mintegral", "pangle", "vungle"]
    assert report.dynamic_code is True
    assert report.class_count == 9
    assert report.obfuscation_ratio == pytest.approx(2 / 9, abs=0.001)
    assert report.cert_sha256 == ["ab" * 32]
    assert len(report.sha256) == 64  # skrót base.apk


def test_analyze_apk_survives_manifest_failure_and_broken_dex(tmp_path):
    base = make_apk(tmp_path / "base.apk", {
        "classes.dex": make_dex(AD_CLASSES[:2]),
        "classes2.dex": b"garbage",
    })

    def broken_manifest(path):
        raise ValueError("bad AXML")

    report = analyze_apk("com.clean.x", [base], read_manifest=broken_manifest,
                         sdks=load_default_ad_sdks())
    assert report.ad_sdks == ["applovin", "mintegral"]
    assert report.label is None
    assert "manifest" in report.error and "classes2.dex" in report.error


def test_analyze_apk_without_files():
    report = analyze_apk("com.clean.x", [], read_manifest=_manifest(), sdks=load_default_ad_sdks())
    assert report.error == "no APK files"
    assert report.class_count == 0


def test_report_json_roundtrip():
    report = ApkReport("com.x", 3, "f" * 64, "X", False, ["aa"], ["admob"], True, 10, 0.5, None)
    data = json.loads(json.dumps(report_to_json(report)))
    assert data["version"] == 1
    assert report_from_json(data) == report


def test_report_from_json_rejects_unknown_version():
    with pytest.raises(ValueError):
        report_from_json({"version": 99, "package": "com.x"})


def test_apply_apk_report_sets_facts():
    f = AppFacts("com.clean.x")
    apply_apk_report(f, ApkReport("com.clean.x", 42, "f" * 64, "Cleaner", True, ["aa"],
                                  ["admob", "applovin"], True, 100, 0.3, None))
    assert (f.label, f.label_padded, f.ad_sdks, f.dynamic_code) == (
        "Cleaner", True, {"admob", "applovin"}, True)
    assert (f.ad_sdk_count, f.ad_sdk_list, f.cert_sha256, f.apk_error) == (
        2, "admob, applovin", ("aa",), None)


def test_apply_failed_report_keeps_facts_unknown():
    f = AppFacts("com.clean.x")
    apply_apk_report(f, ApkReport("com.clean.x", error="pull: remote object does not exist"))
    assert f.apk_error.startswith("pull")
    assert (f.ad_sdks, f.ad_sdk_count, f.dynamic_code, f.label_padded) == (None, None, None, None)