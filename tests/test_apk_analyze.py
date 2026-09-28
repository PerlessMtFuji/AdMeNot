import json
import zipfile
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
from demalware.engine.apk.manifest import ICON_MAX_BYTES, ManifestInfo, _read_icon, icon_uri
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
    ("Evil\x1b[2JApp\x07", ("Evil[2JApp", False)),  # sterujące ANSI/C0 nie trafiają do konsoli
    ("Bad\x9bApp", ("BadApp", False)),                # C1 (CSI)
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

def test_apply_apk_report_cleans_stored_label():
    f = AppFacts("com.clean.x")
    apply_apk_report(f, ApkReport("com.clean.x", label="\x1b[31mRed", class_count=1))
    assert f.label == "[31mRed"


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8


def test_icon_uri_accepts_only_bitmaps_by_magic_bytes():
    assert icon_uri(PNG).startswith("data:image/png;base64,")
    assert icon_uri(WEBP).startswith("data:image/webp;base64,")
    assert icon_uri(b"\xff\xd8\xff\xe0jfif").startswith("data:image/jpeg;base64,")
    assert icon_uri(b"<svg onload='x'/>") is None
    assert icon_uri(b"\x03\x00\x08\x00axml") is None  # skompilowany XML (ikona adaptacyjna)
    assert icon_uri(PNG + b"\x00" * ICON_MAX_BYTES) is None


class _FakeApk:
    def __init__(self, icons, files):
        self.icons, self.files = icons, files

    def get_app_icon(self, max_dpi=65536):
        return self.icons.get(max_dpi)

    def get_file(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]


def test_read_icon_prefers_bitmap_and_skips_adaptive_xml():
    apk = _FakeApk({480: "res/mipmap-xxhdpi/ic.png", 65536: "res/mipmap-anydpi-v26/ic.xml"},
                   {"res/mipmap-xxhdpi/ic.png": PNG, "res/mipmap-anydpi-v26/ic.xml": b"\x03\x00"})
    assert _read_icon(apk) == icon_uri(PNG)
    only_xml = _FakeApk({65536: "res/mipmap-anydpi-v26/ic.xml"},
                        {"res/mipmap-anydpi-v26/ic.xml": b"\x03\x00"})
    assert _read_icon(only_xml) is None
    missing = _FakeApk({480: "res/gone.png", 640: "res/x.webp"}, {"res/x.webp": WEBP})
    assert _read_icon(missing) == icon_uri(WEBP)


def test_analyze_apk_carries_icon_to_facts(tmp_path):
    base = make_apk(tmp_path / "base.apk", {"classes.dex": make_dex(["com.clean.x.Main"])})

    def read(path: Path) -> ManifestInfo:
        return ManifestInfo("com.clean.x", 42, "X", (), icon_uri(PNG))

    report = analyze_apk("com.clean.x", [base], read_manifest=read, sdks=load_default_ad_sdks())
    assert report.icon == icon_uri(PNG)
    restored = report_from_json(json.loads(json.dumps(report_to_json(report))))
    f = AppFacts("com.clean.x")
    apply_apk_report(f, restored)
    assert f.icon == icon_uri(PNG)


@pytest.mark.parametrize("icon", [
    "data:image/svg+xml;base64,PHN2Zy8+",
    "javascript:alert(1)",
    "data:image/png;base64,PHN2Zy8+",  # nagłówek mówi PNG, treść to SVG
    "data:image/png;base64,!!!",
    42,
])
def test_apply_apk_report_drops_foreign_icons(icon):
    f = AppFacts("com.clean.x")
    apply_apk_report(f, ApkReport("com.clean.x", label="X", class_count=1, icon=icon))
    assert f.icon is None


def test_report_lists_hash_of_every_file(tmp_path):
    base, split = tmp_path / "base.apk", tmp_path / "split_config.apk"
    for p in (base, split):
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("x.txt", p.name)
    report = analyze_apk("com.x", [base, split],
                         read_manifest=lambda p: ManifestInfo("com.x", 5, "X", ("ab" * 32,)))
    assert set(report.files) == {"base.apk", "split_config.apk"}
    assert report.files["base.apk"] == report.sha256


def test_stale_report_is_not_applied_and_marks_gap():
    facts = AppFacts("com.x", version_code=8)
    apply_apk_report(facts, ApkReport("com.x", version_code=7, class_count=10, ad_sdks=["admob"],
                                      cert_sha256=["ab" * 32]))
    assert facts.ad_sdks is None and facts.cert_sha256 is None
    assert "stale" in facts.apk_error and "apk" in facts.gaps


def test_partial_report_applies_what_it_has_but_marks_gap():
    facts = AppFacts("com.x", version_code=7)
    apply_apk_report(facts, ApkReport("com.x", version_code=7, class_count=10, ad_sdks=["admob"],
                                      error="base.apk!classes2.dex: truncated uleb128",
                                      files={"base.apk": "cd" * 32}))
    assert facts.ad_sdks == {"admob"} and "apk" in facts.gaps
    assert facts.apk_sha256 == ("cd" * 32,)


def test_complete_report_leaves_no_gap():
    facts = AppFacts("com.x", version_code=7)
    apply_apk_report(facts, ApkReport("com.x", version_code=7, class_count=10))
    assert facts.gaps == set() and facts.apk_error is None


def test_old_json_without_files_still_loads():
    data = report_to_json(ApkReport("com.x"))
    del data["files"]
    assert report_from_json(data).files == {}


LONG_CODE = (1 << 32) | 7  # versionCodeMajor=1, versionCode=7 — dumpsys pokazuje długi kod


def test_long_version_code_from_dumpsys_matches_lower_manifest_code():
    """Przegląd końcowy M1: raport sprzed odczytu versionCodeMajor nie jest »stale«."""
    facts = AppFacts("com.x", version_code=LONG_CODE)
    apply_apk_report(facts, ApkReport("com.x", version_code=7, class_count=10, ad_sdks=["admob"]))
    assert facts.apk_error is None and facts.gaps == set()
    assert facts.ad_sdks == {"admob"}


def test_long_version_code_still_detects_a_different_install():
    facts = AppFacts("com.x", version_code=LONG_CODE)
    apply_apk_report(facts, ApkReport("com.x", version_code=(2 << 32) | 7, class_count=10))
    assert "stale" in facts.apk_error and "apk" in facts.gaps


def test_read_manifest_combines_version_code_major(monkeypatch, tmp_path):
    import androguard.core.apk as androguard_apk

    from demalware.engine.apk.manifest import read_manifest

    class FakeApk:
        def __init__(self, path):
            pass

        def get_app_name(self):
            return "X"

        def get_app_icon(self, max_dpi=None):
            return None

        def get_androidversion_code(self):
            return "7"

        def get_attribute_value(self, tag, attribute, format_value=False):
            return {"versionCodeMajor": "1"}.get(attribute) if tag == "manifest" else None

        def get_certificates(self):
            return []

        def get_package(self):
            return "com.x"

    monkeypatch.setattr(androguard_apk, "APK", FakeApk)
    assert read_manifest(tmp_path / "base.apk").version_code == LONG_CODE
