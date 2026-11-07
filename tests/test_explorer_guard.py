from __future__ import annotations

import pytest

from admenot.engine.explorer.guard import (
    STREAM_BLOCK,
    ExplorerAdb,
    ExplorerPusher,
    UnsafeCommand,
    assert_explorer,
    explorer_pusher,
    is_tmp_name,
    safe_read_path,
    stream_args,
)
from admenot.engine.transfer.guard import SCAN_VOLUME_CMD, q
from admenot.engine.transfer.puller import PullResult

TMP = "/sdcard/Download/.admenot-0123456789ab.part"


class Recorder:
    def __init__(self, serial: str | None = "S1") -> None:
        self.serial = serial
        self.calls: list[tuple[str, object]] = []

    def shell(self, command: str, timeout: float = 20.0) -> str:
        self.calls.append(("shell", command))
        return "ok"

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        self.calls.append(("run", args))
        return "ok"

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        self.calls.append(("run_bytes", args))
        return b"ok"

    def with_serial(self, serial: str) -> Recorder:
        return Recorder(serial)


@pytest.mark.parametrize("cmd", [
    "find '/sdcard/DCIM' -mindepth 1 -maxdepth 1 -exec stat -c '%f|%s|%Y|%n' {} +",
    "find '/sdcard/' -mindepth 1 -maxdepth 1 -exec stat -c '%f|%s|%Y|%n' {} +",
    "find '/sdcard/DCIM/' -mindepth 1 -maxdepth 1 -exec stat -c '%f|%s|%Y|%n' {} +",
    "stat -c '%f|%s|%Y|%n' '/sdcard/a b' 2>&1 || true",
    "du -sb '/sdcard/Download/' 2>&1 || true",
    "du -sk '/sdcard/Zdjęcia klienta/' 2>&1 || true",
    "find '/sdcard/Download/' -type f -exec stat -c '%s|%n' {} + 2>&1 || true",
    "find /sdcard/ -type f -exec stat -c '%s|%n' {} + 2>&1 || true",
    "find '/sdcard/Download/' -type f 2>&1 || true",
    "sha256sum '/sdcard/x'",
    "df -k /sdcard",
    "ls '/sdcard/DCIM/'",
    "ls '/sdcard/DCIM/' 2>&1",
    "head -c 131072 '/sdcard/x.jpg'",
    "head -c 1048576 '/sdcard/x.jpg'",
    "tail -c +1 '/sdcard/$x zażółć.jpg'",
    "dd if='/sdcard/a b.mp4' bs=65536 skip=12 status=none",
    "dd if='/sdcard/a.mp4' bs=65536 skip=0 status=none count=4",
    "getprop ro.build.version.sdk",
    ("content query --uri content://media/external/file --projection "
     "_id:mime_type:duration:width:height:artist:album:title:bitrate "
     "--where \"_data='/storage/emulated/0/Music/a.mp3'\""),
])
def test_allows_reads(cmd):
    assert_explorer(cmd)


@pytest.mark.parametrize("cmd", [
    "mkdir -p '/sdcard/Nowy folder'",
    f"mv -n '{TMP}' '/sdcard/Download/a (z komputera).txt'",
    "content call --uri content://media --method scan_file --arg '/storage/emulated/0/DCIM/a.jpg'",
    SCAN_VOLUME_CMD,
    f"rm -f '{TMP}'",
])
def test_allows_writes_under_sdcard(cmd):
    assert_explorer(cmd)


