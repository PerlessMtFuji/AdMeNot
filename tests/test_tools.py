import pytest

from admenot.engine.tools import ToolPath, resolve_adb, resolve_scrcpy, tools_dir


@pytest.fixture
def assets(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "assets"))
    return tmp_path / "assets"


def _bundle(assets, *names):
    directory = assets / "tools" / "scrcpy"
    directory.mkdir(parents=True)
    for name in names:
        (directory / name).write_bytes(b"x")
    return directory


def test_settings_path_wins_over_bundled_and_path(assets, monkeypatch):
    _bundle(assets, "adb.exe")
    monkeypatch.setattr("shutil.which", lambda name: "C:\\sdk\\adb.exe")
    assert resolve_adb("  D:\\my\\adb.exe ") == ToolPath("D:\\my\\adb.exe", "settings")


def test_bundled_adb_wins_over_path(assets, monkeypatch):
    directory = _bundle(assets, "adb.exe")
    monkeypatch.setattr("shutil.which", lambda name: "C:\\sdk\\adb.exe")
    assert resolve_adb(None) == ToolPath(str(directory / "adb.exe"), "bundled")
    assert resolve_adb("   ") == ToolPath(str(directory / "adb.exe"), "bundled")


def test_path_adb_when_nothing_is_bundled(assets, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "C:\\sdk\\adb.exe" if name == "adb" else None)
    assert resolve_adb(None) == ToolPath("C:\\sdk\\adb.exe", "path")


def test_missing_adb(assets, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert resolve_adb(None) == ToolPath(None, "missing")


def test_scrcpy_needs_the_exe_and_the_server(assets):
    assert tools_dir() == assets / "tools" / "scrcpy"
    assert resolve_scrcpy() is None
    directory = _bundle(assets, "scrcpy.exe")
    assert resolve_scrcpy() is None
    (directory / "scrcpy-server").write_bytes(b"x")
    assert resolve_scrcpy() == directory / "scrcpy.exe"
