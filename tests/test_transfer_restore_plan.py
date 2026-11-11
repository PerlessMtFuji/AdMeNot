from __future__ import annotations

import dataclasses
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from faketransfer import DEFAULT_FREE_KB, FakeStoragePhone

from admenot.engine.adb.transport import AdbError
from admenot.engine.device.info import DeviceInfo
from admenot.engine.transfer import restore_plan as rp
from admenot.engine.transfer import store
from admenot.engine.transfer.apkcheck import ApkCheck
from admenot.engine.transfer.backup import Selection, _cmd_batches, run_backup
from admenot.engine.transfer.guard import STAT_TAIL, AppendOnlyAdb, ReadOnlyAdb, q
from admenot.engine.transfer.inventory import Inventory, scan_files
from admenot.engine.transfer.restore_plan import (
    UPLOAD_GROUPS,
    GroupTotals,
    PhoneSpace,
    alt_name,
    build_plan,
    read_space,
    reserve,
)
from admenot.engine.transfer.telephony import Stopped

NOW = datetime(2026, 10, 25, 12, 0, 0)
MTIME = 1_700_000_000
GiB = 1024 ** 3
OLD = {
    "DCIM/Camera/IMG.JPG": b"I" * 300,
    "DCIM/Camera/VID.MP4": b"V" * 500,
    "DCIM/x.heic": b"H" * 20,
    "DCIM/plik": b"P" * 10,
    "Download/c.pdf": b"%PDF" + b"c" * 50,
}


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))


def _device() -> DeviceInfo:
    return DeviceInfo(
        serial="OLD", brand="oppo", manufacturer="OPPO", model="CPH2127", device="x",
        market_name=None, android_release="11", sdk=30, security_patch=None, uptime_s=1.0,
        local_now=NOW)


def _write(root: Path, files: dict[str, bytes], mtime: int = MTIME) -> None:
    (root / "sdcard").mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        path = root / "sdcard" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (mtime, mtime))


def _copy(tmp_path: Path, files: dict[str, bytes] = OLD, others: set[str] | None = None,
          extra: tuple[str, ...] = ()) -> store.CopyDir:
    """Kopia Etapu 1: `run_backup` ze starego telefonu (Zdjęcia i Pobrane)."""
    _write(tmp_path / "old", files)
    old = FakeStoragePhone(tmp_path / "old", serial="OLD")
    found, others, unreadable = scan_files(ReadOnlyAdb(old), lambda: False)
    inv = Inventory(contacts=0, sms=0, mms=0, mms_bytes=0, calls=0, files=found, others=others,
                    apps=[], skipped_apps=[], whatsapp_backup=None, storage=None, unreadable=unreadable)
    sel = Selection(contacts=False, sms=False, mms=False, calls=False,
                    categories=frozenset({"media", "downloads", *extra}), others=frozenset(others or ()),
                    apps=frozenset())
    copy = store.create_copy("OLD", _device(), None, NOW)
    res = run_backup(old, old, _device(), copy, inv, sel, on_progress=lambda p: None,
                     should_stop=lambda: False, wait_device=old.reconnect, free_bytes=lambda p: 10 ** 12)
    assert res.status == "complete"
    return copy


def _new(tmp_path: Path, files: dict[str, bytes] | None = None, mtime: int = MTIME) -> FakeStoragePhone:
    _write(tmp_path / "new", files or {}, mtime)
    return FakeStoragePhone(tmp_path / "new", serial="NEW")


def _plan(new: FakeStoragePhone, copy: store.CopyDir, **kw) -> rp.RestorePlan:
    return build_plan(AppendOnlyAdb(new), copy, lambda: False, **kw)


def _by_remote(plan: rp.RestorePlan) -> dict[str, rp.PlanFile]:
    return {f.remote: f for f in plan.files}


