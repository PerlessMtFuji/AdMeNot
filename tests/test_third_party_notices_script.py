import hashlib
import importlib.util
import json
import sys
from importlib import metadata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "third_party_notices.py"


def _module():
    spec = importlib.util.spec_from_file_location("third_party_notices", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["third_party_notices"] = module
    spec.loader.exec_module(module)
    return module


def _dist(site, name, version, headers, license_text=None):
    info = site / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}", *headers]
    (info / "METADATA").write_text("\n".join(lines) + "\n", "utf-8")
    record = [f"{info.name}/METADATA,,"]
    if license_text is not None:
        (info / "licenses").mkdir()
        (info / "licenses" / "LICENSE").write_text(license_text, "utf-8")
        record.append(f"{info.name}/licenses/LICENSE,,")
    (info / "RECORD").write_text("\n".join(record) + "\n", "utf-8")
    return metadata.PathDistribution(info)


@pytest.fixture
def site(tmp_path):
    dists = {
        "admenot": _dist(tmp_path, "admenot", "0.9.0", ["Requires-Dist: alpha",
                                                        'Requires-Dist: pytest; extra == "dev"']),
        "alpha": _dist(tmp_path, "alpha", "1.0", ["License-Expression: MIT",
                                                  "Requires-Dist: beta>=2",
                                                  'Requires-Dist: macos-only; sys_platform == "darwin"'],
                       license_text="MIT License\nalpha authors"),
        "beta": _dist(tmp_path, "beta", "2.1", ["Classifier: License :: OSI Approved :: BSD License"]),
        "nolicense": _dist(tmp_path, "nolicense", "0.1", []),
    }

    def find(name):
        try:
            return dists[name.lower()]
        except KeyError:
            raise metadata.PackageNotFoundError(name) from None

    return find


def test_closure_follows_requirements_and_skips_extras_and_missing(site):
    m = _module()
    names = [d.metadata["Name"] for d in m.python_closure(("admenot",), dist=site)]
    assert names == ["alpha", "beta"]  # bez admenot, pytest (extra) i macos-only (brak)


def test_license_sources(site):
    m = _module()
    assert m.license_of(site("alpha")) == "MIT"
    assert m.license_of(site("beta")) == "BSD License"
    assert m.license_of(site("nolicense")) is None


def test_render_includes_texts_and_flags_missing_licenses(site):
    m = _module()
    components = m.python_components([site("alpha"), site("nolicense")])
    text = m.render(components)
    assert "alpha 1.0" in text and "Licencja / License: MIT" in text and "alpha authors" in text
    assert "nolicense 0.1" in text and "nieznana / unknown" in text
    assert m.missing_licenses(components) == ["nolicense"]


def test_ui_components_cover_dependencies_and_bundled_dev_packages(tmp_path):
    m = _module()
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "package.json").write_text(json.dumps({"dependencies": {"@lucide/svelte": "^1"}}), "utf-8")
    for name in ("@lucide/svelte", *m.UI_BUNDLED):
        root = ui / "node_modules" / name
        root.mkdir(parents=True)
        (root / "package.json").write_text(json.dumps({"version": "1.2.3", "license": "ISC"}), "utf-8")
        (root / "LICENSE").write_text(f"{name} license text", "utf-8")
    components = m.ui_components(ui)
    assert [c.name for c in components] == sorted({"@lucide/svelte", *m.UI_BUNDLED})
    assert all(c.license == "ISC" and c.texts == (f"{c.name} license text",) for c in components)


def test_license_override_fills_in_missing_metadata(tmp_path):
    m = _module()
    clr = _dist(tmp_path, "clr_loader", "0.3.1", [], license_text="MIT License\nclr authors")
    assert m.license_of(clr) == "MIT"  # metadane bez licencji, tekst MIT jest w dist-info
    assert m.missing_licenses(m.python_components([clr])) == []


def test_webview2_sdk_component_carries_microsoft_bsd_text(tmp_path):
    m = _module()
    component = m._webview2_sdk(tmp_path / "brak.dll")  # brak pliku → wersja nieznana
    assert component.name == "Microsoft Edge WebView2 SDK (via pywebview)"
    assert component.version == "?"
    assert component.license == "BSD-3-Clause (Microsoft WebView2 SDK)"
    assert "Microsoft Corporation" in component.texts[0]


def test_google_device_list_is_listed_with_source_and_hash_version(tmp_path):
    m = _module()
    csv = tmp_path / "supported_devices.csv"
    csv.write_bytes(b"Retail Branding,Marketing Name,Device,Model\r\nOPPO,A16,OP4F7FL1,CPH2271\r\n")
    component = m._gplay(csv)
    assert component.name == "Google Play supported devices (supported_devices.csv)"
    assert component.version == hashlib.sha256(csv.read_bytes()).hexdigest()[:12]
    assert component.license
    assert m.missing_licenses([component]) == []
    assert m.GPLAY_URL in component.texts[0]
    assert m.GPLAY_URL in m.render([component])


def test_google_device_list_points_at_the_repo_copy():
    m = _module()
    assert m.GPLAY_CSV == ROOT / "data" / "supported_devices.csv"
    assert m.GPLAY_CSV.is_file()
