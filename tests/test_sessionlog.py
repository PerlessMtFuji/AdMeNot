from datetime import datetime

import pytest

from admenot.engine.adb.fake import FakeAdb
from admenot.engine.adb.sessionlog import OUTPUT_LIMIT, SessionLogAdb, session_log_path
from admenot.engine.adb.transport import AdbError


def test_session_log_records_commands_without_output(tmp_path):
    path = tmp_path / "logs" / "2026-09-26.log"
    adb = SessionLogAdb(FakeAdb({"echo secret": "tajne dane\n"}, serial="S1"), path,
                        now=lambda: datetime(2026, 9, 26, 12, 0))
    assert adb.shell("echo secret") == "tajne dane\n"
    with pytest.raises(AdbError):
        adb.shell("missing")
    lines = path.read_text("utf-8").splitlines()
    assert [line.split("\t")[2] for line in lines] == ["ok", "error:command_failed"]
    assert lines[0].startswith("2026-09-26T12:00:00\tS1\t") and lines[0].endswith("\techo secret")
    assert "tajne" not in path.read_text("utf-8")


def test_session_log_wraps_host_commands_and_serial(tmp_path):
    inner = FakeAdb(host={"devices -l": "List of devices attached\n"})
    adb = SessionLogAdb(inner, tmp_path / "x.log").with_serial("S2")
    assert adb.serial == "S2"
    adb.run(["devices", "-l"])
    assert (tmp_path / "x.log").read_text("utf-8").rstrip().endswith("\thost:devices -l")


def test_session_log_file_has_no_client_file_names_but_console_does(tmp_path):
    """Plik logu (90 dni) bez nazw plików klienta; konsola na żywo dostaje polecenie bez zmian."""
    seen = []
    cmd = "stat -c '%s|%Y|%n' '/sdcard/DCIM/Wakacje w Zakopanem.jpg' /sdcard/Download/faktura.pdf"
    adb = SessionLogAdb(FakeAdb({cmd: ""}, serial="S1"), tmp_path / "x.log", on_command=seen.append)
    adb.shell(cmd)
    adb.tagged("pull").note(r"open C:\Users\Jan\AppData\Local\AdMeNot\transfers\S1\x\files\DCIM\a.jpg")
    text = (tmp_path / "x.log").read_text("utf-8")
    for leak in ("Zakopanem", "faktura", "DCIM", "Download"):
        assert leak not in text, text
    assert "stat -c '%s|%Y|%n' '/sdcard/<path>' /sdcard/<path>" in text
    assert seen[0]["command"] == cmd


def test_session_log_path_is_per_day(tmp_path):
    assert session_log_path(tmp_path, datetime(2026, 9, 26, 23, 59)) == tmp_path / "2026-09-26.log"


def test_on_command_gets_output_and_errors(tmp_path):
    seen = []
    long = "x" * (OUTPUT_LIMIT + 10)
    adb = SessionLogAdb(FakeAdb({"echo hi": "hi\n", "big": long}, serial="S1"), tmp_path / "l.log",
                        now=lambda: datetime(2026, 9, 26, 12, 0), on_command=seen.append)
    adb.shell("echo hi")
    adb.shell("big")
    with pytest.raises(AdbError):
        adb.shell("missing")
    assert seen[0] == {"time": "2026-09-26T12:00:00", "serial": "S1", "command": "echo hi",
                       "status": "ok", "duration": seen[0]["duration"], "output": "hi\n",
                       "tag": None}
    assert len(seen[1]["output"]) == OUTPUT_LIMIT
    assert seen[2]["status"] == "error:command_failed" and "missing" in seen[2]["output"]
    assert "hi" not in (tmp_path / "l.log").read_text("utf-8").replace("echo hi", "")


def test_tagged_console_commands_are_marked_in_the_log(tmp_path):
    seen = []
    adb = SessionLogAdb(FakeAdb({"id": "uid=2000\n"}, serial="S1"), tmp_path / "l.log",
                        on_command=seen.append)
    console = adb.tagged("console").with_serial("S1")
    console.shell("id")
    assert (tmp_path / "l.log").read_text("utf-8").rstrip().endswith("\tconsole:id")
    assert seen[0]["tag"] == "console" and seen[0]["command"] == "id"


def test_run_bytes_logs_size_not_content(tmp_path):
    seen = []
    inner = FakeAdb(serial="S1", binary={"exec-out screencap -p": b"\x89PNG" + b"x" * 96})
    adb = SessionLogAdb(inner, tmp_path / "l.log", now=lambda: datetime(2026, 9, 26, 12, 0),
                        on_command=seen.append).tagged("shot")
    assert adb.run_bytes(["exec-out", "screencap", "-p"]).startswith(b"\x89PNG")
    assert seen[0]["command"] == "host:exec-out screencap -p"
    assert seen[0]["output"] == "<100 B>" and seen[0]["tag"] == "shot"
    assert (tmp_path / "l.log").read_text("utf-8").rstrip().endswith(
        "\tshot:host:exec-out screencap -p")


def test_note_records_a_line_without_adb(tmp_path):
    seen = []
    adb = SessionLogAdb(FakeAdb(serial="S1"), tmp_path / "l.log",
                        now=lambda: datetime(2026, 9, 26, 12, 0),
                        on_command=seen.append).tagged("scrcpy")
    adb.note("INFO: Texture: 576x1280")
    assert seen == [{"time": "2026-09-26T12:00:00", "serial": "S1",
                     "command": "INFO: Texture: 576x1280", "status": "info",
                     "duration": seen[0]["duration"], "output": "", "tag": "scrcpy"}]
    assert "\tinfo\t" in (tmp_path / "l.log").read_text("utf-8")


def test_notification_dump_with_content_reaches_the_console_as_size_only(tmp_path):
    seen = []
    dump = "android.title=String (Bank)\nandroid.text=String (kod 123456)\n"
    cmd = "dumpsys notification --noredact"
    adb = SessionLogAdb(FakeAdb({cmd: dump}, serial="S1"), tmp_path / "l.log", on_command=seen.append)
    assert adb.tagged("recheck").shell(cmd) == dump  # program dostaje pełny zrzut
    adb.tagged("console").shell(cmd)  # wpisany ręcznie w konsoli: serwisant widzi wynik
    assert seen[0]["output"] == f"<{len(dump.encode())} B>"
    assert seen[1]["output"] == dump


def test_account_dump_hidden_in_console(tmp_path):
    """`dumpsys account` (plan telefonii) wypisuje adresy e-mail kont klienta: konsola ich nie dostaje."""
    seen = []
    dump = "Accounts: 1\n  Account {name=jan.kowalski@gmail.com, type=com.google}\n"
    cmd = "dumpsys account"
    adb = SessionLogAdb(FakeAdb({cmd: dump, f"-T {cmd}": dump}, serial="S1"), tmp_path / "l.log",
                        on_command=seen.append)
    assert adb.shell(cmd) == dump  # program dostaje pełny zrzut
    adb.run(["shell", "-T", cmd])
    adb.tagged("console").shell(cmd)  # wpisany ręcznie w konsoli: serwisant widzi wynik
    assert [e["output"] for e in seen[:2]] == ["", ""]
    assert seen[2]["output"] == dump
    assert "kowalski" not in (tmp_path / "l.log").read_text("utf-8")