def test_new_phone_empty_all_push(tmp_path):
    copy = _copy(tmp_path)
    plan = _plan(_new(tmp_path), copy)
    files = _by_remote(plan)
    assert set(files) == {"/sdcard/" + rel for rel in OLD}
    for f in plan.files:
        assert (f.action, f.target, f.apk) == ("push", f.remote, None)
        assert f.local.is_absolute()
        assert f.local.read_bytes() == OLD[f.remote[len("/sdcard/"):]]
        assert (f.size, f.mtime) == (len(OLD[f.remote[len("/sdcard/"):]]), MTIME)
    assert plan.groups["downloads"] == GroupTotals(files=1, bytes=54, exists=0, rename=0)
    assert plan.space == PhoneSpace(free=DEFAULT_FREE_KB * 1024, total=120_000_000 * 1024)
    assert plan.reserve == reserve(plan.space)
    assert plan.need(set(UPLOAD_GROUPS), set()) == sum(len(d) for d in OLD.values())


def test_identical_file_exists(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, {"DCIM/Camera/IMG.JPG": OLD["DCIM/Camera/IMG.JPG"]}, mtime=MTIME + 2)
    plan = _plan(new, copy)
    f = _by_remote(plan)["/sdcard/DCIM/Camera/IMG.JPG"]
    assert (f.action, f.target) == ("exists", "/sdcard/DCIM/Camera/IMG.JPG")
    assert plan.groups["photos"].exists == 1
    assert plan.need({"photos"}, set()) == 20 + 10  # x.heic + plik, bez istniejącego IMG.JPG


def test_mtime_3s_off_is_conflict(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, {"DCIM/Camera/IMG.JPG": OLD["DCIM/Camera/IMG.JPG"]}, mtime=MTIME - 3)
    f = _by_remote(_plan(new, copy))["/sdcard/DCIM/Camera/IMG.JPG"]
    assert (f.action, f.target) == ("rename", "/sdcard/DCIM/Camera/IMG (z kopii).JPG")


def test_conflict_takes_next_free_alt_name(tmp_path):
    copy = _copy(tmp_path)
    theirs = {"DCIM/Camera/IMG.JPG": b"other", "DCIM/Camera/IMG (z kopii).JPG": b"older copy"}
    new = _new(tmp_path, theirs)
    plan = _plan(new, copy)
    f = _by_remote(plan)["/sdcard/DCIM/Camera/IMG.JPG"]
    assert (f.action, f.target) == ("rename", "/sdcard/DCIM/Camera/IMG (z kopii 2).JPG")
    assert plan.groups["photos"].rename == 1
    assert plan.need({"photos"}, set()) == 300 + 20 + 10  # zapis obok liczy się w pełnym rozmiarze
    for rel, data in theirs.items():  # plan niczego nie zmienia na telefonie
        assert new.local("/sdcard/" + rel).read_bytes() == data


def test_alt_name_not_reused_within_plan(tmp_path):
    """Plik kopii `a (z kopii).jpg` zajmuje tę nazwę, więc konflikt `a.jpg` idzie dalej."""
    copy = _copy(tmp_path, {"DCIM/a.jpg": b"A" * 5, "DCIM/a (z kopii).jpg": b"B" * 6})
    plan = _plan(_new(tmp_path, {"DCIM/a.jpg": b"theirs"}), copy)
    files = _by_remote(plan)
    assert files["/sdcard/DCIM/a (z kopii).jpg"].action == "push"
    assert files["/sdcard/DCIM/a.jpg"].target == "/sdcard/DCIM/a (z kopii 2).jpg"


def test_alt_identical_from_lost_state_is_exists(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, {"DCIM/Camera/IMG.JPG": b"other",
                          "DCIM/Camera/IMG (z kopii).JPG": OLD["DCIM/Camera/IMG.JPG"]})
    f = _by_remote(_plan(new, copy))["/sdcard/DCIM/Camera/IMG.JPG"]
    assert (f.action, f.target) == ("exists", "/sdcard/DCIM/Camera/IMG (z kopii).JPG")


