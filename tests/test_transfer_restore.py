from __future__ import annotations

import dataclasses
import os
import shutil
import threading
from pathlib import Path

import pytest
from faketransfer import FakeStoragePhone
from test_transfer_restore_plan import APK_FILES, MTIME, OLD, _apks, _copy, _device, _new

from admenot.engine.adb.transport import AdbError
from admenot.engine.device.info import DeviceInfo
from admenot.engine.paths import device_dir_name
from admenot.engine.transfer import restore as rs
from admenot.engine.transfer import store
from admenot.engine.transfer.guard import AppendOnlyAdb
from admenot.engine.transfer.restore import RestoreError, RestoreResult, UploadChoice, run_restore
from admenot.engine.transfer.restore_plan import UPLOAD_GROUPS, RestorePlan, build_plan
from admenot.engine.transfer.restore_state import RestoreRow, RestoreState, restore_state_path

GiB = 1024 ** 3
ALL = frozenset(UPLOAD_GROUPS)


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))


def _target(sdk: int = 30) -> DeviceInfo:
    return dataclasses.replace(_device(), serial="NEW", sdk=sdk)


def _plan(new: FakeStoragePhone, copy: store.CopyDir, taken: bool = False) -> RestorePlan:
    alts = None
    if taken:
        state = RestoreState(restore_state_path(copy, "NEW"))
        alts = state.taken_alts()
        state.close()
    return build_plan(AppendOnlyAdb(new), copy, lambda: False, taken_alts=alts)


def _run(new: FakeStoragePhone, copy: store.CopyDir, plan: RestorePlan, choice: UploadChoice | None = None,
         *, device: DeviceInfo | None = None, should_stop=lambda: False, wait_device=None,
         streams: int = rs.STREAMS) -> RestoreResult:
    return run_restore(AppendOnlyAdb(new), new, device or _target(), copy, plan,
                       choice or UploadChoice(ALL, frozenset()), on_progress=lambda p: None,
                       should_stop=should_stop, wait_device=wait_device or new.reconnect, streams=streams)


def _rows(copy: store.CopyDir) -> dict[str, RestoreRow]:
    state = RestoreState(restore_state_path(copy, "NEW"))
    try:
        return state.all_files()
    finally:
        state.close()


def _meta(copy: store.CopyDir, key: str):
    state = RestoreState(restore_state_path(copy, "NEW"))
    try:
        return state.get_meta(key)
    finally:
        state.close()


def _phone_files(new: FakeStoragePhone) -> dict[str, bytes]:
    base = new.root / "sdcard"
    return {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob("*") if p.is_file()}


def _assert_uploaded(new: FakeStoragePhone, files: dict[str, bytes]) -> None:
    for rel, data in files.items():
        path = new.local("/sdcard/" + rel)
        assert path.read_bytes() == data, rel
        assert int(path.stat().st_mtime) == MTIME, rel


MANY = {f"DCIM/d{d}/f{i}.jpg": bytes([65 + d]) * (100 + i) for d in range(4) for i in range(3)}


def test_upload_all_complete(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    res = _run(new, copy, _plan(new, copy))
    _assert_uploaded(new, OLD)
    assert new.scans == 1
    assert res.status == "complete"
    assert (res.files_done, res.files_exists, res.files_renamed, res.files_failed, res.files_missing) == (5, 0, 0, 0, 0)
    assert res.bytes == sum(len(d) for d in OLD.values())
    assert (res.target_serial, res.media_scan, res.hashed) == ("NEW", "done", False)
    assert restore_state_path(copy, "NEW") == copy.path / "restore" / f"{device_dir_name('NEW')}.sqlite"
    assert _meta(copy, "serial") == "NEW"
    assert _meta(copy, "status") == "complete"
    assert _meta(copy, "updated").endswith("+00:00")
    assert UploadChoice.from_json(_meta(copy, "choice")) == UploadChoice(ALL, frozenset())


def test_unquoted_stat_errors_plan_and_verify(tmp_path):
    """Telefon bez toyboxowych cudzysłowów w błędach `stat`: plan i sprawdzenie po `push` działają."""
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    new.stat_unquoted = True
    res = _run(new, copy, _plan(new, copy))
    _assert_uploaded(new, OLD)
    assert (res.status, res.files_done) == ("complete", 5)


def test_existing_identical_not_pushed(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, {"DCIM/Camera/IMG.JPG": OLD["DCIM/Camera/IMG.JPG"]})
    res = _run(new, copy, _plan(new, copy))
    assert "/sdcard/DCIM/Camera/IMG.JPG" not in new.pushed
    assert len(new.pushed) == 4
    assert (res.status, res.files_done, res.files_exists) == ("complete", 4, 1)
    assert _rows(copy)["/sdcard/DCIM/Camera/IMG.JPG"].status == "exists"


def test_conflict_saved_beside(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, {"DCIM/Camera/IMG.JPG": b"theirs, not ours"})
    res = _run(new, copy, _plan(new, copy))
    assert new.local("/sdcard/DCIM/Camera/IMG.JPG").read_bytes() == b"theirs, not ours"
    assert new.local("/sdcard/DCIM/Camera/IMG (z kopii).JPG").read_bytes() == OLD["DCIM/Camera/IMG.JPG"]
    assert (res.status, res.files_done, res.files_renamed) == ("complete", 5, 1)


def _appear(new: FakeStoragePhone, rel: str, data: bytes, mtime: int = MTIME) -> None:
    """Plik, który pojawił się na telefonie po zbudowaniu planu (np. odtwarzanie WhatsAppa)."""
    path = new.local("/sdcard/" + rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))


