from __future__ import annotations

from pathlib import Path

import pytest
from faketransfer import FakeStoragePhone

from admenot.engine.adb.transport import AdbError, classify_error
from admenot.engine.explorer.create import CreateError, make_folder, make_text
from admenot.engine.explorer.guard import ExplorerAdb, ExplorerPusher, UnsafeCommand, is_tmp_name
from admenot.engine.explorer.queue import read_tmp_folders, record_tmp_folder


@pytest.fixture
def phone(tmp_path: Path) -> FakeStoragePhone:
    p = FakeStoragePhone(tmp_path / "phone")
    p.local("/sdcard/Docs").mkdir(parents=True)
    return p


@pytest.fixture
def adb(phone: FakeStoragePhone) -> ExplorerAdb:
    return ExplorerAdb(phone)


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    tmp_dir, temp_dir = tmp_path / "explorer_tmp", tmp_path / "temp"
    temp_dir.mkdir()
    return tmp_dir, temp_dir


def text(adb, phone, dirs, name="note", body="hi", parent="/sdcard/Docs", **kw):
    return make_text(adb, phone, parent, name, body, tmp_dir=dirs[0], temp_dir=dirs[1], **kw)


def no_tmp(phone: FakeStoragePhone) -> bool:
    return not any(is_tmp_name(p.name) for p in (phone.root / "sdcard").rglob("*"))


def test_make_folder(adb, phone):
    assert make_folder(adb, "/sdcard/Docs", "New") == "/sdcard/Docs/New"
    assert phone.local("/sdcard/Docs/New").is_dir()


def test_make_folder_exists(adb, phone):
    phone.local("/sdcard/Docs/New").mkdir()
    (phone.local("/sdcard/Docs/f.txt")).write_bytes(b"x")
    for name in ("New", "f.txt"):
        with pytest.raises(CreateError) as e:
            make_folder(adb, "/sdcard/Docs", name)
        assert e.value.key == "exists"


def test_make_text_utf8_polish(adb, phone, dirs):
    path = text(adb, phone, dirs, "zażółć", "Zażółć gęślą jaźń\r\nlinia 2")
    assert path == "/sdcard/Docs/zażółć.txt"
    data = phone.local(path).read_bytes()
    assert data == "Zażółć gęślą jaźń\nlinia 2".encode()
    assert not data.startswith(b"\xef\xbb\xbf")
    assert no_tmp(phone)
    assert read_tmp_folders("FAKE", directory=dirs[0]) == []
    assert list(dirs[1].iterdir()) == []


def test_make_text_adds_extension(adb, phone, dirs):
    assert text(adb, phone, dirs, "a") == "/sdcard/Docs/a.txt"
    assert text(adb, phone, dirs, "b.TXT") == "/sdcard/Docs/b.TXT"
    assert text(adb, phone, dirs, "c.md") == "/sdcard/Docs/c.md.txt"


def test_make_text_exists_not_overwritten(adb, phone, dirs):
    phone.local("/sdcard/Docs/a.txt").write_bytes(b"old")
    with pytest.raises(CreateError) as e:
        text(adb, phone, dirs, "a", "new")
    assert e.value.key == "exists"
    assert phone.local("/sdcard/Docs/a.txt").read_bytes() == b"old"
    assert phone.push_calls == 0  # sprawdzenie przed wysłaniem


def test_make_text_target_appears_meanwhile(adb, phone, dirs):
    target = phone.local("/sdcard/Docs/a.txt")

    def appear(cmd: str) -> None:
        if cmd.startswith("mv -n"):
            target.write_bytes(b"other")

    phone.on_shell = appear
    with pytest.raises(CreateError) as e:
        text(adb, phone, dirs, "a", "new")
    assert e.value.key == "exists"
    assert target.read_bytes() == b"other"
    assert no_tmp(phone)
    assert read_tmp_folders("FAKE", directory=dirs[0]) == []


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\nb", "x" * 256, "ż" * 128])
def test_bad_names(adb, phone, dirs, name):
    for call in (lambda: make_folder(adb, "/sdcard/Docs", name), lambda: text(adb, phone, dirs, name)):
        with pytest.raises(CreateError) as e:
            call()
        assert e.value.key == "bad_name"
    assert phone.commands == [] and phone.push_calls == 0