def test_taken_alts_keep_previous_target(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, {"DCIM/Camera/IMG.JPG": b"other",
                          "DCIM/Camera/IMG (z kopii 3).JPG": b"half"})  # nasz niedokończony plik
    taken = {"/sdcard/DCIM/Camera/IMG.JPG": "/sdcard/DCIM/Camera/IMG (z kopii 3).JPG",
             "/sdcard/DCIM/x.heic": "/sdcard/DCIM/x.heic"}
    files = _by_remote(_plan(new, copy, taken_alts=taken))
    assert (files["/sdcard/DCIM/Camera/IMG.JPG"].action,
            files["/sdcard/DCIM/Camera/IMG.JPG"].target) == ("rename", "/sdcard/DCIM/Camera/IMG (z kopii 3).JPG")
    assert (files["/sdcard/DCIM/x.heic"].action, files["/sdcard/DCIM/x.heic"].target) == ("push", "/sdcard/DCIM/x.heic")


def test_taken_alt_identical_is_exists(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, {"DCIM/Camera/IMG (z kopii).JPG": OLD["DCIM/Camera/IMG.JPG"]})
    taken = {"/sdcard/DCIM/Camera/IMG.JPG": "/sdcard/DCIM/Camera/IMG (z kopii).JPG"}
    f = _by_remote(_plan(new, copy, taken_alts=taken))["/sdcard/DCIM/Camera/IMG.JPG"]
    assert (f.action, f.target) == ("exists", "/sdcard/DCIM/Camera/IMG (z kopii).JPG")


def test_denied_folder_pushes_to_original_without_alt_search(tmp_path):
    """`stat` odmówiony (FUSE) = zapis też odmówiony: `push` pod oryginalną ścieżkę, bez nazw zastępczych."""
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    new.deny_stat_prefixes = {"/sdcard/DCIM/Camera/"}
    files = _by_remote(_plan(new, copy))
    for remote in ("/sdcard/DCIM/Camera/IMG.JPG", "/sdcard/DCIM/Camera/VID.MP4"):
        assert (files[remote].action, files[remote].target) == ("push", remote)
    assert not any("z kopii" in c for c in new.commands)


def test_candidate_timeout_raises_never_guesses(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, {"DCIM/Camera/IMG.JPG": b"other", "DCIM/Camera/IMG (z kopii).JPG": b"theirs"})
    candidate = q("/sdcard/DCIM/Camera/IMG (z kopii).JPG")
    tries: list[str] = []

    def slow(command: str) -> None:
        if command.startswith("stat ") and candidate in command:
            tries.append(command)
            raise AdbError("timeout", "stat (>120s)")

    new.on_shell = slow
    with pytest.raises(AdbError) as exc:
        _plan(new, copy)
    assert exc.value.kind == "timeout" and len(tries) == 2  # jedna powtórka paczki


