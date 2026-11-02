from __future__ import annotations

import os
from pathlib import Path

import pytest
from faketransfer import FakeStoragePhone

from admenot.engine.adb.transport import AdbError
from admenot.engine.explorer.guard import ExplorerAdb
from admenot.engine.explorer.listing import ListError, folder_label, list_dir, locked_paths
from admenot.engine.explorer.places import Place, count_place, find_places


def put(phone: FakeStoragePhone, remote: str, data: bytes = b"x", mtime: int | None = None) -> None:
    path = phone.local(remote)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def mkdir(phone: FakeStoragePhone, remote: str) -> None:
    phone.local(remote).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def phone(tmp_path: Path) -> FakeStoragePhone:
    return FakeStoragePhone(tmp_path)


@pytest.fixture
def adb(phone: FakeStoragePhone) -> ExplorerAdb:
    return ExplorerAdb(phone)


def test_list_dir_returns_dirs_and_files(phone, adb):
    mkdir(phone, "/sdcard/root/Ą B")
    put(phone, "/sdcard/root/-a.jpg", b"abc", 1_600_000_000)
    put(phone, "/sdcard/root/$x zażółć.jpg", b"12345", 1_600_000_100)
    put(phone, "/sdcard/root/😀.png", b"1", 1_600_000_200)
    res = list_dir(adb, "/sdcard/root")
    assert res.skipped == 0
    by_name = {e.name: e for e in res.entries}
    assert set(by_name) == {"Ą B", "-a.jpg", "$x zażółć.jpg", "😀.png"}
    assert by_name["Ą B"].kind == "dir"
    assert by_name["Ą B"].path == "/sdcard/root/Ą B"
    for name, size, mtime in [("-a.jpg", 3, 1_600_000_000), ("$x zażółć.jpg", 5, 1_600_000_100),
                              ("😀.png", 1, 1_600_000_200)]:
        e = by_name[name]
        assert (e.kind, e.size, e.mtime, e.path, e.label, e.locked) == (
            "file", size, mtime, f"/sdcard/root/{name}", None, False)


def test_list_dir_accepts_trailing_slash_and_sdcard_root(phone, adb):
    put(phone, "/sdcard/a.txt")
    assert [e.path for e in list_dir(adb, "/sdcard").entries] == ["/sdcard/a.txt"]
    assert [e.path for e in list_dir(adb, "/sdcard/").entries] == ["/sdcard/a.txt"]
    assert "find /sdcard/ -mindepth 1" in phone.commands[0]


def test_list_dir_skips_hidden(phone, adb):
    put(phone, "/sdcard/root/.hidden")
    put(phone, "/sdcard/root/.admenot-0123456789ab.part")
    put(phone, "/sdcard/root/shown.txt")
    res = list_dir(adb, "/sdcard/root")
    assert [e.name for e in res.entries] == ["shown.txt"]
    assert res.skipped == 0


def test_list_dir_marks_locked_only_when_denied(phone, adb):
    mkdir(phone, "/sdcard/Android/data/com.x")
    mkdir(phone, "/sdcard/Android/obb")
    mkdir(phone, "/sdcard/Android/media")
    phone.deny_list_prefixes = {"/sdcard/Android/data/"}
    by_name = {e.name: e for e in list_dir(adb, "/sdcard/Android", sdk=33).entries}
    assert by_name["data"].locked is True
    assert by_name["obb"].locked is False
    assert by_name["media"].locked is False
    with pytest.raises(ListError) as exc:
        list_dir(adb, "/sdcard/Android/data")
    assert exc.value.kind == "denied"


def test_list_dir_listable_android_data_not_locked(phone, adb):
    mkdir(phone, "/sdcard/Android/data/com.x")
    mkdir(phone, "/sdcard/Android/obb")
    assert not any(e.locked for e in list_dir(adb, "/sdcard/Android", sdk=33).entries)


