import json

from conftest import SERIAL, make_synthetic_adb
from demalware.cli.main import main
from demalware.engine.adb.fake import FakeAdb
from demalware.engine.adb.transport import AdbError


def test_devices_lists_entries(capsys):
    assert main(["devices"], host=make_synthetic_adb()) == 0
    out = capsys.readouterr().out
    assert SERIAL in out and "device" in out


def test_scan_json(capsys):
    assert main(["scan", "--json", "--lang", "en"], host=make_synthetic_adb()) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["results"][0]["package"] == "com.clean.pro.boost"


def test_scan_text_hides_safe_apps_by_default(capsys):
    assert main(["scan"], host=make_synthetic_adb()) == 0
    out = capsys.readouterr().out
    assert "com.clean.pro.boost" in out and "Szkodliwa" in out
    assert "com.whatsapp" not in out


def test_scan_text_all_shows_safe_apps(capsys):
    assert main(["scan", "--all"], host=make_synthetic_adb()) == 0
    assert "com.whatsapp" in capsys.readouterr().out


def test_no_device(capsys):
    host = make_synthetic_adb("List of devices attached\n\n")
    assert main(["scan"], host=host) == 2
    assert "Nie wykryto telefonu" in capsys.readouterr().err


def test_unauthorized_device(capsys):
    host = make_synthetic_adb("List of devices attached\nABC123 unauthorized usb:1-1\n")
    assert main(["scan"], host=host) == 3
    assert "ABC123" in capsys.readouterr().err


def test_multiple_devices_require_serial(capsys):
    host = make_synthetic_adb(
        f"List of devices attached\n{SERIAL} device usb:1-1\nOTHER1 device usb:1-2\n")
    assert main(["scan"], host=host) == 2
    assert "--serial" in capsys.readouterr().err
    assert main(["scan", "--serial", SERIAL, "--json"], host=host) == 0


def test_unknown_serial(capsys):
    assert main(["scan", "--serial", "NOPE"], host=make_synthetic_adb()) == 2


def test_adb_missing(capsys):
    host = FakeAdb(host={"devices -l": AdbError("adb_missing", "adb executable not found")})
    assert main(["devices"], host=host) == 4
    assert "adb" in capsys.readouterr().err
