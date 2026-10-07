import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICE = ("Required Notice: Copyright 2026 Eryk Wlodarski "
          "(https://github.com/PerlessMtFuji/AdMeNot)")


def test_license_is_polyform_shield_with_the_required_notice():
    lines = (ROOT / "LICENSE").read_text("utf-8").splitlines()
    assert lines[0] == NOTICE
    assert lines[1] == ""
    assert lines[2] == "# PolyForm Shield License 1.0.0"
    assert "## Noncompete" in lines


def test_package_metadata_names_the_license():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert data["project"]["license"] == "LicenseRef-PolyForm-Shield-1.0.0"
    assert data["project"]["license-files"] == ["LICENSE"]
    assert data["build-system"]["requires"] == ["hatchling>=1.27"]


def test_readme_says_source_available_not_open_source():
    readme = (ROOT / "README.md").read_text("utf-8")
    assert "## Licencja / License" in readme
    assert "PolyForm Shield 1.0.0" in readme
    assert "source-available" in readme
