from __future__ import annotations

import sys
import time
from pathlib import Path

from admenot.engine.transfer.puller import RealPuller


def _fake_adb(tmp_path: Path, script_body: str) -> str:
    """„adb” = skrypt Pythona opakowany w plik wykonywalny (.cmd na Windows, sh gdzie indziej)."""
    py = tmp_path / "fake_adb.py"
    py.write_text(script_body, encoding="utf-8")
    if sys.platform == "win32":
        wrapper = tmp_path / "adb.cmd"
        wrapper.write_text(f'@"{sys.executable}" "{py}" %*\r\n', encoding="utf-8")
    else:
        wrapper = tmp_path / "adb"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
    return str(wrapper)


def test_real_puller_stops(tmp_path):
    adb = _fake_adb(tmp_path, "import time\ntime.sleep(30)\n")
    ticks = []

    def tick():
        ticks.append(1)

    started = time.monotonic()
    result = RealPuller(adb, "S1", None).pull(["/sdcard/a"], tmp_path, lambda: bool(ticks), tick)
    assert result.stopped is True
    assert time.monotonic() - started < 3
    assert len(ticks) >= 1


def test_real_puller_collects_lines(tmp_path):
    adb = _fake_adb(tmp_path, "import sys\nprint('one')\nprint('two', file=sys.stderr)\nsys.exit(1)\n")
    result = RealPuller(adb, "S1", None).pull(["/sdcard/a"], tmp_path, lambda: False, lambda: None)
    assert result.rc == 1
    assert result.stopped is False
    assert sorted(result.lines) == ["one", "two"]


def test_real_puller_passes_pull_args_and_logs(tmp_path):
    adb = _fake_adb(tmp_path, "import sys\nprint(' '.join(sys.argv[1:]))\n")

    class Log:
        def __init__(self):
            self.notes = []

        def note(self, what, status="info"):
            self.notes.append(what)

    log = Log()
    result = RealPuller(adb, "S1", log).pull(["/sdcard/a", "/sdcard/b"], tmp_path, lambda: False, lambda: None)  # type: ignore[arg-type]
    assert result.rc == 0
    assert result.lines == [f"-s S1 pull -a -Z /sdcard/a /sdcard/b {tmp_path}"]
    assert log.notes == [f"host:pull -a -Z /sdcard/a /sdcard/b {tmp_path}"]


def test_real_puller_stops_process_when_callback_raises(tmp_path):
    import pytest
    marker = tmp_path / "alive.txt"
    adb = _fake_adb(tmp_path, f"import time\nwhile True:\n    open(r'{marker}', 'a').write('x')\n    time.sleep(0.1)\n")

    def boom():
        raise RuntimeError("ui gone")

    with pytest.raises(RuntimeError):
        RealPuller(adb, "S1", None).pull(["/sdcard/a"], tmp_path, boom, lambda: None)
    time.sleep(0.3)
    size = marker.stat().st_size
    time.sleep(0.5)
    assert marker.stat().st_size == size  # nic już nie pisze


def test_real_puller_missing_adb(tmp_path):
    import pytest

    from admenot.engine.adb.transport import AdbError
    with pytest.raises(AdbError):
        RealPuller(str(tmp_path / "nope"), "S1", None).pull(["/sdcard/a"], tmp_path, lambda: False, lambda: None)
