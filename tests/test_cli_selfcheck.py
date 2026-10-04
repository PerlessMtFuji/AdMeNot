import sqlite3

import pytest

from admenot.app import main as app_main
from admenot.cli import selfcheck_cli
from admenot.cli.main import main

TOOLS = ("adb.exe", "scrcpy.exe", "scrcpy-server", "SDL3.dll")


@pytest.fixture
def installed(monkeypatch, tmp_path):
    """Kompletna „instalacja” w tmp: narzędzia, phones.db, zdjęcia, UI."""
    assets = tmp_path / "assets"
    tools = assets / "tools" / "scrcpy"
    tools.mkdir(parents=True)
    for name in TOOLS:
        (tools / name).write_bytes(b"x")
    con = sqlite3.connect(assets / "phones.db")
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.commit()
    con.close()
    (assets / "phones").mkdir()
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html>", "utf-8")
    monkeypatch.setenv("ADMENOT_ASSETS", str(assets))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setattr(app_main, "WEB_DIR", web)
    return assets


def test_complete_install_passes(installed, capsys):
    assert selfcheck_cli.cmd_selfcheck("pl") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines and all(line.startswith("OK") for line in lines)
    assert any("androguard" in line for line in lines)


def test_missing_phones_db_is_reported(installed, capsys):
    (installed / "phones.db").unlink()
    assert selfcheck_cli.cmd_selfcheck("pl") == 1
    out = capsys.readouterr().out
    assert "BRAK    phones.db — " in out


def test_missing_adb_is_reported(installed, capsys):
    (installed / "tools" / "scrcpy" / "adb.exe").unlink()
    assert selfcheck_cli.cmd_selfcheck("en") == 1
    assert "MISSING adb.exe — " in capsys.readouterr().out


def test_missing_scrcpy_dll_is_reported(installed, capsys):
    (installed / "tools" / "scrcpy" / "SDL3.dll").unlink()
    assert selfcheck_cli.cmd_selfcheck("pl") == 1
    assert "BRAK    SDL3.dll — " in capsys.readouterr().out


def test_missing_androguard_resources_are_reported(installed, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(selfcheck_cli, "androguard_resources", lambda: tmp_path / "nowhere")
    assert selfcheck_cli.cmd_selfcheck("pl") == 1
    assert "BRAK    androguard public.xml — " in capsys.readouterr().out


def test_cli_command(installed, capsys):
    assert main(["selfcheck"]) == 0
    assert "OK" in capsys.readouterr().out