def test_bad_name_after_extension(adb, phone, dirs):
    with pytest.raises(CreateError) as e:
        text(adb, phone, dirs, "x" * 252)
    assert e.value.key == "bad_name"


def test_denied(adb, phone, dirs):
    phone.deny_prefixes = {"/sdcard/Locked/"}
    phone.local("/sdcard/Locked").mkdir()
    with pytest.raises(CreateError) as e:
        make_folder(adb, "/sdcard/Locked", "New")
    assert e.value.key == "denied"
    with pytest.raises(CreateError) as e:
        text(adb, phone, dirs, "a", parent="/sdcard/Locked")
    assert e.value.key == "denied"
    assert no_tmp(phone)
    assert read_tmp_folders("FAKE", directory=dirs[0]) == []
    assert list(dirs[1].iterdir()) == []


def test_offline(adb, phone, dirs):
    phone.online = False

    def drop(cmd: str) -> None:
        raise AdbError("offline", "device offline")

    phone.on_shell = drop
    with pytest.raises(CreateError) as e:
        make_folder(adb, "/sdcard/Docs", "New")
    assert e.value.key == "offline"
    with pytest.raises(CreateError) as e:
        text(adb, phone, dirs, "a")
    assert e.value.key == "offline"


def test_offline_during_push_keeps_tmp_listed(adb, phone, dirs):
    phone.fail_after_push_files = 0  # push urywa się i telefon znika

    def drop(cmd: str) -> None:
        if cmd.startswith("rm -f") and not phone.online:
            raise AdbError("offline", "device offline")

    phone.on_shell = drop
    with pytest.raises(CreateError) as e:
        text(adb, phone, dirs, "a")
    assert e.value.key == "offline"
    assert read_tmp_folders("FAKE", directory=dirs[0]) == ["/sdcard/Docs"]
    assert list(dirs[1].iterdir()) == []
    assert not phone.local("/sdcard/Docs/a.txt").exists()


def test_listed_folder_stays_listed(adb, phone, dirs):
    record_tmp_folder("FAKE", "/sdcard/Docs", directory=dirs[0])
    text(adb, phone, dirs, "a")
    assert read_tmp_folders("FAKE", directory=dirs[0]) == ["/sdcard/Docs"]


def test_offline_word_in_folder_name_is_not_a_disconnect(adb, phone):
    # adb klasyfikuje błąd po tekście: „Mapy offline” w ścieżce daje rodzaj `offline`, choć telefon jest
    def refuse(cmd: str) -> None:
        if cmd.startswith("mkdir "):
            raise classify_error("mkdir: '/sdcard/Docs/Mapy offline': Permission denied")

    phone.on_shell = refuse
    with pytest.raises(CreateError) as e:
        make_folder(adb, "/sdcard/Docs", "Mapy offline")
    assert e.value.key == "denied"


def test_make_text_pushes_only_through_the_explorer_guard(adb, phone, dirs):
    seen: list[str] = []

    class Spy:
        def push(self, locals_, remote, should_stop, tick):
            seen.append(remote)
            return phone.push(locals_, remote, should_stop, tick)

    assert text(adb, Spy(), dirs, "a", "x") == "/sdcard/Docs/a.txt"
    assert len(seen) == 1 and is_tmp_name(seen[0].rsplit("/", 1)[1])
    # token spoza wzorca: strażnik odmawia, zanim cokolwiek trafi do `adb push`
    seen.clear()
    with pytest.raises((CreateError, UnsafeCommand)):
        text(adb, Spy(), dirs, "b", "x", token=lambda: "0123456789AB")
    assert seen == [] and not phone.local("/sdcard/Docs/b.txt").exists()
    # wrapper sam: cel inny niż nasz plik tymczasowy — odmowa
    with pytest.raises(UnsafeCommand):
        ExplorerPusher(Spy()).push([dirs[1] / "x"], "/sdcard/Docs/a.txt", lambda: False, lambda: None)
    assert seen == []
