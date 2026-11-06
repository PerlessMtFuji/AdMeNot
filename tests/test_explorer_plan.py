from __future__ import annotations

import os
from pathlib import Path

import pytest
from faketransfer import FakeStoragePhone

from admenot.engine.explorer.guard import ExplorerAdb, assert_explorer
from admenot.engine.explorer.hostfs import filesystem, free_bytes, long_path, writable
from admenot.engine.explorer.plan import plan_to_pc, plan_to_phone, side_name

GIB = 1 << 30
OK = {"free_bytes": lambda p: 10**15, "filesystem": lambda p: "NTFS", "writable": lambda p: True}


def put(phone: FakeStoragePhone, remote: str, data: bytes = b"x") -> None:
    path = phone.local(remote)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def phone(tmp_path: Path) -> FakeStoragePhone:
    return FakeStoragePhone(tmp_path / "phone")


@pytest.fixture
def adb(phone: FakeStoragePhone) -> ExplorerAdb:
    return ExplorerAdb(phone)


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    d = tmp_path / "pc"
    d.mkdir()
    return d


def test_expands_folders_recursively(phone, adb, dest):
    put(phone, "/sdcard/Pics/a.jpg", b"aa")
    phone.local("/sdcard/Pics/sub/deep").mkdir(parents=True)
    phone.listing_extra["/sdcard/Pics/sub/deep"] = [("b?x.jpg", 1, 1)]  # nazwa niedozwolona w Windows
    put(phone, "/sdcard/Pics/.hidden", b"h")
    put(phone, "/sdcard/Pics/.admenot-0123456789ab.part", b"t")
    phone.local("/sdcard/Pics/empty").mkdir()
    put(phone, "/sdcard/single.txt", b"s")
    plan = plan_to_pc(adb, ["/sdcard/Pics", "/sdcard/single.txt"], dest, **OK)
    got = {i.src: (i.dst, i.action) for i in plan.items}
    assert got == {
        "/sdcard/Pics/a.jpg": (str(dest / "Pics" / "a.jpg"), "copy"),
        "/sdcard/Pics/.hidden": (str(dest / "Pics" / ".hidden"), "copy"),
        "/sdcard/Pics/sub/deep/b?x.jpg": (str(dest / "Pics" / "sub" / "deep" / "b_x.jpg"), "copy"),
        "/sdcard/single.txt": (str(dest / "single.txt"), "copy"),
    }
    assert plan.kind == "to_pc"
    assert plan.bytes == 5
    assert plan.problems == [] and plan.skipped == 0
    assert str(dest / "Pics" / "empty") in plan.dirs
    assert plan.dirs.index(str(dest / "Pics" / "sub")) < plan.dirs.index(str(dest / "Pics" / "sub" / "deep"))


def test_same_name_other_size_goes_beside(phone, adb, dest):
    put(phone, "/sdcard/a.jpg", b"phone!")
    (dest / "a.jpg").write_bytes(b"pc")
    plan = plan_to_pc(adb, ["/sdcard/a.jpg"], dest, **OK)
    assert [(i.dst, i.action) for i in plan.items] == [(str(dest / "a (z telefonu).jpg"), "renamed")]


def test_same_name_same_size_needs_hash(phone, adb, dest):
    put(phone, "/sdcard/a.jpg", b"abc")
    (dest / "a.jpg").write_bytes(b"xyz")
    plan = plan_to_pc(adb, ["/sdcard/a.jpg"], dest, **OK)
    assert [(i.dst, i.action) for i in plan.items] == [(str(dest / "a.jpg"), "check_hash")]


def test_same_dst_twice_in_plan_is_renamed(phone, adb, dest):
    put(phone, "/sdcard/A/a.jpg", b"1")
    put(phone, "/sdcard/B/a.jpg", b"1")
    plan = plan_to_pc(adb, ["/sdcard/A/a.jpg", "/sdcard/B/a.jpg"], dest, **OK)
    assert [(Path(i.dst).name, i.action) for i in plan.items] == [("a.jpg", "copy"), ("a (z telefonu).jpg", "renamed")]


def test_side_name_sequence():
    taken: set[str] = {"a.jpg"}
    first = side_name("a.jpg", taken, "z telefonu")
    assert first == "a (z telefonu).jpg"
    taken.add(first)
    assert side_name("a.jpg", taken, "z telefonu") == "a (z telefonu 2).jpg"
    assert side_name("A.JPG", taken, "z komputera") == "A (z komputera).JPG"
    assert side_name("README", set(), "z komputera") == "README (z komputera)"
    assert side_name("x.tar.gz", set(), "z telefonu") == "x.tar (z telefonu).gz"


def test_no_space_on_phone(phone, adb, tmp_path):
    phone.free_kb = 2
    f = tmp_path / "big.bin"
    f.write_bytes(b"0" * 5000)
    plan = plan_to_phone(adb, [f], "/sdcard/Download")
    (problem,) = plan.problems
    assert problem.key == "no_space"
    assert problem.detail["missing"] == 5000 - 2048
    assert plan_to_phone(adb, [tmp_path / "nope"], "/sdcard/Download").problems == []


def test_df_command_is_allowed():
    assert_explorer("df -k /sdcard")


