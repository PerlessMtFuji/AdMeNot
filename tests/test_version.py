import importlib.metadata
import re

import pytest

import admenot
from admenot.app.main import window_title
from admenot.cli.main import main
from admenot.engine.versions import engine_versions


def test_one_version_everywhere(capsys):
    assert re.fullmatch(r"\d+\.\d+\.\d+", admenot.__version__)
    assert importlib.metadata.version("admenot") == admenot.__version__
    # paczka PyInstallera nie ma dist-info — silnik nie może polegać na metadanych
    assert engine_versions()["engine"] == admenot.__version__
    with pytest.raises(SystemExit) as stop:
        main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == f"AdMeNot {admenot.__version__}"


def test_window_title_says_beta_before_1_0():
    assert window_title("0.9.0") == "AdMeNot 0.9.0 beta"
    assert window_title("1.0.0") == "AdMeNot 1.0.0"
