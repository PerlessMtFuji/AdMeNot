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


def test_readme_is_english_with_a_link_to_polish():
    readme = (ROOT / "README.md").read_text("utf-8")
    assert "**English** | [Polski](README.pl.md)" in readme.splitlines()[2]
    assert "## License" in readme
    assert "PolyForm Shield 1.0.0" in readme
    assert "source-available, not open source" in readme


def test_polish_readme_links_back_to_english():
    readme = (ROOT / "README.pl.md").read_text("utf-8")
    assert "[English](README.md) | **Polski**" in readme.splitlines()[2]
    assert "## Licencja" in readme
    assert "PolyForm Shield 1.0.0" in readme
    assert "kod jawny (source-available)" in readme