@pytest.mark.parametrize("cmd", [
    "rm '/sdcard/Download/.admenot-0123456789ab.part'",
    "du -sb '/data/data/' 2>&1 || true",
    "du -sb '/sdcard/../data/' 2>&1 || true",
    "du -sb '/sdcard/a' '/sdcard/b' 2>&1 || true",
    "du -sbL '/sdcard/a/' 2>&1 || true",
    "du -s -b '/sdcard/a/' 2>&1 || true",
    "du -sb /sdcard/a/;reboot 2>&1 || true",
    "rm -f '/sdcard/a.jpg'",
    "rm -rf '/sdcard/Download'",
    f"rm -f '{TMP}' '/sdcard/Download/.admenot-aaaaaaaaaaaa.part'",
    "rm -f '/sdcard/.admenot-*.part'",
    "rm -f /data/local/tmp/.admenot-0123456789ab.part",
    f"mv '{TMP}' '/sdcard/Download/a.txt'",
    "mv -n '/sdcard/Download/a.jpg' '/sdcard/Download/b.jpg'",
    f"mv -n '{TMP}' '/sdcard/Other/a.txt'",
    f"mv -n '{TMP}' '/data/a.txt'",
    "cp '/sdcard/a' '/sdcard/b'",
    "mkdir -p /data/x",
    "mkdir -p '/sdcard/../data/x'",
    "head -c 1048577 '/sdcard/x'",
    "head -c 999999999 x",
    "tail -c +1 /data/x",
    "tail -c +1 '/sdcard/../data/x'",
    "tail -c 5 '/sdcard/x'",
    "dd if=/data/x bs=65536 skip=0 status=none",
    "dd if='/sdcard/x' bs=65536 skip=0 of='/sdcard/y' status=none",
    "dd if='/sdcard/x' bs=65536 skip=0",
    "dd if='/sdcard/x' bs=1 skip=0 status=none",
    "dd if='/sdcard/x' bs=65536 skip=-1 status=none",
    "dd if='/sdcard/x' bs=65536 skip=0 status=none seek=1",
    "dd if='/sdcard/x' bs=65536 skip=0 status=none of='/sdcard/y'",
    "ls '/data/'",
    "stat -c '%s' '/sdcard/x'",
    "ls '/sdcard/x\ny'",
    "ls '/sdcard/x'; reboot",
    "ls '/sdcard/x' | cat",
    "ls '/sdcard/x' > '/sdcard/y'",
    "ls $(reboot)",
    "ls '/sdcard/x' `id`",
    "find '/sdcard/' -mindepth 1 -maxdepth 1 -delete",
    "find '/sdcard/' -exec rm {} +",
    "find '/sdcard/' -type f -delete",
    "find '/sdcard/' -type f -exec rm {} +",
    "find '/sdcard/' -type f -print",
    "find '/sdcard/' -type d",
    "find '/sdcard/' -type f 2>&1",
    "find '/data/local/' -type f",
    "find '/sdcard/../data/' -type f",
    "content insert --uri content://sms --bind a:s:b",
    "content call --uri content://media --method other",
    "content call --uri content://media --method scan_file --arg '/data/a.jpg'",
    "reboot",
    "sha256sum /data/x",
    "rm\xa0-rf\xa0/sdcard",
    "rm\x0b-rf /sdcard/x",
    "head x",
    # przejście Miejsca: tylko ta postać, tylko pod /sdcard/
    "find '/data/' -type f -exec stat -c '%s|%n' {} + 2>&1 || true",
    "find /data/media/0 -type f -exec stat -c '%s|%n' {} + 2>&1 || true",
    "find '/sdcard/../data/' -type f -exec stat -c '%s|%n' {} + 2>&1 || true",
    "find '/sdcard/DCIM/..' -type f -exec stat -c '%s|%n' {} + 2>&1 || true",
    "find '/data/' -type f 2>&1 || true",
    "find '/sdcard/DCIM/' -type f -exec stat -c '%s|%n' {} +; reboot 2>&1 || true",
    "find '/sdcard/DCIM/' -type f -exec rm {} + 2>&1 || true",
    "find '/sdcard/DCIM/' -type f -delete 2>&1 || true",
    "find '/sdcard/DCIM/' -type f -exec stat -c %s {} +",
    "ls '/sdcard/a' 2>&1 || true",
    "rm -rf /sdcard 2>&1 || true",
])
def test_refuses(cmd):
    with pytest.raises(UnsafeCommand):
        assert_explorer(cmd)


def test_is_tmp_name():
    assert is_tmp_name(".admenot-0123456789ab.part")
    for name in (".admenot-x.part", "a.part", ".admenot-0123456789ab.part.jpg", ".admenot-0123456789AB.part"):
        assert not is_tmp_name(name)


def test_safe_read_path():
    assert safe_read_path("/sdcard/a b") == "/sdcard/a b"
    for p in ("/data/x", "/sdcard/../x", "/sdcard/a\nb"):
        with pytest.raises(UnsafeCommand):
            safe_read_path(p)