def test_timeout_once_is_retried(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    fired: list[str] = []

    def once(command: str) -> None:
        if command.startswith("stat ") and not fired:
            fired.append(command)
            raise AdbError("timeout", "stat (>120s)")

    new.on_shell = once
    assert {f.action for f in _plan(new, copy).files} == {"push"}


def test_empty_phone_stat_is_batched(tmp_path):
    many = {f"DCIM/Camera/IMG_20261025_120000_{i:04d}_long_name_for_batching.jpg": b"x" for i in range(1200)}
    copy = _copy(tmp_path, many)
    new = _new(tmp_path)
    plan = _plan(new, copy)
    assert {f.action for f in plan.files} == {"push"}
    stats = [c for c in new.commands if c.startswith("stat ")]
    assert len(stats) == len(_cmd_batches(["/sdcard/" + r for r in many])) > 1
    assert all(c.endswith(STAT_TAIL) for c in stats)


def test_stat_batches_fit_the_windows_command_line(tmp_path):
    """`adb shell <polecenie>` idzie przez CreateProcess: cała linia ≤ 32 767 jednostek UTF-16
    (emoji = 2), a list2cmdline dokleja cudzysłowy i ukośniki. Próba na OPPO: 1279 ścieżek
    w jednej paczce = 48 049 znaków → WinError 206."""
    many = {f"DCIM/AdMeNotTest/Ą B/'$x' zażółć 😀 {i:04d} — długa nazwa pliku.jpg": b"x" for i in range(1500)}
    copy = _copy(tmp_path, many)
    new = _new(tmp_path)
    _plan(new, copy)
    adb_path = r"C:\Program Files\AdMeNot\assets\tools\scrcpy\adb.exe"
    for c in (c for c in new.commands if c.startswith("stat ")):
        line = subprocess.list2cmdline([adb_path, "-s", "TESTSERIAL000001", "shell", c])
        assert len(line.encode("utf-16-le")) // 2 < 32_767


def test_missing_local_files_left_out(tmp_path, monkeypatch):
    _apks(monkeypatch, {"/sdcard/Download/evil.apk": ("malicious", False),
                        "/sdcard/Download/odd.apk": ("suspicious", False),
                        "/sdcard/Download/ok.APK": ("clean", True),
                        "/sdcard/DCIM/bundle.xapk": ("unknown", True)})
    copy = _copy(tmp_path, APK_FILES)
    (copy.files_dir / "Download" / "ok.APK").unlink()  # np. kwarantanna antywirusa
    (copy.files_dir / "DCIM" / "x.heic").unlink()
    (copy.files_dir / "DCIM" / "plik").write_bytes(b"short")  # inny rozmiar niż w stanie
    plan = _plan(_new(tmp_path), copy)
    assert plan.missing == 3
    assert plan.missing_by_group == {"downloads": 1, "photos": 2}
    assert plan.missing_in({"photos", "videos"}) == 2
    assert not {"/sdcard/Download/ok.APK", "/sdcard/DCIM/x.heic", "/sdcard/DCIM/plik"} & set(_by_remote(plan))


def test_missing_apk_with_real_check(tmp_path):
    copy = _copy(tmp_path, {**OLD, "Download/gone.apk": b"G" * 10})
    (copy.files_dir / "Download" / "gone.apk").unlink()
    (copy.files_dir / "DCIM" / "x.heic").unlink()
    plan = _plan(_new(tmp_path), copy)
    assert plan.missing == 2
    assert plan.missing_by_group == {"downloads": 1, "photos": 1}
    assert {"/sdcard/Download/gone.apk", "/sdcard/DCIM/x.heic"}.isdisjoint(_by_remote(plan))


def test_whatsapp_and_other_groups(tmp_path):
    files = {**OLD, "WhatsApp/Media/w.jpg": b"W" * 7, "Music/song.mp3": b"M" * 9}
    plan = _plan(_new(tmp_path), _copy(tmp_path, files, others={"Music"}, extra=("whatsapp",)))
    got = _by_remote(plan)
    assert got["/sdcard/WhatsApp/Media/w.jpg"].group == "whatsapp"
    assert got["/sdcard/Music/song.mp3"].group == "other:Music"
    assert plan.groups["other:Music"] == GroupTotals(files=1, bytes=9, exists=0, rename=0)


def test_alt_name_shapes():
    assert alt_name("/sdcard/DCIM/a.jpg", 1) == "/sdcard/DCIM/a (z kopii).jpg"
    assert alt_name("/sdcard/DCIM/a.jpg", 2) == "/sdcard/DCIM/a (z kopii 2).jpg"
    assert alt_name("/sdcard/x/a.tar.gz", 1) == "/sdcard/x/a.tar (z kopii).gz"
    assert alt_name("/sdcard/x/README", 1) == "/sdcard/x/README (z kopii)"
    assert alt_name("/sdcard/x/.nomedia", 3) == "/sdcard/x/.nomedia (z kopii 3)"
    assert alt_name("/sdcard/x/.foo.txt", 1) == "/sdcard/x/.foo (z kopii).txt"


def test_media_split_photos_videos(tmp_path):
    files = _by_remote(_plan(_new(tmp_path), _copy(tmp_path)))
    assert files["/sdcard/DCIM/Camera/IMG.JPG"].group == "photos"
    assert files["/sdcard/DCIM/Camera/VID.MP4"].group == "videos"
    assert files["/sdcard/DCIM/x.heic"].group == "photos"
    assert files["/sdcard/DCIM/plik"].group == "photos"
    assert files["/sdcard/Download/c.pdf"].group == "downloads"


def test_reserve_and_fits(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    new.total_kb = 64 * GiB // 1024
    groups = {"photos", "videos", "downloads"}
    plan = _plan(new, copy)
    assert plan.space.total == 64 * GiB
    assert plan.reserve == 64 * GiB // 20  # 5% z 64 GiB = 3,2 GiB
    # film 1 GiB (prawdziwy plik tej wielkości byłby za duży na test)
    big = [dataclasses.replace(f, size=GiB) if f.group == "videos" else f for f in plan.files]
    plan = dataclasses.replace(plan, files=big)
    plan = dataclasses.replace(plan, space=PhoneSpace(plan.need(groups, set()) + 3 * GiB, 64 * GiB))
    assert plan.fits(groups, set()) is False
    assert plan.fits(groups - {"videos"}, set()) is True
    assert reserve(PhoneSpace(free=10 * GiB, total=None)) == GiB
    assert reserve(PhoneSpace(free=GiB, total=8 * GiB)) == GiB  # 5% < 1 GiB


def _apks(monkeypatch, outcomes: dict[str, tuple[str, bool]]) -> list[list[tuple[str, Path]]]:
    calls: list[list[tuple[str, Path]]] = []

    def fake(copy, files):
        calls.append(list(files))
        return [ApkCheck(r, None, outcomes[r][0], "ioc", outcomes[r][1]) for r, _ in files]

    monkeypatch.setattr(rp, "load_or_check", fake)
    return calls


APK_FILES = {**OLD, "Download/evil.apk": b"E" * 1000, "Download/odd.apk": b"S" * 2000,
             "Download/ok.APK": b"K" * 4000, "DCIM/bundle.xapk": b"X" * 8}


def test_malicious_apk_never_counted(tmp_path, monkeypatch):
    calls = _apks(monkeypatch, {"/sdcard/Download/evil.apk": ("malicious", False),
                                "/sdcard/Download/odd.apk": ("suspicious", False),
                                "/sdcard/Download/ok.APK": ("clean", True),
                                "/sdcard/DCIM/bundle.xapk": ("unknown", True)})
    copy = _copy(tmp_path, APK_FILES)
    plan = _plan(_new(tmp_path), copy)
    checked = {r: loc for r, loc in calls[0]}
    assert set(checked) == {"/sdcard/Download/evil.apk", "/sdcard/Download/odd.apk",
                            "/sdcard/Download/ok.APK", "/sdcard/DCIM/bundle.xapk"}
    files = _by_remote(plan)
    assert all(checked[r] == files[r].local for r in checked)
    assert files["/sdcard/Download/evil.apk"].apk.outcome == "malicious"
    assert files["/sdcard/Download/c.pdf"].apk is None
    base = plan.need({"downloads"}, set())
    assert base == 54 + 4000
    assert plan.need({"downloads"}, {"/sdcard/Download/evil.apk"}) == base
    assert plan.need({"photos"}, set()) == 300 + 20 + 10 + 8  # paczka „nie do oceny” idzie normalnie


def test_suspicious_apk_counted_only_when_on(tmp_path, monkeypatch):
    _apks(monkeypatch, {"/sdcard/Download/evil.apk": ("malicious", False),
                        "/sdcard/Download/odd.apk": ("suspicious", False),
                        "/sdcard/Download/ok.APK": ("clean", True),
                        "/sdcard/DCIM/bundle.xapk": ("unknown", True)})
    plan = _plan(_new(tmp_path), _copy(tmp_path, APK_FILES))
    assert plan.need({"downloads"}, {"/sdcard/Download/odd.apk"}) == 54 + 4000 + 2000
    assert plan.groups["downloads"].bytes == 54 + 4000  # domyślny wybór APK


def test_plan_odd_names(tmp_path):
    odd = {"DCIM/it's.jpg": b"1" * 11, "DCIM/$x.jpg": b"2" * 12, "DCIM/zażółć gęślą.jpg": b"3" * 13}
    copy = _copy(tmp_path, odd)
    new = _new(tmp_path, odd)
    plan = _plan(new, copy)
    assert {f.remote: f.action for f in plan.files} == {"/sdcard/" + r: "exists" for r in odd}
    stats = [c for c in new.commands if c.startswith("stat ")]
    for rel in odd:
        assert any(q("/sdcard/" + rel) in c for c in stats)


@pytest.mark.parametrize("unquoted", [False, True])
def test_stat_error_lines_quoted_and_unquoted(tmp_path, unquoted):
    """toybox: `stat: '<ścieżka>': …`; inne wersje bez cudzysłowów — obie dają ten sam plan."""
    copy = _copy(tmp_path)
    new = _new(tmp_path, {"DCIM/Camera/IMG.JPG": b"theirs"})
    new.stat_unquoted = unquoted
    new.deny_stat_prefixes = {"/sdcard/Download/"}
    files = _by_remote(_plan(new, copy))
    img = files["/sdcard/DCIM/Camera/IMG.JPG"]
    assert (img.action, img.target) == ("rename", "/sdcard/DCIM/Camera/IMG (z kopii).JPG")
    assert files["/sdcard/DCIM/x.heic"].action == "push"
    assert files["/sdcard/Download/c.pdf"].action == "push"  # `denied` → bez szukania nazwy


class _CannedStat:
    """Telefon, który na `stat` odpowiada gotowym tekstem (nazwy z `:` nie istnieją na NTFS)."""

    def __init__(self, out: str) -> None:
        self.out = out

    def shell(self, command: str, timeout: float = 20.0) -> str:
        return self.out


def test_stat_unquoted_name_with_colon_space_longest_match():
    a, b = "/sdcard/DCIM/a", "/sdcard/DCIM/a: b.jpg"
    out = (f"stat: {b}: No such file or directory\n"
           f"stat: {a}: Permission denied\n"
           f"stat: '/sdcard/x: y': No such file or directory\n")
    answers = rp.stat_all(_CannedStat(out), [a, b, "/sdcard/x: y"], lambda: False)
    assert answers == {a: "denied", b: "gone", "/sdcard/x: y": "gone"}


def test_stat_unknown_path_in_error_line_never_guessed():
    """Linia o ścieżce, o którą nie pytaliśmy, nie odpowiada za żadną z pytanych → plan przerwany."""
    out = "stat: /sdcard/DCIM/inna.jpg: No such file or directory\n"
    with pytest.raises(AdbError):
        rp.stat_all(_CannedStat(out), ["/sdcard/DCIM/a.jpg"], lambda: False)


def test_stop_requested(tmp_path):
    copy = _copy(tmp_path)
    with pytest.raises(Stopped):
        build_plan(AppendOnlyAdb(_new(tmp_path)), copy, lambda: True)


class _DfAdb:
    def __init__(self, out: str) -> None:
        self.out = out
        self.commands: list[str] = []

    def shell(self, command: str, timeout: float = 20.0) -> str:
        self.commands.append(command)
        return self.out


def test_read_space_columns():
    adb = _DfAdb("Filesystem 1K-blocks Used Available Use% Mounted on\n"
                 "/dev/fuse 1000 400 600 40% /storage/emulated\n")
    assert read_space(adb) == PhoneSpace(free=600 * 1024, total=1000 * 1024)
    assert adb.commands == ["df -k /sdcard/"]


def test_read_space_total_unknown():
    adb = _DfAdb("Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/fuse - - 600 - /x\n")
    assert read_space(adb) == PhoneSpace(free=600 * 1024, total=None)


def test_read_space_unreadable_raises():
    with pytest.raises(AdbError):
        read_space(_DfAdb("df: /sdcard/: Permission denied\n"))


def test_plan_is_frozen(tmp_path):
    f = _plan(_new(tmp_path), _copy(tmp_path)).files[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.target = "/sdcard/x"  # type: ignore[misc]
