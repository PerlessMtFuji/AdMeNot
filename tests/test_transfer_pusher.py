from __future__ import annotations

import json
import time
from pathlib import Path

from test_transfer_puller import _fake_adb

from admenot.engine.transfer.pusher import RealPusher


def test_real_pusher_stops(tmp_path):
    adb = _fake_adb(tmp_path, "import time\ntime.sleep(30)\n")
    ticks = []
    started = time.monotonic()
    result = RealPusher(adb, "S1", None).push([tmp_path / "a"], "/sdcard/DCIM/", lambda: bool(ticks),
                                              lambda: ticks.append(1))
    assert result.stopped is True
    assert time.monotonic() - started < 3
    assert len(ticks) >= 1


def test_real_pusher_collects_lines(tmp_path):
    adb = _fake_adb(tmp_path, "import sys\nprint('one')\nprint('two', file=sys.stderr)\nsys.exit(1)\n")
    result = RealPusher(adb, "S1", None).push([tmp_path / "a"], "/sdcard/DCIM/", lambda: False, lambda: None)
    assert result.rc == 1
    assert result.stopped is False
    assert sorted(result.lines) == ["one", "two"]


def test_push_args_quote_odd_names(tmp_path):
    out = tmp_path / "argv.json"
    adb = _fake_adb(tmp_path, f"import json, sys\njson.dump(sys.argv[1:], open(r'{out}', 'w', encoding='utf-8'))\n")
    src = tmp_path / "src"
    src.mkdir()
    files = []
    for name in ("it's.jpg", "-a.jpg", "$x zażółć.jpg"):
        (src / name).write_bytes(b"x")
        files.append(src / name)

    class Log:
        def __init__(self):
            self.notes = []

        def note(self, what, status="info"):
            self.notes.append(what)

    log = Log()
    result = RealPusher(adb, "S1", log).push(files, "/sdcard/DCIM/Ą B/", lambda: False, lambda: None)  # type: ignore[arg-type]
    assert result.rc == 0
    argv = json.loads(out.read_text(encoding="utf-8"))
    assert argv[:2] == ["-s", "S1"] and argv[2] == "push"
    locals_ = argv[3:-1]
    assert len(locals_) == 3
    for arg, f in zip(locals_, files, strict=True):
        assert Path(arg).is_absolute() and not arg.startswith("-")
        assert Path(arg) == f.resolve()
    assert argv[-1] == "/sdcard/DCIM/Ą B/"
    assert log.notes == ["host:push 3 files"]


def test_real_pusher_rejects_unsafe_target(tmp_path):
    import pytest

    from admenot.engine.transfer.guard import UnsafeCommand
    with pytest.raises(UnsafeCommand):
        RealPusher("adb", "S1", None).push([tmp_path / "a"], "/data/x/", lambda: False, lambda: None)
