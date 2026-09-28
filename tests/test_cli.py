import json

from conftest import SERIAL, make_synthetic_adb

from demalware.cli.main import main
from demalware.engine.adb.fake import FakeAdb
from demalware.engine.adb.transport import AdbError
from demalware.engine.apk.analyze import ApkReport
from demalware.engine.foreground import ACTIVITIES, WINDOWS


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


SIX_SDKS = ["admob", "applovin", "meta", "mintegral", "pangle", "vungle"]


class _FakeDeviceProvider:
    def __init__(self, adb, *args, **kwargs):
        pass

    def reports_for(self, apps, progress=None):
        for i, f in enumerate(apps, start=1):
            if progress:
                progress(i, len(apps), f.package)
        return {"com.wlive.forecast": ApkReport(
            "com.wlive.forecast", 31, label="Weather\u202e Live", label_padded=True,
            ad_sdks=SIX_SDKS, class_count=500)}


def test_scan_apk_shows_labels_and_progress(capsys, monkeypatch):
    monkeypatch.setattr("demalware.cli.main.DeviceApkProvider", _FakeDeviceProvider)
    assert main(["scan", "--apk"], host=make_synthetic_adb()) == 0
    captured = capsys.readouterr()
    assert "Weather Live (com.wlive.forecast)" in captured.out  # oczyszczona etykieta
    assert "Podejrzana" in captured.out
    assert "Analiza APK 3/3" in captured.err


def test_scan_apk_lists_failures(capsys, monkeypatch):
    class Failing(_FakeDeviceProvider):
        def reports_for(self, apps, progress=None):
            return {"com.clean.pro.boost": ApkReport("com.clean.pro.boost", error="timeout")}

    monkeypatch.setattr("demalware.cli.main.DeviceApkProvider", Failing)
    assert main(["scan", "--apk"], host=make_synthetic_adb()) == 0
    assert "[apk] com.clean.pro.boost: timeout" in capsys.readouterr().out


def test_who_prints_foreground_and_overlays(capsys):
    adb = make_synthetic_adb()
    adb.responses[ACTIVITIES] = "  topResumedActivity=ActivityRecord{1 u0 com.clean.pro.boost/.Ad t1}\n"
    adb.responses[WINDOWS] = ("  Window #1 Window{a u0 com.clean.pro.boost}:\n"
                              "    mAttrs={ty=APPLICATION_OVERLAY}\n    isOnScreen=true\n")
    assert main(["who", "--delay", "0"], host=adb) == 0
    out = capsys.readouterr().out
    assert "com.clean.pro.boost" in out and "Na pierwszym planie" in out


def test_who_reports_unknown_when_the_phone_does_not_answer(capsys):
    assert main(["who", "--delay", "0", "--lang", "en"], host=make_synthetic_adb()) == 0
    captured = capsys.readouterr()
    assert "Could not tell which app is in the foreground." in captured.out
    assert "No windows over other apps." in captured.out
    assert "[who] activities:" in captured.err and "[who] windows:" in captured.err
