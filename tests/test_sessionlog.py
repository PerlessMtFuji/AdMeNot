from datetime import datetime

import pytest

from demalware.engine.adb.fake import FakeAdb
from demalware.engine.adb.sessionlog import SessionLogAdb, session_log_path
from demalware.engine.adb.transport import AdbError


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


def test_session_log_path_is_per_day(tmp_path):
    assert session_log_path(tmp_path, datetime(2026, 9, 26, 23, 59)) == tmp_path / "2026-09-26.log"