def test_list_dir_no_probe_below_android_11(phone, adb):
    mkdir(phone, "/sdcard/Android/data")
    phone.deny_list_prefixes = {"/sdcard/Android/data/"}
    assert not any(e.locked for e in list_dir(adb, "/sdcard/Android", sdk=29).entries)
    assert not any(c.startswith("ls ") for c in phone.commands)


def test_locked_paths_candidates():
    assert locked_paths(33) == {"/sdcard/Android/data", "/sdcard/Android/obb"}
    assert locked_paths(29) == frozenset()


def test_list_dir_missing_folder(adb):
    with pytest.raises(ListError) as exc:
        list_dir(adb, "/sdcard/nope")
    assert exc.value.kind == "missing"


def test_list_dir_offline(phone, adb):
    phone.online = False
    with pytest.raises(ListError) as exc:
        list_dir(adb, "/sdcard")
    assert exc.value.kind == "offline"


def test_list_dir_large_folder(phone, adb):
    phone.listing_extra["/sdcard/root"] = [(f"f{i}.jpg", i, 1_600_000_000 + i) for i in range(12_000)]
    mkdir(phone, "/sdcard/root")
    phone.commands.clear()
    res = list_dir(adb, "/sdcard/root")
    assert len(res.entries) == 12_000
    assert res.entries[5].size in range(12_000)
    assert len(phone.commands) == 1


def test_list_dir_refuses_newline_name(phone, adb):
    put(phone, "/sdcard/root/ok.txt")
    phone.listing_extra["/sdcard/root"] = [("bad\nname.txt", 7, 1), ("a\nb\nc.txt", 7, 1)]
    res = list_dir(adb, "/sdcard/root")
    assert [e.name for e in res.entries] == ["ok.txt"]
    assert res.skipped == 2


def test_list_dir_labels_app_folders(phone, adb):
    mkdir(phone, "/sdcard/Android/media/com.whatsapp")
    mkdir(phone, "/sdcard/Android/media/com.x.app")
    mkdir(phone, "/sdcard/Android/media/com.unknown")
    by_name = {e.name: e.label for e in
               list_dir(adb, "/sdcard/Android/media", apps={"com.x.app": "Moja aplikacja"}).entries}
    assert by_name == {"com.whatsapp": "WhatsApp", "com.x.app": "Moja aplikacja", "com.unknown": None}


def test_folder_label():
    apps = {"com.x.app": "Moja aplikacja"}
    assert folder_label("/sdcard/Android/media/com.whatsapp", apps) == "WhatsApp"
    assert folder_label("Android/media/com.whatsapp", {}) == "WhatsApp"
    assert folder_label("/sdcard/Android/media/com.x.app", apps) == "Moja aplikacja"
    assert folder_label("/sdcard/Android/data/com.x.app", apps) == "Moja aplikacja"
    assert folder_label("/sdcard/Android/data/com.unknown", apps) is None
    assert folder_label("/sdcard/DCIM", apps) is None
    assert folder_label("/sdcard/Android/media/com.x.app/sub", apps) is None


def test_find_places_skips_missing(phone, adb):
    mkdir(phone, "/sdcard/DCIM/Camera")
    mkdir(phone, "/sdcard/DCIM/Screenshots")
    put(phone, "/sdcard/Download")  # plik, nie folder
    mkdir(phone, "/sdcard/Music")
    places = find_places(adb)
    assert [(p.key, p.path) for p in places] == [
        ("camera", "/sdcard/DCIM/Camera"), ("screenshots", "/sdcard/DCIM/Screenshots"),
        ("music", "/sdcard/Music"), ("all", "/sdcard")]
    assert all(p.count is None and p.icon for p in places)
    assert len(phone.commands) == 1


def test_find_places_only_all_on_empty_phone(adb):
    assert [p.key for p in find_places(adb)] == ["all"]


def test_screenshots_prefers_pictures(phone, adb):
    mkdir(phone, "/sdcard/DCIM/Screenshots")
    mkdir(phone, "/sdcard/Pictures/Screenshots")
    assert next(p for p in find_places(adb) if p.key == "screenshots").path == "/sdcard/Pictures/Screenshots"


