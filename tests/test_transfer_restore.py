from __future__ import annotations

import dataclasses
import os
import shutil
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
from admenot.engine.transfer.restore import (
    RestoreError,
    RestoreResult,
    RestoreState,
    UploadChoice,
    restore_state_path,
    run_restore,
)
from admenot.engine.transfer.restore_plan import UPLOAD_GROUPS, RestorePlan, build_plan

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


def _rows(copy: store.CopyDir) -> dict[str, rs.RestoreRow]:
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


def test_resume_after_stop_no_duplicates(tmp_path):
    copy = _copy(tmp_path, MANY)
    new = _new(tmp_path)
    first = _run(new, copy, _plan(new, copy), should_stop=lambda: new.push_calls >= 1)
    assert first.status == "stopped"
    assert _meta(copy, "status") == "stopped"
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
    state.insert(rs.RestoreRow(remote, remote, "videos", 500, MTIME, "pushing", 0, None))
    state.close()
    res = _run(new, copy, _plan(new, copy, taken=True))
    assert res.status == "complete"
    _assert_uploaded(new, OLD)
    assert not any("z kopii" in rel for rel in _phone_files(new))
    assert _rows(copy)[remote].target == remote


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


def test_denied_folder_reported_not_failed(tmp_path):
    wa = {"Android/media/com.whatsapp/WhatsApp/Media/w1.jpg": b"1" * 7,
          "Android/media/com.whatsapp/WhatsApp/Media/w2.jpg": b"2" * 8}
    copy = _copy(tmp_path, {**OLD, **wa}, extra=("whatsapp",))
    new = _new(tmp_path)
    new.deny_prefixes = {"/sdcard/Android/media/"}
    res = _run(new, copy, _plan(new, copy))
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


OUTCOMES = {"/sdcard/Download/evil.apk": ("malicious", False), "/sdcard/Download/odd.apk": ("suspicious", False),
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
