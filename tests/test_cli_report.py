import pytest

from demalware.cli.main import main
from demalware.engine.adb.fake import FakeAdb
from demalware.engine.settings import ServiceInfo, load_service


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("DEMALWARE_ASSETS", str(tmp_path / "no-assets"))
    return tmp_path


def no_phone() -> FakeAdb:
    return FakeAdb({}, host={})  # każde polecenie ADB kończy się błędem


def test_service_shows_hint_when_empty(capsys):
    assert main(["service"], host=no_phone()) == 0
    assert "demalware service --name" in capsys.readouterr().out


def test_service_sets_fields_and_logo(capsys, data_dir):
    logo = data_dir / "logo.png"
    logo.write_bytes(b"\x89PNG....")
    assert main(["service", "--name", "Serwis Ząb", "--phone", "600 000 000",
                 "--logo", str(logo)], host=no_phone()) == 0
    out = capsys.readouterr().out
    assert "Serwis: Serwis Ząb" in out and "Telefon: 600 000 000" in out and "Adres: —" in out
    assert load_service() == ServiceInfo("Serwis Ząb", None, "600 000 000", logo.resolve())

    assert main(["--lang", "en", "service", "--address", "Main St 1", "--phone", "",
                 "--clear-logo"], host=no_phone()) == 0
    assert "Address: Main St 1" in capsys.readouterr().out
    assert load_service() == ServiceInfo("Serwis Ząb", "Main St 1", None, None)


def test_service_rejects_bad_logo(capsys, data_dir):
    assert main(["service", "--logo", str(data_dir / "nie-ma.png")], host=no_phone()) == 2
    assert "Nie ma pliku" in capsys.readouterr().err
    assert load_service() == ServiceInfo()
