import sqlite3

import pytest
from conftest import make_synthetic_adb
from httpstub import Stub, serve

from admenot.app import main as app_main
from admenot.cli import main as cli_main
from admenot.cli import selfcheck_cli
from admenot.cli.main import main
from admenot.net import client

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


def test_scan_diff_ignores_uptime_only():
    ref = "OPPO A16 · Android 12 · uptime 77.8 h\n  10  Reklamy  com.a\n"
    same = "OPPO A16 · Android 12 · uptime 80.1 h\n  10  Reklamy  com.a\n"
    other = "OPPO A16 · Android 12 · uptime 80.1 h\n  12  Reklamy  com.a\n"
    assert selfcheck_cli.scan_diff(ref, same) == []
    assert selfcheck_cli.scan_diff(ref, other) == ["-  10  Reklamy  com.a", "+  12  Reklamy  com.a"]


def test_device_check_compares_the_scan_with_the_reference(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    real_scan = cli_main._scan

    def scan_without_apk(adb, serial, lang, deep=frozenset(), apk=False):
        return real_scan(adb, serial, lang, deep)  # syntetyczny telefon nie ma plików APK

    monkeypatch.setattr(cli_main, "_scan", scan_without_apk)
    assert main(["scan", "--all"], host=make_synthetic_adb()) == 0
    reference = capsys.readouterr().out
    assert "uptime 77.8 h" in reference
    ref = tmp_path / "ref.txt"
    ref.write_text(reference.replace("uptime 77.8 h", "uptime 1.0 h"), "utf-8")

    args = ["selfcheck", "--device", "--reference", str(ref)]
    assert main(args, host=make_synthetic_adb()) == 0
    assert "taki sam jak referencyjny" in capsys.readouterr().out

    ref.write_text(reference.replace("com.clean.pro.boost", "com.inna.apka"), "utf-8")
    assert main(args, host=make_synthetic_adb()) == 1
    out = capsys.readouterr().out
    assert "różni się od referencyjnego" in out and "+" in out and "com.clean.pro.boost" in out


@pytest.fixture
def health(monkeypatch):
    stub = Stub(body=b'{"ok": true, "db": true}')
    stub.routes["/updates/v1/manifest.json"] = (404, b'{"error": "not_found"}')
    stop = serve(stub)
    monkeypatch.setenv(client.ENV_URL, stub.url)
    yield stub
    stop()


def test_offline_selfcheck_never_calls_the_server(installed, monkeypatch, capsys):
    def boom(path):
        raise AssertionError(f"selfcheck bez --online połączył się z {path}")

    monkeypatch.setattr(client, "get_json", boom)
    monkeypatch.setattr(client, "get_bytes", boom)
    assert main(["selfcheck"]) == 0
    out = capsys.readouterr().out
    assert "serwer" not in out and "aktualizacje" not in out


def test_online_selfcheck_reports_server_ok(installed, health, capsys):
    assert main(["selfcheck", "--online"]) == 0
    out = capsys.readouterr().out
    assert "OK      serwer" in out
    assert "OK      aktualizacje — brak manifestu" in out
    assert health.requests[0][1] == "/api/v1/health"


def test_online_selfcheck_reports_http_error(installed, health, capsys):
    health.status = 503
    health.body = b'{"ok": false, "db": false}'
    assert main(["selfcheck", "--online", "--lang", "en"]) == 1
    assert "MISSING server — http 503" in capsys.readouterr().out


def test_online_selfcheck_reports_offline(installed, monkeypatch, capsys):
    def offline(path):
        raise client.BackendError("offline")

    monkeypatch.setattr(client, "get_json", offline)
    monkeypatch.setattr(client, "get_bytes", offline)
    assert main(["selfcheck", "--online"]) == 1
    assert "BRAK    serwer — offline" in capsys.readouterr().out


def test_online_selfcheck_requires_ok_true(installed, health, capsys):
    health.body = b'{"status": "up"}'  # 200, ale to nie nasz health
    assert main(["selfcheck", "--online"]) == 1
    assert "BRAK    serwer — ok != true" in capsys.readouterr().out
