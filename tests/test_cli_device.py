import json

import pytest
from conftest import make_synthetic_adb
from phonedb import make_phone_assets

from admenot.cli.main import main


@pytest.fixture(autouse=True)
def assets(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    path = make_phone_assets(tmp_path / "phones")
    monkeypatch.setenv("ADMENOT_ASSETS", str(path))
    return path


def test_device_shows_exact_match(capsys):
    assert main(["device"], host=make_synthetic_adb()) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "Samsung Galaxy A14 (2023)"
    assert "Dopasowanie: dokładne, kod modelu SM-A145R" in out
    assert "SN R58T00TEST" in out


def test_device_english(capsys):
    assert main(["device", "--lang", "en"], host=make_synthetic_adb()) == 0
    assert "Match: exact, model code SM-A145R" in capsys.readouterr().out


def test_device_json(capsys):
    assert main(["device", "--json"], host=make_synthetic_adb()) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["device"]["model"] == "SM-A145R"
    assert data["match"]["phone"]["slug"] == "samsung-galaxy-a14"
    assert data["match"]["confidence"] == "exact"


def test_search_needs_no_phone(capsys):
    host = make_synthetic_adb("List of devices attached\n\n")
    assert main(["device", "--search", "galaxy a14"], host=host) == 0
    assert capsys.readouterr().out.splitlines() == [
        "samsung-galaxy-a14\tSamsung Galaxy A14 (2023)",
        "samsung-galaxy-a14-5g\tSamsung Galaxy A14 5G (2023)",
    ]


def test_search_without_results(capsys):
    host = make_synthetic_adb("List of devices attached\n\n")
    assert main(["device", "--search", "nokia 3310"], host=host) == 0
    assert "Brak telefonów pasujących do „nokia 3310”" in capsys.readouterr().out


def test_set_and_clear_model(capsys):
    host = make_synthetic_adb()
    assert main(["device", "--set-model", "samsung-galaxy-a14-5g"], host=host) == 0
    out = capsys.readouterr().out
    assert "Zapisano model dla SM-A145R: samsung-galaxy-a14-5g" in out
    assert "Samsung Galaxy A14 5G (2023)" in out
    assert "Dopasowanie: wybrane ręcznie" in out
    assert main(["device", "--clear-model"], host=host) == 0
    out = capsys.readouterr().out
    assert "Usunięto ręczny wybór modelu dla SM-A145R." in out
    assert "Dopasowanie: dokładne" in out


def test_set_model_unknown_slug(capsys):
    assert main(["device", "--set-model", "nokia-3310"], host=make_synthetic_adb()) == 2
    assert "nokia-3310" in capsys.readouterr().err


def test_device_without_db(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "empty"))
    assert main(["device"], host=make_synthetic_adb()) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "samsung SM-A145R"
    assert "brak bazy telefonów" in out and "scripts/build_phone_db.py" in out


def test_device_no_phone(capsys):
    host = make_synthetic_adb("List of devices attached\n\n")
    assert main(["device"], host=host) == 2
    assert "Nie wykryto telefonu" in capsys.readouterr().err


def test_old_photo_flags_still_work(capsys):
    host = make_synthetic_adb()
    assert main(["device", "--set-photo", "samsung-galaxy-a14-5g"], host=host) == 0
    assert main(["device", "--clear-photo"], host=host) == 0
    assert "Usunięto ręczny wybór modelu dla SM-A145R." in capsys.readouterr().out