def test_no_space_on_pc(phone, adb, dest):
    put(phone, "/sdcard/a.bin", b"0" * 100)
    plan = plan_to_pc(adb, ["/sdcard/a.bin"], dest, **{**OK, "free_bytes": lambda p: 40})
    (problem,) = plan.problems
    assert (problem.key, problem.detail["missing"]) == ("no_space", 60)


def test_fat32_big_file(phone, adb, dest):
    phone.local("/sdcard/V").mkdir(parents=True)
    phone.listing_extra["/sdcard/V"] = [("huge.mkv", 4 * GIB + 1, 1), ("edge.mkv", 4 * GIB - 1, 1)]
    plan = plan_to_pc(adb, ["/sdcard/V"], dest, **{**OK, "filesystem": lambda p: "FAT32"})
    fat = [p for p in plan.problems if p.key == "fat32_big"]
    assert [p.detail["names"] for p in fat] == [["huge.mkv"]]
    ntfs = plan_to_pc(adb, ["/sdcard/V"], dest, **OK)
    assert not [p for p in ntfs.problems if p.key == "fat32_big"]


def test_read_only_dest(phone, adb, dest):
    put(phone, "/sdcard/a.txt")
    plan = plan_to_pc(adb, ["/sdcard/a.txt"], dest, **{**OK, "writable": lambda p: False})
    assert [p.key for p in plan.problems] == ["read_only"]


def test_long_windows_path(phone, adb, tmp_path):
    put(phone, "/sdcard/f.txt", b"x")
    deep = tmp_path / ("d" * 100) / ("e" * 100) / ("f" * 100)
    plan = plan_to_pc(adb, ["/sdcard/f.txt"], deep, **OK)
    assert plan.problems == []
    if os.name == "nt":
        assert plan.items[0].dst.startswith("\\\\?\\") and len(plan.items[0].dst) > 260
    huge = tmp_path / ("g" * 33000)
    plan = plan_to_pc(adb, ["/sdcard/f.txt"], huge, **OK)
    assert [p.key for p in plan.problems] == ["path_too_long"]


def test_upload_conflicts_and_structure(phone, adb, tmp_path):
    put(phone, "/sdcard/Up/a.txt", b"12")
    put(phone, "/sdcard/Up/b.txt", b"123")
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"1234")  # inny rozmiar
    (src / "b.txt").write_bytes(b"abc")  # ten sam rozmiar
    (src / "sub" / "c.txt").write_bytes(b"c")
    plan = plan_to_phone(adb, [src / "a.txt", src / "b.txt", src / "sub"], "/sdcard/Up/")
    got = {Path(i.src).name: (i.dst, i.action) for i in plan.items}
    assert got == {
        "a.txt": ("/sdcard/Up/a (z komputera).txt", "renamed"),
        "b.txt": ("/sdcard/Up/b.txt", "check_hash"),
        "c.txt": ("/sdcard/Up/sub/c.txt", "copy"),
    }
    assert plan.dirs == ["/sdcard/Up/sub"] and plan.kind == "to_phone" and plan.bytes == 8


def test_upload_into_locked_folder(phone, adb, tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"1")
    for locked in (["/sdcard/Android/data"], lambda p: p.startswith("/sdcard/Android/data")):
        plan = plan_to_phone(adb, [f], "/sdcard/Android/data/com.x/files", locked=locked)
        assert [p.key for p in plan.problems] == ["denied"] and plan.items == []
    assert plan_to_phone(adb, [f], "/sdcard/Download", locked=["/sdcard/Android/data"]).problems == []


def test_hostfs_real_volume(tmp_path):
    assert free_bytes(tmp_path / "missing" / "x") > 0
    assert writable(tmp_path)
    if os.name == "nt":
        assert filesystem(tmp_path)
        assert long_path("C:\\" + "a" * 300).startswith("\\\\?\\C:\\")


def test_exclude_leaves_chosen_files_and_folders_out(phone, adb, dest):
    put(phone, "/sdcard/P/big.mp4", b"b")
    put(phone, "/sdcard/P/ok.jpg", b"o")
    put(phone, "/sdcard/P/Blok/x.jpg", b"x")
    plan = plan_to_pc(adb, ["/sdcard/P"], dest, exclude={"/sdcard/P/big.mp4", "/sdcard/P/Blok"}, **OK)
    assert [i.src for i in plan.items] == ["/sdcard/P/ok.jpg"]
    assert plan.skipped == 0


def test_fat32_problem_carries_full_paths_for_exclude(phone, adb, dest):
    phone.local("/sdcard/V").mkdir(parents=True)
    phone.listing_extra["/sdcard/V"] = [("huge.mkv", 4 * GIB + 1, 1)]
    plan = plan_to_pc(adb, ["/sdcard/V"], dest, **{**OK, "filesystem": lambda p: "FAT32"})
    (fat,) = [p for p in plan.problems if p.key == "fat32_big"]
    assert fat.detail["paths"] == ["/sdcard/V/huge.mkv"]
    again = plan_to_pc(adb, ["/sdcard/V"], dest, exclude=set(fat.detail["paths"]),
                       **{**OK, "filesystem": lambda p: "FAT32"})
    assert again.problems == [] and again.items == []
