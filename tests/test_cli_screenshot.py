from pathlib import Path

import pytest
from conftest import SERIAL
from fakephone import make_cli_phone

from demalware.cli.main import main
from demalware.engine import paths
from demalware.engine.foreground import ACTIVITIES, WINDOWS
from demalware.engine.journal.db import Journal


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("DEMALWARE_ASSETS", str(tmp_path / "no-assets"))
    return tmp_path


def _phone():
    phone = make_cli_phone()
    phone.static[ACTIVITIES] = "  topResumedActivity=ActivityRecord{1 u0 com.clean.pro.boost/.Ad t1}\n"
    phone.static[WINDOWS] = ""
    return phone


def test_needs_order_or_out(capsys):
    assert main(["screenshot"], host=_phone()) == 2
    assert "--order" in capsys.readouterr().err


def test_out_saves_only_a_file(env, capsys):
    phone = _phone()
    target = env / "shot.png"
    assert main(["screenshot", "--out", str(target)], host=phone) == 0
    assert target.read_bytes() == phone.screen
    assert f"Zapisano {target}" in capsys.readouterr().out
    assert not paths.journal_path().exists() or Journal(paths.journal_path()).orphan_screenshots() == []


def test_order_saves_to_the_journal(env, capsys):
    phone = _phone()
    with Journal(paths.journal_path()) as journal:
        order = journal.create_order(SERIAL, "SM-A145R")
    target = env / "copy.png"
    code = main(["screenshot", "--order", order.number, "--out", str(target)], host=phone)
    assert code == 0
    out = capsys.readouterr().out
    assert f"w zleceniu {order.number}" in out and "com.clean.pro.boost" in out
    with Journal(paths.journal_path()) as journal:
        (shot,) = journal.screenshots(order.id)
    assert target.read_bytes() == paths.screenshot_files(shot.id)[0].read_bytes()


def test_unknown_order_and_wrong_phone(capsys):
    assert main(["screenshot", "--order", "ZS/2026/0101/01"], host=_phone()) == 2
    assert "ZS/2026/0101/01" in capsys.readouterr().err
    with Journal(paths.journal_path()) as journal:
        order = journal.create_order("OTHER", None)
    assert main(["screenshot", "--order", order.number], host=_phone()) == 2
    assert "OTHER" in capsys.readouterr().err


def test_english(capsys, env):
    target = env / "shot.png"
    assert main(["screenshot", "--out", str(target), "--lang", "en"], host=_phone()) == 0
    assert f"Saved {target}" in capsys.readouterr().out


def test_out_to_nonexistent_directory(capsys):
    phone = _phone()
    target = Path(r"C:\this\dir\does\not\exist\shot.png")
    code = main(["screenshot", "--out", str(target)], host=phone)
    assert code == 6
    err = capsys.readouterr().err
    assert "Nie można zapisać" in err and str(target) in err
    assert "Traceback" not in err


def test_order_alone_saves_to_journal(capsys):
    phone = _phone()
    with Journal(paths.journal_path()) as journal:
        order = journal.create_order(SERIAL, "SM-A145R")
    code = main(["screenshot", "--order", order.number], host=phone)
    assert code == 0
    out = capsys.readouterr().out
    assert f"w zleceniu {order.number}" in out
    with Journal(paths.journal_path()) as journal:
        (shot,) = journal.screenshots(order.id)
    # Verify screenshot is in journal
    assert paths.screenshot_files(shot.id)[0].exists()
