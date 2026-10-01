from datetime import datetime

import pytest
from conftest import SERIAL
from fakephone import LISTENERS, make_cli_phone

from demalware.cli.main import main
from demalware.engine.adb.fake import FakeAdb
from demalware.engine.journal.db import Journal
from demalware.engine.paths import journal_path

WRITES = ("pm disable", "pm uninstall", "appops set", "pm revoke", "settings put", "am force-stop")


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def _orders():
    with Journal(journal_path()) as j:
        return j.orders_for(SERIAL)


def test_fix_disables_app_and_history_shows_the_order(capsys):
    phone = make_cli_phone()
    assert main(["fix", "--app", "com.wlive.forecast=disable", "--yes"], host=phone) == 0
    out = capsys.readouterr().out
    assert "WYŁĄCZ" in out and "wyłączenie aplikacji" in out and "✓ com.wlive.forecast" in out
    assert phone.apps["com.wlive.forecast"].enabled is False
    (order,) = _orders()
    assert order.status == "done" and f"undo --order {order.number}" in out

    assert main(["history"], host=phone) == 0
    history = capsys.readouterr().out
    assert order.number in history and "wykonane" in history
    assert "com.wlive.forecast" in history and "odebranie zgody na powiadomienia" in history


def test_fix_in_english(capsys):
    assert main(["--lang", "en", "fix", "--app", "com.whatsapp=silence", "--yes"],
                host=make_cli_phone()) == 0
    out = capsys.readouterr().out
    assert "SILENCE" in out and "revoke notification access" in out


def test_fix_asks_before_changing_anything(capsys, monkeypatch):
    phone = make_cli_phone()
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert main(["fix", "--recommended"], host=phone) == 1
    out = capsys.readouterr().out
    assert "USUŃ" in out and "com.clean.pro.boost" in out and "kopia APK" in out
    assert "com.whatsapp" not in out and "Anulowano" in out
    assert not [c for c in phone.calls if c.startswith(WRITES)]
    assert _orders() == []


def test_fix_refuses_protected_launcher(capsys):
    phone = make_cli_phone()
    assert main(["fix", "--app", "com.sec.android.app.launcher=disable", "--yes"], host=phone) == 1
    assert "chroniona" in capsys.readouterr().out
    assert phone.apps["com.sec.android.app.launcher"].enabled


def test_fix_bad_app_format(capsys):
    assert main(["fix", "--app", "com.x", "--yes"], host=make_cli_phone()) == 2
    assert "Zły format --app" in capsys.readouterr().err


def test_fix_with_nothing_to_do(capsys):
    assert main(["fix"], host=make_cli_phone()) == 0
    assert "Nic do zrobienia" in capsys.readouterr().out


def test_fix_device_admin_waits_then_reports(capsys):
    phone = make_cli_phone()
    args = ["fix", "--app", "com.clean.pro.boost=remove", "--yes", "--admin-timeout", "0"]
    assert main(args, host=phone) == 5
    out = capsys.readouterr().out
    assert "Dezaktywuj" in out and "administratorem urządzenia" in out
    assert phone.opened == ["admin"] and phone.apps["com.clean.pro.boost"].installed


def test_fix_disconnect_prints_resume_hint(capsys):
    phone = make_cli_phone()
    phone.lose_response.add("pm disable-user --user 0 com.wlive.forecast")
    assert main(["fix", "--app", "com.wlive.forecast=disable", "--yes"], host=phone) == 3
    (order,) = _orders()
    assert f"resume --order {order.number}" in capsys.readouterr().err
    assert order.status == "running"


def test_history_by_serial_works_without_the_phone(capsys):
    phone = make_cli_phone()
    assert main(["fix", "--app", "com.whatsapp=silence", "--yes"], host=phone) == 0
    assert phone.secure[LISTENERS] == ""
    capsys.readouterr()
    offline = FakeAdb(host={"devices -l": "List of devices attached\n\n"})
    assert main(["history", "--serial", SERIAL], host=offline) == 0
    assert "com.whatsapp" in capsys.readouterr().out