def test_foreign_file_after_plan_saved_beside(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, {"DCIM/Camera/IMG (z kopii).JPG": b"older theirs"})
    plan = _plan(new, copy)
    assert next(f for f in plan.files if f.remote == "/sdcard/DCIM/Camera/IMG.JPG").action == "push"
    _appear(new, "DCIM/Camera/IMG.JPG", b"theirs, written meanwhile")
    res = _run(new, copy, plan)
    assert new.local("/sdcard/DCIM/Camera/IMG.JPG").read_bytes() == b"theirs, written meanwhile"
    assert new.local("/sdcard/DCIM/Camera/IMG (z kopii).JPG").read_bytes() == b"older theirs"
    assert new.local("/sdcard/DCIM/Camera/IMG (z kopii 2).JPG").read_bytes() == OLD["DCIM/Camera/IMG.JPG"]
    assert "/sdcard/DCIM/Camera/IMG.JPG" not in new.pushed
    assert (res.status, res.files_done, res.files_renamed) == ("complete", 5, 1)
    assert _rows(copy)["/sdcard/DCIM/Camera/IMG.JPG"].target == "/sdcard/DCIM/Camera/IMG (z kopii 2).JPG"


def test_identical_file_after_plan_not_pushed(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    plan = _plan(new, copy)
    _appear(new, "DCIM/Camera/VID.MP4", OLD["DCIM/Camera/VID.MP4"], MTIME + 2)
    res = _run(new, copy, plan)
    assert "/sdcard/DCIM/Camera/VID.MP4" not in new.pushed
    assert (res.status, res.files_done, res.files_exists) == ("complete", 4, 1)
    assert _rows(copy)["/sdcard/DCIM/Camera/VID.MP4"].status == "exists"


def test_recheck_one_stat_per_chunk(tmp_path):
    """Przed każdą paczką jeden `stat` celów, po niej jeden (sprawdzenie rozmiaru) — nic więcej."""
    copy = _copy(tmp_path, MANY)
    new = _new(tmp_path)
    plan = _plan(new, copy)
    new.commands.clear()
    _run(new, copy, plan)
    stats = [c for c in new.commands if c.startswith("stat ")]
    assert new.push_calls == 4 and len(stats) == 2 * new.push_calls


def test_own_partial_not_rechecked(tmp_path):
    """Własny niedokończony plik pod celem nie jest „cudzy” — nadpisany, bez `stat` przed `push`."""
    copy = _copy(tmp_path)
    remote = "/sdcard/DCIM/Camera/VID.MP4"
    new = _new(tmp_path, {"DCIM/Camera/VID.MP4": OLD["DCIM/Camera/VID.MP4"][:250]})
    state = RestoreState(restore_state_path(copy, "NEW"))
    state.set_meta("serial", "NEW")
    state.insert(RestoreRow(remote, remote, "videos", 500, MTIME, "pushing", 0, None))
    state.close()
    plan = _plan(new, copy, taken=True)
    new.commands.clear()
    res = _run(new, copy, plan)
    assert res.status == "complete"
    _assert_uploaded(new, OLD)
    stats = [c for c in new.commands if c.startswith("stat ")]
    assert sum(1 for c in stats if "VID.MP4" in c) == 1  # tylko sprawdzenie po `push`


def test_resume_after_stop_no_duplicates(tmp_path):
    copy = _copy(tmp_path, MANY)
    new = _new(tmp_path)
    first = _run(new, copy, _plan(new, copy), should_stop=lambda: new.push_calls >= 1)
    assert (first.status, first.media_scan) == ("stopped", "skipped")
    assert _meta(copy, "status") == "stopped"
    assert new.scans == 0
    before = set(new.pushed)
    assert 0 < len(before) < len(MANY)
    second = _run(new, copy, _plan(new, copy, taken=True))
    assert second.status == "complete"
    assert second.files_done == len(MANY)
    assert not any("z kopii" in rel for rel in _phone_files(new))
    _assert_uploaded(new, MANY)
    assert before.isdisjoint(new.pushed[len(before):])  # wgrane w pierwszym podejściu nie poszły drugi raz


def test_own_partial_file_overwritten(tmp_path):
    copy = _copy(tmp_path)
    remote = "/sdcard/DCIM/Camera/VID.MP4"
    new = _new(tmp_path, {"DCIM/Camera/VID.MP4": OLD["DCIM/Camera/VID.MP4"][:250]})
    state = RestoreState(restore_state_path(copy, "NEW"))
    state.set_meta("serial", "NEW")
    state.insert(RestoreRow(remote, remote, "videos", 500, MTIME, "pushing", 0, None))
    state.close()
    res = _run(new, copy, _plan(new, copy, taken=True))
    assert res.status == "complete"
    _assert_uploaded(new, OLD)
    assert not any("z kopii" in rel for rel in _phone_files(new))
    assert _rows(copy)[remote].target == remote


def test_own_file_found_complete_counts_as_done(tmp_path):
    """Nasz plik (`pushing`) wgrany w całości przed przerwaniem: plan widzi „już jest”, raport — wgrany."""
    copy = _copy(tmp_path)
    remote = "/sdcard/DCIM/Camera/VID.MP4"
    new = _new(tmp_path, {"DCIM/Camera/VID.MP4": OLD["DCIM/Camera/VID.MP4"]})
    state = RestoreState(restore_state_path(copy, "NEW"))
    state.set_meta("serial", "NEW")
    state.insert(RestoreRow(remote, remote, "videos", 500, MTIME, "pushing", 0, None))
    state.close()
    plan = _plan(new, copy, taken=True)
    assert next(f for f in plan.files if f.remote == remote).action == "exists"
    res = _run(new, copy, plan)
    assert remote not in new.pushed
    assert (res.status, res.files_done, res.files_exists) == ("complete", 5, 0)
    assert _rows(copy)[remote].status == "done"


def test_disconnect_during_parallel_push(tmp_path):
    copy = _copy(tmp_path, MANY)
    new = _new(tmp_path)
    new.fail_after_push_files = 3
    waits: list[int] = []

    def wait_device() -> None:
        waits.append(1)
        new.reconnect()
        new.fail_after_push_files = None

    res = _run(new, copy, _plan(new, copy), wait_device=wait_device, streams=4)
    assert len(waits) == 1
    assert res.status == "complete"
    rows = _rows(copy)
    assert all(r.status == "done" and r.attempts == 0 for r in rows.values())
    _assert_uploaded(new, MANY)
    assert not any("z kopii" in rel for rel in _phone_files(new))


def test_phone_full_stops_resumable(tmp_path):
    files = {f"DCIM/{d}/{i}.jpg": d.encode() * 1000 for d in "ABC" for i in range(2)}
    copy = _copy(tmp_path, files)
    new = _new(tmp_path)
    new.total_kb = 8 * GiB // 1024  # zapas = 1 GiB
    plan = _plan(new, copy)
    assert plan.reserve == GiB
    new.free_kb = GiB // 1024 + 3  # mieści się jedna paczka (2 × 1000 B)
    with pytest.raises(RestoreError) as exc:
        _run(new, copy, plan, streams=1)
    assert exc.value.key == "phone_full"
    rows = _rows(copy)
    assert {r for r, row in rows.items() if row.status == "done"} == {"/sdcard/DCIM/A/0.jpg", "/sdcard/DCIM/A/1.jpg"}
    assert all(row.status == "pending" for r, row in rows.items() if "/A/" not in r)
    assert _meta(copy, "status") == "phone_full"
    new.free_kb = None  # serwisant zwolnił miejsce
    assert _run(new, copy, _plan(new, copy, taken=True)).status == "complete"
    _assert_uploaded(new, files)


def test_phone_full_counts_chunks_in_flight(tmp_path, monkeypatch):
    """4 strumienie: `df` nie widzi jeszcze paczki w locie, więc liczymy ją jako zajętą."""
    files = {f"DCIM/{d}/{i}.jpg": d.encode() * 1000 for d in "ABCD" for i in range(2)}
    copy = _copy(tmp_path, files)
    new = _new(tmp_path)
    new.total_kb = 8 * GiB // 1024  # zapas = 1 GiB
    plan = _plan(new, copy)
    new.free_kb = GiB // 1024 + 3  # bez paczki w locie zmieściłaby się każda z osobna
    release = threading.Event()
    push, real_df = new.push, rs.read_space
    dfs: list[int] = []

    def held(locals_, remote, should_stop, tick):
        assert release.wait(10)  # paczka A „w locie”, dopóki nie zapadnie decyzja o paczce B
        return push(locals_, remote, should_stop, tick)

    def df(adb):
        space = real_df(adb)
        dfs.append(space.free)
        if len(dfs) == 2:
            release.set()
        return space

    new.push = held  # type: ignore[method-assign]
    monkeypatch.setattr(rs, "read_space", df)
    with pytest.raises(RestoreError) as exc:
        _run(new, copy, plan, streams=4)
    assert exc.value.key == "phone_full"
    assert dfs == [(GiB // 1024 + 3) * 1024] * 2  # drugi `df` przed zapisem A — zatrzymała paczka w locie
    assert new.push_calls == 1
    rows = _rows(copy)
    assert {r for r, row in rows.items() if row.status == "done"} == {"/sdcard/DCIM/A/0.jpg", "/sdcard/DCIM/A/1.jpg"}
    assert all(row.status == "pending" for r, row in rows.items() if "/A/" not in r)


@pytest.mark.parametrize("folder_exists", [True, False], ids=["push_refused", "mkdir_refused"])
def test_denied_folder_reported_not_failed(tmp_path, folder_exists):
    wa = {"Android/media/com.whatsapp/WhatsApp/Media/w1.jpg": b"1" * 7,
          "Android/media/com.whatsapp/WhatsApp/Media/w2.jpg": b"2" * 8}
    copy = _copy(tmp_path, {**OLD, **wa}, extra=("whatsapp",))
    new = _new(tmp_path)
    if folder_exists:  # folder jest, ale Android nie pozwala zapisać w nim plików
        new.local("/sdcard/Android/media/com.whatsapp/WhatsApp/Media").mkdir(parents=True)
    new.deny_prefixes = {"/sdcard/Android/media/"}
    res = _run(new, copy, _plan(new, copy))
    # odmowa `mkdir -p` → pliki od razu `denied`, bez `push` do tego folderu
    assert new.push_calls == (4 if folder_exists else 3)
    rows = _rows(copy)
    assert {r for r, row in rows.items() if row.status == "denied"} == {"/sdcard/" + k for k in wa}
    assert all(row.attempts == 0 for row in rows.values())
    _assert_uploaded(new, OLD)
    assert (res.status, res.files_denied, res.files_failed, res.files_done) == ("incomplete", 2, 0, 5)
    assert _meta(copy, "status") == "incomplete"


def test_unselected_group_skipped(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    res = _run(new, copy, _plan(new, copy), UploadChoice(ALL - {"videos"}, frozenset()))
    assert not any(rel.lower().endswith(".mp4") for rel in _phone_files(new))
    assert (res.status, res.files_unselected, res.files_done) == ("complete", 1, 4)
    row = _rows(copy)["/sdcard/DCIM/Camera/VID.MP4"]
    assert (row.status, row.error) == ("skipped", "unselected")


def test_missing_counted_only_in_selected_groups(tmp_path):
    """Plik zniknął z PC w grupie, której nie wgrywamy → wynik nie jest żółty z tego powodu."""
    copy = _copy(tmp_path)
    (copy.files_dir / "DCIM" / "Camera" / "VID.MP4").unlink()
    new = _new(tmp_path)
    plan = _plan(new, copy)
    assert plan.missing == 1
    res = _run(new, copy, plan, UploadChoice(ALL - {"videos"}, frozenset()))
    assert (res.status, res.files_missing) == ("complete", 0)
    res = _run(new, copy, plan)
    assert (res.status, res.files_missing) == ("complete", 1)


def test_own_partial_kept_own_while_group_unticked(tmp_path):
    """Przerwany w połowie pliku, wznowiony z odznaczoną grupą, potem z zaznaczoną: nadpisany ten sam
    plik (nasz), bez „(z kopii)”."""
    copy = _copy(tmp_path)
    remote = "/sdcard/DCIM/Camera/VID.MP4"
    new = _new(tmp_path, {"DCIM/Camera/VID.MP4": OLD["DCIM/Camera/VID.MP4"][:250]})
    state = RestoreState(restore_state_path(copy, "NEW"))
    state.set_meta("serial", "NEW")
    state.insert(RestoreRow(remote, remote, "videos", 500, MTIME, "pushing", 0, None))
    state.close()
    first = _run(new, copy, _plan(new, copy, taken=True), UploadChoice(ALL - {"videos"}, frozenset()))
    assert (first.status, first.files_unselected) == ("complete", 1)
    row = _rows(copy)[remote]
    assert (row.status, row.error, row.own) == ("skipped", "unselected", True)
    second = _run(new, copy, _plan(new, copy, taken=True))
    assert second.status == "complete"
    _assert_uploaded(new, OLD)
    assert not any("z kopii" in rel for rel in _phone_files(new))
    assert _rows(copy)[remote].target == remote


def test_restore_state_without_own_column_migrated(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE files (remote TEXT PRIMARY KEY, target TEXT NOT NULL, grp TEXT NOT NULL, "
                     "size INTEGER NOT NULL, mtime INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', "
                     "attempts INTEGER NOT NULL DEFAULT 0, error TEXT);"
                     "INSERT INTO files VALUES ('/sdcard/a', '/sdcard/a', 'photos', 1, 2, 'pushing', 0, NULL);")
    db.commit()
    db.close()
    state = RestoreState(path)
    try:
        assert state.all_files()["/sdcard/a"].own is False
        assert state.taken_alts() == {"/sdcard/a": "/sdcard/a"}
    finally:
        state.close()


OUTCOMES = {"/sdcard/Download/evil.apk":("malicious", False), "/sdcard/Download/odd.apk": ("suspicious", False),
            "/sdcard/Download/ok.APK": ("clean", True), "/sdcard/DCIM/bundle.xapk": ("unknown", True)}


def test_malicious_apk_never_pushed_even_if_in_apks_on(tmp_path, monkeypatch):
    _apks(monkeypatch, OUTCOMES)
    copy = _copy(tmp_path, APK_FILES)
    new = _new(tmp_path)
    res = _run(new, copy, _plan(new, copy), UploadChoice(ALL, frozenset({"/sdcard/Download/evil.apk"})))
    phone = _phone_files(new)
    assert "Download/evil.apk" not in phone
    assert {"Download/ok.APK", "DCIM/bundle.xapk"} <= set(phone)
    assert (res.apk_skipped, res.apk_suspicious_skipped, res.status) == (1, 1, "complete")
    assert _rows(copy)["/sdcard/Download/evil.apk"].error == "apk_malicious"


def test_suspicious_apk_pushed_only_when_on(tmp_path, monkeypatch):
    _apks(monkeypatch, OUTCOMES)
    copy = _copy(tmp_path, APK_FILES)
    new = _new(tmp_path)
    plan = _plan(new, copy)
    res = _run(new, copy, plan)
    assert "Download/odd.apk" not in _phone_files(new)
    assert res.apk_suspicious_skipped == 1
    res = _run(new, copy, plan, UploadChoice(ALL, frozenset({"/sdcard/Download/odd.apk"})))
    assert _phone_files(new)["Download/odd.apk"] == APK_FILES["Download/odd.apk"]
    assert (res.apk_suspicious_skipped, res.apk_skipped) == (0, 1)


@pytest.mark.parametrize("sdk", [33, 28])
def test_stopped_skips_media_scan(tmp_path, sdk):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    res = _run(new, copy, _plan(new, copy), device=_target(sdk=sdk), should_stop=lambda: True)
    assert (res.status, res.media_scan, new.scans) == ("stopped", "skipped", 0)


def test_no_file_pushed_skips_media_scan(tmp_path):
    """Kopia tylko telefonii (żadna grupa plików niewybrana): bez skanu galerii (6-9 s na telefonie)."""
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    res = _run(new, copy, _plan(new, copy), UploadChoice(frozenset(), frozenset()))
    assert (res.status, res.files_done, res.media_scan, new.scans) == ("complete", 0, "skipped", 0)


def test_rerun_after_pushed_files_still_scans(tmp_path):
    """Wznowienie, w którym nic nowego nie poszło, ale wcześniej pliki trafiły na telefon: skan zostaje."""
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    _run(new, copy, _plan(new, copy))
    res = _run(new, copy, _plan(new, copy, taken=True))
    assert (res.status, res.media_scan, new.scans) == ("complete", "done", 2)


def test_android9_asks_restart(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    res = _run(new, copy, _plan(new, copy), device=_target(sdk=28))
    assert (new.scans, res.media_scan, res.status) == (0, "restart", "complete")


def test_media_scan_failure_still_complete(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)

    def broken_scan(command: str) -> None:
        if command.startswith("content call"):
            raise AdbError("timeout", "content call (>3600s)")

    new.on_shell = broken_scan
    res = _run(new, copy, _plan(new, copy))
    assert (res.status, res.media_scan) == ("complete", "failed")


def test_wrong_device_refused(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    plan = _plan(new, copy)
    state = RestoreState(restore_state_path(copy, "NEW"))
    state.set_meta("serial", "OTHER")
    state.close()
    with pytest.raises(RestoreError) as exc:
        _run(new, copy, plan)
    assert exc.value.key == "wrong_device"
    assert new.push_calls == 0
    assert _meta(copy, "serial") == "OTHER"


def test_copy_missing(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    plan = _plan(new, copy)
    shutil.rmtree(copy.files_dir)
    with pytest.raises(RestoreError) as exc:
        _run(new, copy, plan)
    assert exc.value.key == "copy_missing"


def test_big_files_one_stream_after_small(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "SMALL_MAX", 100)
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    remotes: list[str] = []
    push = new.push

    def spy(locals_: list[Path], remote: str, should_stop, tick):
        remotes.append(remote)
        return push(locals_, remote, should_stop, tick)

    new.push = spy  # type: ignore[method-assign]
    res = _run(new, copy, _plan(new, copy))
    assert res.status == "complete"
    _assert_uploaded(new, OLD)
    # małe (x.heic, plik, c.pdf) przed dużymi (IMG.JPG 300 B, VID.MP4 500 B — jedna paczka z katalogu)
    assert remotes[-1] == "/sdcard/DCIM/Camera/"
    assert set(remotes[:-1]) == {"/sdcard/DCIM/", "/sdcard/Download/"}


def test_retry_then_error_after_three_attempts(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    plan = _plan(new, copy)
    bad = "/sdcard/Download/c.pdf"
    push = new.push

    def flaky(locals_: list[Path], remote: str, should_stop, tick):
        keep = [p for p in locals_ if p.name != "c.pdf"]
        if len(keep) != len(locals_):
            return rs.PullResult(1, ["adb: error: failed to copy: protocol fault"], False)
        return push(keep, remote, should_stop, tick)

    new.push = flaky  # type: ignore[method-assign]
    res = _run(new, copy, plan)
    row = _rows(copy)[bad]
    assert (row.status, row.attempts) == ("error", 3)
    assert (res.status, res.files_failed, res.files_done) == ("incomplete", 1, 4)


def test_verify_hash(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    res = _run(new, copy, _plan(new, copy), UploadChoice(ALL, frozenset(), verify_hash=True))
    assert (res.status, res.hashed) == ("complete", True)
    assert any(c.startswith("sha256sum ") for c in new.commands)


def test_hash_mismatch_repushed(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    plan = _plan(new, copy)
    target = new.local("/sdcard/DCIM/x.heic")
    push = new.push
    calls = {"n": 0}

    def corrupt_first(locals_: list[Path], remote: str, should_stop, tick):
        res = push(locals_, remote, should_stop, tick)
        if target.exists() and calls["n"] == 0:
            calls["n"] += 1
            st = target.stat()
            target.write_bytes(b"Z" * st.st_size)  # ten sam rozmiar, inna treść
            os.utime(target, (st.st_atime, st.st_mtime))
        return res

    new.push = corrupt_first  # type: ignore[method-assign]
    res = _run(new, copy, plan, UploadChoice(ALL, frozenset(), verify_hash=True), streams=1)
    assert res.status == "complete"
    assert target.read_bytes() == OLD["DCIM/x.heic"]
    assert _rows(copy)["/sdcard/DCIM/x.heic"].attempts == 1


def test_read_restores_summarizes_each_target_phone(tmp_path):
    from admenot.engine.transfer.restore_state import read_restores

    copy = _copy(tmp_path, MANY)
    assert read_restores(copy) == []
    new = _new(tmp_path)
    _run(new, copy, _plan(new, copy), should_stop=lambda: new.push_calls >= 1)
    (stopped,) = read_restores(copy)
    assert (stopped.serial, stopped.status, stopped.resumable) == ("NEW", "stopped", True)
    assert stopped.updated == _meta(copy, "updated")
    _run(new, copy, _plan(new, copy, taken=True))
    (done,) = read_restores(copy)
    assert (done.status, done.resumable) == ("complete", False)
    (copy.path / "restore" / "broken.sqlite").write_bytes(b"not a database")
    assert [r.serial for r in read_restores(copy)] == ["NEW"]  # nieczytelny stan pomijany
    assert {p.name for p in (copy.path / "restore").iterdir()} == {
        "broken.sqlite", f"{device_dir_name('NEW')}.sqlite"}  # odczyt niczego nie zakłada


def test_loose_file_in_storage_root_uploaded(tmp_path):
    """Luźny plik w głównym folderze („Inne”: `other:`): katalog docelowy `/sdcard` już jest — bez
    `mkdir -p /sdcard`, którego strażnik i tak by nie przepuścił."""
    copy = _copy(tmp_path, {**OLD, "notes.txt": b"loose"}, others={""})
    new = _new(tmp_path)
    res = _run(new, copy, _plan(new, copy), UploadChoice(ALL | {"other:"}, frozenset()))
    assert res.status == "complete" and res.files_done == len(OLD) + 1
    assert new.local("/sdcard/notes.txt").read_bytes() == b"loose"


def test_read_restores_skips_locked_state_quickly(tmp_path):
    """Stan zablokowany zapisem trwającego wgrywania: widok kopii nie czeka dłużej niż `READ_TIMEOUT`."""
    import sqlite3
    import time

    from admenot.engine.transfer.restore_state import READ_TIMEOUT, read_restores

    copy = _copy(tmp_path)
    new = _new(tmp_path)
    _run(new, copy, _plan(new, copy), should_stop=lambda: new.push_calls >= 1)
    writer = sqlite3.connect(restore_state_path(copy, "NEW"), isolation_level=None)
    try:
        writer.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        assert read_restores(copy) == []
        assert time.monotonic() - started < READ_TIMEOUT + 1.0
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert [r.serial for r in read_restores(copy)] == ["NEW"]


def test_files_complete_with_tel_still_to_run_is_resumable(tmp_path):
    """Program zamknięty między plikami a telefonią: pliki `complete`, ale wybrana telefonia ma rekordy
    (`tel_left`) — Banner wznowienia zostaje. Bez telefonii w wyborze stary `tel_left` się nie liczy."""
    from admenot.engine.transfer.restore_state import read_restores

    copy = _copy(tmp_path)
    state = RestoreState(restore_state_path(copy, "NEW"))
    try:
        state.set_meta("serial", "NEW")
        state.set_meta("status", "complete")
        state.set_meta("tel_left", 3)
        state.set_meta("choice", UploadChoice(ALL, frozenset(), tel=frozenset({"sms"})).to_json())
    finally:
        state.close()
    (entry,) = read_restores(copy)
    assert (entry.status, entry.resumable) == ("complete", True)
    state = RestoreState(restore_state_path(copy, "NEW"))
    try:
        state.set_meta("choice", UploadChoice(ALL, frozenset()).to_json())
    finally:
        state.close()
    (entry,) = read_restores(copy)
    assert entry.resumable is False


# ---- settle_finished: wznowienie, w którym nie ma już nic do zrobienia (T10-M1…M5, U6) ----------------
def _no_tel(contacts: int = 0):
    from admenot.engine.transfer.telplan import ContactSelection, TelPlan
    from admenot.engine.transfer.telrecords import ContactRecord, TelSources

    write = [ContactRecord(f"c{i}", f"Osoba {i}", False, (), ()) for i in range(contacts)]
    return TelPlan(TelSources("vcf" if contacts else None, None, None, None),
                   ContactSelection(write, {}, 0) if contacts else None, [], [], [], {}, False, {}, None)


def _interrupted(copy: store.CopyDir, rows: list[RestoreRow], *, choice: UploadChoice | None = None,
                 status: str = "stopped", **meta) -> None:
    """Stan przerwanego wgrywania na `NEW`: wiersze plików, wybór i meta jak po zamkniętym programie."""
    state = RestoreState(restore_state_path(copy, "NEW"))
    try:
        state.set_meta("serial", "NEW")
        state.set_meta("status", status)
        if choice is not None:
            state.set_meta("choice", choice.to_json())
        for key, value in meta.items():
            state.set_meta(key, value)
        for r in rows:
            state.insert(r)
        state.commit()
    finally:
        state.close()


def _row(remote: str, status: str, error: str | None = None, *, target: str | None = None, size: int = 1,
         grp: str = "photos") -> RestoreRow:
    return RestoreRow(remote, target or remote, grp, size, MTIME, status, 0, error)


def _settle(new: FakeStoragePhone, copy: store.CopyDir, tel=None, sdk: int = 30) -> bool:
    return rs.settle_finished(copy, "NEW", _plan(new, copy), tel or _no_tel(), AppendOnlyAdb(new), sdk)


def test_settle_rows_like_reconcile_and_scans_the_gallery(tmp_path):
    """Plan widzi wszystko jako „już jest”: nasz plik (`pushing`, `pending` po przerwanej próbie) → `done`,
    cudzy (`pending` bez śladu naszego pliku) → `exists`; pliki `done` bez skanu po nich → skan galerii."""
    copy = _copy(tmp_path)
    new = _new(tmp_path, OLD)
    _interrupted(copy, [
        _row("/sdcard/DCIM/Camera/IMG.JPG", "done"),
        _row("/sdcard/DCIM/Camera/VID.MP4", "pushing"),
        _row("/sdcard/DCIM/x.heic", "pending", "interrupted"),
        _row("/sdcard/DCIM/plik", "pending"),
        _row("/sdcard/Download/c.pdf", "pending")], choice=UploadChoice(ALL, frozenset()))
    assert _settle(new, copy) is True
    rows = _rows(copy)
    assert {r: rows[r].status for r in rows} == {
        "/sdcard/DCIM/Camera/IMG.JPG": "done", "/sdcard/DCIM/Camera/VID.MP4": "done",
        "/sdcard/DCIM/x.heic": "done", "/sdcard/DCIM/plik": "exists", "/sdcard/Download/c.pdf": "exists"}
    assert new.scans == 1 and _meta(copy, rs.SCANNED) == 3
    assert _meta(copy, "status") == "complete" and _meta(copy, "tel_left") == 0


def test_settle_skips_scan_when_one_ran_after_the_done_files(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, OLD)
    _interrupted(copy, [_row("/sdcard/DCIM/Camera/IMG.JPG", "done"), _row("/sdcard/DCIM/plik", "pending")],
                 choice=UploadChoice(ALL, frozenset()), scanned=1)
    assert _settle(new, copy) is True
    assert new.scans == 0


def test_settle_on_old_android_does_not_scan(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, OLD)
    _interrupted(copy, [_row("/sdcard/DCIM/Camera/VID.MP4", "pushing")], choice=UploadChoice(ALL, frozenset()))
    assert _settle(new, copy, sdk=28) is True
    assert new.scans == 0 and _meta(copy, rs.SCANNED) is None


def test_run_restore_records_the_scan(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path)
    assert _run(new, copy, _plan(new, copy)).media_scan == "done"
    assert _meta(copy, rs.SCANNED) == 5


def test_settle_denied_or_error_rows_close_incomplete(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, OLD)
    _interrupted(copy, [_row("/sdcard/DCIM/plik", "denied", "denied"),
                        _row("/sdcard/DCIM/x.heic", "error", "push_failed"),
                        _row("/sdcard/Download/c.pdf", "pending")], choice=UploadChoice(ALL, frozenset()))
    assert _settle(new, copy) is True
    assert _meta(copy, "status") == "incomplete"


def test_settle_without_saved_choice_falls_back_to_every_group(tmp_path):
    """Stan bez zapisanego wyboru (program zamknięty przed jego zapisem): liczy się każda grupa planu, więc
    plik, którego telefon nie ma, zostawia stan do wznowienia."""
    copy = _copy(tmp_path)
    new = _new(tmp_path, {k: v for k, v in OLD.items() if k != "Download/c.pdf"})
    _interrupted(copy, [_row("/sdcard/DCIM/plik", "pending")])
    assert _settle(new, copy) is False
    assert _rows(copy)["/sdcard/DCIM/plik"].status == "pending"
    new_all = _new(tmp_path / "b", OLD)
    copy_all = _copy(tmp_path / "b")
    _interrupted(copy_all, [_row("/sdcard/DCIM/plik", "pending")])
    assert _settle(new_all, copy_all) is True


def test_settle_unselected_groups_and_apks_are_skipped_with_their_reason(tmp_path, monkeypatch):
    _apks(monkeypatch, {"/sdcard/Download/evil.apk": ("malicious", False),
                        "/sdcard/Download/odd.apk": ("suspicious", False),
                        "/sdcard/Download/ok.APK": ("clean", True),
                        "/sdcard/DCIM/bundle.xapk": ("unknown", True)})
    copy = _copy(tmp_path, APK_FILES)
    on_phone = {k: v for k, v in APK_FILES.items() if k not in ("Download/evil.apk", "Download/odd.apk",
                                                                  "DCIM/Camera/VID.MP4")}
    new = _new(tmp_path, on_phone)
    plan = _plan(new, copy)
    video = next(f for f in plan.files if f.remote == "/sdcard/DCIM/Camera/VID.MP4")
    groups = frozenset(UPLOAD_GROUPS) - {video.group}
    _interrupted(copy, [_row("/sdcard/Download/evil.apk", "pending", grp="downloads"),
                        _row("/sdcard/Download/odd.apk", "pushing", grp="downloads"),
                        _row("/sdcard/DCIM/Camera/VID.MP4", "pending", grp=video.group)],
                 choice=UploadChoice(groups, frozenset()))
    assert _settle(new, copy) is True
    rows = _rows(copy)
    assert (rows["/sdcard/Download/evil.apk"].status, rows["/sdcard/Download/evil.apk"].error) == (
        "skipped", "apk_malicious")
    odd = rows["/sdcard/Download/odd.apk"]
    assert (odd.status, odd.error, odd.own) == ("skipped", "apk_suspicious", True)  # pod celem nasz plik
    vid = rows["/sdcard/DCIM/Camera/VID.MP4"]
    assert (vid.status, vid.error, vid.own) == ("skipped", "unselected", False)


def test_settle_row_whose_file_left_the_copy_keeps_its_own_mark(tmp_path):
    """T10-M2: `pushing` pliku, którego nie ma już w kopii → `skipped`/`missing` z `own` (jak `_reconcile`),
    żeby nasz niedokończony plik pod celem nie został uznany za cudzy."""
    copy = _copy(tmp_path)
    new = _new(tmp_path, OLD)
    _interrupted(copy, [_row("/sdcard/DCIM/gone.jpg", "pushing"), _row("/sdcard/DCIM/old.jpg", "pending")],
                 choice=UploadChoice(ALL, frozenset()))
    assert _settle(new, copy) is True
    rows = _rows(copy)
    assert (rows["/sdcard/DCIM/gone.jpg"].status, rows["/sdcard/DCIM/gone.jpg"].error,
            rows["/sdcard/DCIM/gone.jpg"].own) == ("skipped", "missing", True)
    assert (rows["/sdcard/DCIM/old.jpg"].status, rows["/sdcard/DCIM/old.jpg"].own) == ("skipped", False)


def test_settle_keeps_state_while_contacts_are_still_missing(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, OLD)
    _interrupted(copy, [_row("/sdcard/DCIM/plik", "pending")],
                 choice=UploadChoice(ALL, frozenset(), tel=frozenset({"contacts"})), tel_left=2)
    assert _settle(new, copy, tel=_no_tel(contacts=2)) is False
    assert _meta(copy, "tel_left") == 2 and _meta(copy, "status") == "stopped"
    assert _settle(new, copy, tel=_no_tel()) is True  # kontakty już są na telefonie


def test_settle_leaves_a_non_resumable_state_untouched(tmp_path):
    copy = _copy(tmp_path)
    new = _new(tmp_path, OLD)
    _interrupted(copy, [_row("/sdcard/DCIM/plik", "done")], choice=UploadChoice(ALL, frozenset()),
                 status="complete", updated="2026-10-01T10:00:00+00:00")
    assert _settle(new, copy) is False
    assert new.scans == 0 and _meta(copy, "updated") == "2026-10-01T10:00:00+00:00"
