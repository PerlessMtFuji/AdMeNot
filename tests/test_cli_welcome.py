import pytest
from conftest import SERIAL
from fakephone import make_cli_phone

from admenot.cli.main import main
from admenot.engine import welcome
from admenot.engine.settings import load_settings


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ADMENOT_ACCEPT_RISK")


@pytest.mark.parametrize("argv", [["scan"], ["fix", "--recommended", "--yes"],
                                  ["undo", "--order", "Z-1"], ["capture", "--out", "x"]])
def test_phone_commands_stop_before_acceptance(argv, capsys):
    assert main(argv, host=make_cli_phone()) == 2
    err = capsys.readouterr().err
    assert welcome.RISK_LINES["pl"][0] in err and "--accept-risk" in err
    assert load_settings().welcome_version is None


def test_flag_accepts_and_continues(capsys):
    assert main(["scan", "--accept-risk", "--serial", SERIAL], host=make_cli_phone()) == 0
    assert load_settings().welcome_version == welcome.WELCOME_VERSION
    assert main(["scan", "--serial", SERIAL], host=make_cli_phone()) == 0  # już zaakceptowane


def test_other_commands_do_not_ask():
    assert main(["devices"], host=make_cli_phone()) == 0


def test_english_warning(capsys):
    main(["--lang", "en", "scan"], host=make_cli_phone())
    assert welcome.RISK_LINES["en"][0] in capsys.readouterr().err
