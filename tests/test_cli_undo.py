import pytest
from conftest import SERIAL
from fakephone import LISTENERS, POST, make_cli_phone

from demalware.cli.main import main
from demalware.engine.adb.fake import FakeAdb
from demalware.engine.journal.db import Journal
from demalware.engine.paths import journal_path

DISABLE = "pm disable-user --user 0 com.wlive.forecast"


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def _fix(phone, *apps):
    args = ["fix", "--yes"]
    for app in apps:
        args += ["--app", app]
    main(args, host=phone)
    with Journal(journal_path()) as j:
        return j.orders_for(SERIAL)[0]


def test_undo_order_restores_the_phone(capsys):
    phone = make_cli_phone()
    order = _fix(phone, "com.wlive.forecast=disable")
    capsys.readouterr()
    assert main(["undo", "--order", order.number], host=phone) == 0
    app = phone.apps["com.wlive.forecast"]
    assert app.enabled and app.granted == {POST}
    out = capsys.readouterr().out
    assert "↺ com.wlive.forecast: wyłączenie aplikacji" in out and "cofnięte" in out


def test_undo_single_app(capsys):
    phone = make_cli_phone()
    order = _fix(phone, "com.wlive.forecast=disable", "com.whatsapp=silence")
    assert main(["undo", "--order", order.number, "--app", "com.wlive.forecast"], host=phone) == 0
    assert phone.apps["com.wlive.forecast"].enabled
    assert phone.secure[LISTENERS] == ""  # WhatsApp nadal wyciszony
    assert "częściowo cofnięte" in capsys.readouterr().out


def test_undo_unknown_order(capsys):
    assert main(["undo", "--order", "ZS/1999/0101/01"], host=make_cli_phone()) == 2
    assert "Nie znaleziono zlecenia" in capsys.readouterr().err


def test_undo_needs_the_same_phone(capsys):
    phone = make_cli_phone()
    order = _fix(phone, "com.wlive.forecast=disable")
    phone.host["devices -l"] = "List of devices attached\nOTHER1 device usb:1-2\n"
    assert main(["undo", "--order", order.number], host=phone) == 2
    assert SERIAL in capsys.readouterr().err
    assert phone.apps["com.wlive.forecast"].enabled is False


def test_resume_after_disconnect(capsys):
    phone = make_cli_phone()
    phone.lose_response.add(DISABLE)
    order = _fix(phone, "com.wlive.forecast=disable")
    phone.lose_response.clear()
    phone.disconnected = False
    capsys.readouterr()
    assert main(["history"], host=phone) == 0
    assert "Przerwane zlecenie" in capsys.readouterr().out
    assert main(["resume", "--order", order.number, "--yes"], host=phone) == 0
    assert phone.calls.count(DISABLE) == 1
    with Journal(journal_path()) as j:
        assert j.order(order.id).status == "done"


def test_cache_size_and_clean_keep_backups(capsys, tmp_path):
    cache = tmp_path / "DeMalware" / "apk-cache" / "com.x" / "1"
    cache.mkdir(parents=True)
    (cache / "base.apk").write_bytes(b"x" * 2_000_000)
    backup = tmp_path / "DeMalware" / "backups" / "S" / "com.x" / "1"
    backup.mkdir(parents=True)
    (backup / "base.apk").write_bytes(b"x")
    assert main(["cache"], host=FakeAdb()) == 0
    assert "2 MB" in capsys.readouterr().out
    assert main(["cache", "--clean"], host=FakeAdb()) == 0
    assert not (tmp_path / "DeMalware" / "apk-cache").exists()
    assert (backup / "base.apk").exists()


def test_fix_writes_session_log(tmp_path):
    _fix(make_cli_phone(), "com.wlive.forecast=disable")
    (log,) = (tmp_path / "DeMalware" / "logs").glob("*.log")
    lines = log.read_text("utf-8").splitlines()
    assert any(line.split("\t")[2] == "ok" and line.endswith("\t" + DISABLE) for line in lines)