def test_stream_args_uses_dd_and_block_seek():
    args = stream_args("/sdcard/$x zażółć.mp4", 3 * STREAM_BLOCK + 17)
    assert args == ["exec-out", f"dd if={q('/sdcard/$x zażółć.mp4')} bs=65536 skip=3 status=none"]
    assert stream_args("/sdcard/a.mp4", 0)[1].endswith("skip=0 status=none")
    with pytest.raises(UnsafeCommand):
        stream_args("/sdcard/a.mp4", -1)
    with pytest.raises(UnsafeCommand):
        stream_args("/data/a.mp4", 0)


def test_explorer_adb_filters():
    rec = Recorder()
    adb = ExplorerAdb(rec)
    assert adb.serial == "S1" and adb.with_serial("S2").serial == "S2"
    assert adb.shell("df -k /sdcard") == "ok"
    adb.run(["shell", "-T", "ls '/sdcard/'"])
    adb.run(["get-state"])
    adb.run(["pull", "/sdcard/a.jpg", "C:/tmp/a.jpg"])
    adb.run(["push", "C:/tmp/a.jpg", TMP])
    adb.run_bytes(adb.stream_args("/sdcard/a.mp4", 100))
    adb.run_bytes(["exec-out", "head -c 100 '/sdcard/a'"])
    adb.run_bytes(["exec-out", "tail -c +5 '/sdcard/a'"])
    n = len(rec.calls)
    for bad in (
        ["shell", "rm -f '/sdcard/a'"], ["shell", "-T", "rm -rf /sdcard"], ["install", "x.apk"],
        ["pull", "/data/x", "C:/tmp/x"], ["push", "C:/tmp/a", "/sdcard/a.jpg"],
        ["push", "C:/tmp/a", "/data/.admenot-0123456789ab.part"],
    ):
        with pytest.raises(UnsafeCommand):
            adb.run(bad)
    for bad in (["exec-out", "ls '/sdcard/'"], ["exec-out", "cat '/sdcard/a'"],
                ["shell", "-T", "head -c 5 '/sdcard/a'"], ["exec-out", "dd if=/data/x bs=65536 skip=0 status=none"]):
        with pytest.raises(UnsafeCommand):
            adb.run_bytes(bad)
    with pytest.raises(UnsafeCommand):
        adb.shell("cp a b")
    assert len(rec.calls) == n


class PushRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[list, str]] = []

    def push(self, locals_, remote, should_stop, tick):
        self.calls.append((list(locals_), remote))
        return PullResult(0, ["1 file pushed"], False)


@pytest.mark.parametrize("remote", [
    "/sdcard/Download/a.jpg",  # cudzy plik — nigdy wprost
    "/sdcard/Download/",  # folder
    "/sdcard/Download/.admenot-0123456789AB.part",  # wielkie litery
    "/sdcard/Download/.admenot-0123456789a.part",  # 11 znaków
    "/sdcard/Download/x.admenot-0123456789ab.part",
    "/data/local/tmp/.admenot-0123456789ab.part",  # poza /sdcard/
    "/data/local/tmp/admenot/input.json",  # katalog pomocnika (`safe_push_target` by go przepuścił)
    "/sdcard/../data/.admenot-0123456789ab.part",
    "/sdcard/a\n/.admenot-0123456789ab.part",
])
def test_explorer_pusher_refuses_non_tmp_targets(tmp_path, remote):
    inner = PushRecorder()
    with pytest.raises(UnsafeCommand):
        ExplorerPusher(inner).push([tmp_path / "a.jpg"], remote, lambda: False, lambda: None)
    assert inner.calls == []  # adb nawet nie ruszył


def test_explorer_pusher_accepts_tmp_target_and_delegates(tmp_path):
    inner = PushRecorder()
    pusher = explorer_pusher(inner)
    assert explorer_pusher(pusher) is pusher  # bez podwójnego owijania
    res = pusher.push([tmp_path / "a.jpg"], TMP, lambda: False, lambda: None)
    assert res.rc == 0 and inner.calls == [([tmp_path / "a.jpg"], TMP)]
    with pytest.raises(UnsafeCommand):  # jeden plik na raz (cel to plik, nie folder)
        pusher.push([tmp_path / "a.jpg", tmp_path / "b.jpg"], TMP, lambda: False, lambda: None)