def test_fix_treats_closed_stdin_as_no(capsys, monkeypatch):
    phone = make_cli_phone()

    def closed(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    assert main(["fix", "--app", "com.wlive.forecast=disable"], host=phone) == 1
    assert "Anulowano" in capsys.readouterr().out
    assert phone.apps["com.wlive.forecast"].enabled


def test_fix_disconnect_before_planning_is_reported_without_traceback(capsys, monkeypatch):
    from demalware.engine.actions.errors import ActionError

    def gone(adb, manufacturer=""):
        raise ActionError("disconnected", "device not found")

    monkeypatch.setattr("demalware.cli.actions_cli.read_phone_context", gone)
    assert main(["fix", "--app", "com.wlive.forecast=disable", "--yes"], host=make_cli_phone()) == 3
    assert "Podłącz" in capsys.readouterr().err


def test_fix_stores_scan_snapshot_and_verification(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DEMALWARE_ASSETS", str(tmp_path / "no-assets"))
    phone = make_cli_phone()
    assert main(["fix", "--app", "com.wlive.forecast=disable", "--yes"], host=phone) == 0
    (order,) = _orders()
    assert f"report --order {order.number}" in capsys.readouterr().out
    with Journal(journal_path()) as j:
        snap = j.scan(order.id)
        assert snap["device"]["model"] == "SM-A145R" and snap["phone"]["confidence"] == "none"
        assert "com.clean.pro.boost" in {a["package"] for a in snap["apps"]}
        assert j.verification(order.id) == {}


def test_fix_with_apk_stores_app_names_and_icons_for_the_report(monkeypatch, tmp_path):
    from demalware.engine.apk.analyze import ApkReport

    icon = "data:image/png;base64,iVBORw0KGgo="

    class Provider:
        def __init__(self, adb, policy=None, **kwargs):
            pass

        def reports_for(self, targets, progress=None, flagged=frozenset()):
            return {"com.wlive.forecast": ApkReport("com.wlive.forecast", label="Pogoda Live",
                                                    icon=icon, class_count=1)}

    monkeypatch.setenv("DEMALWARE_ASSETS", str(tmp_path / "no-assets"))
    monkeypatch.setattr("demalware.cli.main.DeviceApkProvider", Provider)
    assert main(["fix", "--apk", "--app", "com.wlive.forecast=disable", "--yes"],
                host=make_cli_phone()) == 0
    (order,) = _orders()
    with Journal(journal_path()) as j:
        app = next(a for a in j.scan(order.id)["apps"] if a["package"] == "com.wlive.forecast")
    assert (app["label"], app["icon"]) == ("Pogoda Live", icon)


def test_fix_clears_the_apk_cache_after_a_finished_repair(capsys, data_dir):
    from demalware.engine.settings import save_settings

    save_settings({"apk_cache_clear_after_repair": True})
    entry = data_dir / "DeMalware" / "apk-cache" / "com.x" / "1"
    entry.mkdir(parents=True)
    (entry / "base.apk").write_bytes(b"x" * 1_000_000)
    assert main(["fix", "--app", "com.wlive.forecast=disable", "--yes"], host=make_cli_phone()) == 0
    out = capsys.readouterr().out
    assert "Usunięto pamięć podręczną APK po naprawie (1 MB)" in out
    assert not (data_dir / "DeMalware" / "apk-cache" / "com.x").exists()


def test_fix_uses_the_incident_recording_like_scan(monkeypatch, tmp_path):
    from demalware.cli import actions_cli
    from demalware.engine.incident import Sample, Timeline, save_incident
    from demalware.engine.paths import incident_path

    monkeypatch.setenv("DEMALWARE_ASSETS", str(tmp_path / "no-assets"))
    phone = make_cli_phone()
    save_incident(incident_path(phone.serial),
                  Timeline([Sample(0.0, "com.game", ["com.wlive.forecast"], None, [])], [0.0]), datetime.now())
    seen = {}
    real = actions_cli.run_scan

    def spy(adb, **kw):
        seen.update(kw)
        return real(adb, **kw)

    monkeypatch.setattr(actions_cli, "run_scan", spy)
    assert main(["fix", "--app", "com.wlive.forecast=disable", "--yes"], host=phone) == 0
    assert seen["incidents"] == {"com.wlive.forecast": (1, "com.game")}
