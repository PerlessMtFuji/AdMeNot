import pytest
from fakephone import make_cli_phone
from httpstub import Stub, serve
from updatehelpers import signed

from admenot import __version__
from admenot.cli import selfcheck_cli
from admenot.cli.main import main
from admenot.net import client, update


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))


@pytest.fixture
def retired(signing_key):
    update.store(update.verify(signed(signing_key, min_supported="9.0.0",
                                      min_reason={"pl": "Błąd cofania", "en": "Undo bug"})))


@pytest.mark.parametrize("argv", [["fix", "--recommended", "--yes"],
                                  ["resume", "--order", "2026/0001", "--yes"]])
def test_retired_version_refuses_changes(retired, argv, capsys):
    assert main(argv, host=make_cli_phone()) == 3
    err = capsys.readouterr().err
    assert "wycofana" in err and "Błąd cofania" in err and update.download_page("pl") in err


def test_undo_is_never_blocked(retired, capsys):
    assert main(["undo", "--order", "2026/0001"], host=make_cli_phone()) != 3


@pytest.fixture
def server(monkeypatch):
    stub = Stub()
    stop = serve(stub)
    monkeypatch.setenv(client.ENV_URL, stub.url)
    yield stub
    stop()


def test_update_row_states(signing_key, server):
    server.body = signed(signing_key)
    assert selfcheck_cli.update_check("pl") == selfcheck_cli.Check("aktualizacje", True,
                                                                   "dostępna 9.9.9")
    server.body = signed(signing_key, latest=__version__, min_supported="0.0.1",
                         url=update.URL_PREFIX + f"v{__version__}/AdMeNot-{__version__}-setup.exe")
    assert selfcheck_cli.update_check("en").detail == f"up to date ({__version__})"
    server.body = signed(signing_key, min_supported="9.0.0")
    row = selfcheck_cli.update_check("pl")
    assert (row.warn, row.detail) == (True, "wycofana (min 9.0.0)")
    server.status, server.body = 404, b'{"error": "not_found"}'
    assert selfcheck_cli.update_check("pl") == selfcheck_cli.Check("aktualizacje", True,
                                                                   "brak manifestu")
    server.status, server.body = 200, b'{"payload": "{}", "sig": "eA=="}'
    assert selfcheck_cli.update_check("pl").ok is False


def test_retired_row_fails_the_selfcheck(signing_key, server, capsys):
    server.routes["/api/v1/health"] = (200, b'{"ok": true, "db": true}')
    server.body = signed(signing_key, min_supported="9.0.0")
    assert selfcheck_cli.cmd_online("pl") == 1
    assert "UWAGA   aktualizacje — wycofana (min 9.0.0)" in capsys.readouterr().out