def test_whatsapp_new_path_preferred(phone, adb):
    mkdir(phone, "/sdcard/WhatsApp/Media")
    assert next(p for p in find_places(adb) if p.key == "whatsapp").path == "/sdcard/WhatsApp/Media"
    mkdir(phone, "/sdcard/Android/media/com.whatsapp/WhatsApp/Media")
    assert next(p for p in find_places(adb) if p.key == "whatsapp").path == \
        "/sdcard/Android/media/com.whatsapp/WhatsApp/Media"


def test_count_place_counts_recursively_visible_files(phone, adb):
    put(phone, "/sdcard/Music/a.mp3")
    put(phone, "/sdcard/Music/Album/b.mp3")
    put(phone, "/sdcard/Music/Album/Disc 2/c.mp3")
    put(phone, "/sdcard/Music/.hidden.mp3")
    assert count_place(adb, Place("music", "/sdcard/Music", None, "music")) == 3


def test_count_place_is_one_call_and_skips_hidden_components(phone, adb):
    put(phone, "/sdcard/Music/.hidden/d.mp3")
    put(phone, "/sdcard/Music/Album/.nomedia")
    put(phone, "/sdcard/Music/Album/e.mp3")
    put(phone, "/sdcard/Music/f.mp3")
    phone.commands.clear()
    assert count_place(adb, Place("music", "/sdcard/Music", None, "music")) == 2
    assert phone.commands == ["find /sdcard/Music/ -type f"]


def test_count_place_denied_raises_list_error(phone, adb):
    mkdir(phone, "/sdcard/Android/data")
    phone.deny_list_prefixes = {"/sdcard/Android/data/"}
    with pytest.raises(ListError) as exc:
        count_place(adb, Place("x", "/sdcard/Android/data", None, "phone"))
    assert exc.value.kind == "denied"


def test_list_dir_trailing_newline_name_is_skipped(phone, adb):
    put(phone, "/sdcard/root/ok.txt")
    phone.listing_extra["/sdcard/root"] = [("ends\n", 7, 1)]
    res = list_dir(adb, "/sdcard/root")
    assert [e.name for e in res.entries] == ["ok.txt"]
    assert res.skipped == 1


def test_find_places_offline_is_list_error(phone, adb):
    phone.online = False
    with pytest.raises(ListError) as exc:
        find_places(adb)
    assert exc.value.kind == "offline"


def test_locked_probe_offline_is_list_error(phone, adb):
    mkdir(phone, "/sdcard/Android/data")
    original = phone.on_shell

    def go_offline(command: str) -> None:
        if command.startswith("ls "):
            phone.online = False
            raise AdbError("offline", "device offline")

    phone.on_shell = go_offline
    with pytest.raises(ListError) as exc:
        list_dir(adb, "/sdcard/Android", sdk=33)
    assert exc.value.kind == "offline"
    phone.on_shell = original


def test_fake_streaming_commands(phone, adb):
    put(phone, "/sdcard/f.bin", bytes(range(200)))
    assert adb.run_bytes(["exec-out", "head -c 4 /sdcard/f.bin"]) == bytes(range(4))
    assert adb.run_bytes(["exec-out", "tail -c +198 /sdcard/f.bin"]) == bytes(range(197, 200))
    put(phone, "/sdcard/d/.admenot-0123456789ab.part", b"new")
    put(phone, "/sdcard/d/x.txt", b"old")
    adb.shell("mv -n /sdcard/d/.admenot-0123456789ab.part /sdcard/d/x.txt")
    assert phone.local("/sdcard/d/x.txt").read_bytes() == b"old"
    adb.shell("mv -n /sdcard/d/.admenot-0123456789ab.part /sdcard/d/y.txt")
    assert phone.local("/sdcard/d/y.txt").read_bytes() == b"new"
