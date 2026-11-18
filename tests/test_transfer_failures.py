from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from admenot.engine.device.info import DeviceInfo
from admenot.engine.transfer import store
from admenot.engine.transfer.failures import Failure, backup_failures, reason_key, restore_failures
from admenot.engine.transfer.restore_state import (
    RestoreRow,
    RestoreState,
    read_restores,
    reopen_restore_for_retry,
    restore_state_path,
)
from admenot.engine.transfer.state import FileRow, State
from admenot.engine.transfer.store import CopyDir, RetryError


@pytest.fixture
def copy(tmp_path) -> CopyDir:
    path = tmp_path / "copy"
    path.mkdir()
    return CopyDir(path)


def _file(remote: str, status: str, error: str | None = None, root: str = "media") -> FileRow:
    return FileRow(remote, root, 10, 1, remote.lstrip("/"), False, status, 1, error)


def _backup(copy: CopyDir) -> State:
    return State(copy.state_path)


def test_reason_key_maps_raw_codes():
    for raw in ("no_space", "disk_full", "ENOSPC"):
        assert reason_key(raw) == "no_space"
    assert reason_key("denied") == "denied"
    for raw in ("disconnect", "disconnected", "no_device", "offline"):
        assert reason_key(raw) == "disconnected"
    for raw in ("vanished", "missing"):
        assert reason_key(raw) == "vanished"
    assert reason_key("changed") == "changed"
    for raw in ("INSTALL_FAILED_X", "failed", "user_restricted", "no_consent", "too_old", "no_abi",
                "version_downgrade", "invalid_apk", "conflict"):
        assert reason_key(raw) == "rejected"
    for raw in ("hash_mismatch", "hash_unavailable"):
        assert reason_key(raw) == "verify"
    for raw in (None, "pull_failed", "OSError", "cokolwiek"):
        assert reason_key(raw) == "other"


def test_backup_failures_missing_state_is_empty(copy):
    assert backup_failures(copy) == []
    assert restore_failures(copy, "NEW") == []


def test_backup_failures_lists_error_files_apps_and_telephony(copy):
    state = _backup(copy)
    state.insert(_file("/sdcard/DCIM/Camera/IMG_1.jpg", "error", "pull_failed"))
    state.insert(_file("/sdcard/DCIM/Camera/IMG_2.jpg", "skipped", "vanished"))
    state.insert(_file("/sdcard/DCIM/Camera/IMG_3.jpg", "done"))
    state.commit()
    state.set_meta("apps", {"com.a": {"status": "failed", "error": "OSError"},
                            "com.b": {"status": "done"}})
    state.set_meta("telephony", {"sms": {"status": "failed", "count": 0, "error": "query_failed"},
                                 "contacts": {"status": "ok", "count": 5}})
    state.close()
    copy.verdicts_path.write_text(json.dumps([{"package": "com.a", "version_code": 1, "verdict": "ok",
                                               "label": "Aplikacja A"}]), encoding="utf-8")
    assert backup_failures(copy) == [
        Failure("file", "media", "IMG_1.jpg", "DCIM/Camera", "other"),
        Failure("app", "apps", "Aplikacja A", "com.a", "other"),
        Failure("tel", "sms", "sms", "", "other"),
    ]


def test_backup_app_without_label_uses_package_and_permanent_not_retryable(copy):
    state = _backup(copy)
    state.set_meta("apps", {"com.a": {"status": "failed", "error": "too_old"}})
    state.close()
    (f,) = backup_failures(copy)
    assert (f.name, f.reason, f.retryable) == ("com.a", "rejected", False)


def test_restore_failures_lists_denied_error_files_apps_and_tel(copy):
    state = RestoreState(restore_state_path(copy, "NEW"))
    state.insert(RestoreRow("/sdcard/Download/a.txt", "/sdcard/Download/a.txt", "docs", 1, 1, "denied", 1))
    state.insert(RestoreRow("/storage/emulated/0/Music/b.mp3", "/sdcard/Music/b.mp3", "music", 1, 1,
                            "error", 1, "push_failed"))
    state.insert(RestoreRow("/sdcard/Music/c.mp3", "/sdcard/Music/c.mp3", "music", 1, 1, "done", 1))
    state.insert(RestoreRow("/sdcard/Music/d.mp3", "/sdcard/Music/d.mp3", "music", 1, 1,
                            "error", 1, "vanished"))
    state.commit()
    state.app_set("com.a", "failed", "conflict")
    state.app_set("com.b", "failed", "disconnected")
    state.app_set("com.c", "installed")
    state.tel_set("sms", ["1", "2", "3"], "error", "file", "write_failed")
    state.tel_set("sms", ["4"], "done", "file")
    state.tel_set("contacts", ["1"], "manual", "file")
    state.close()
    copy.verdicts_path.write_text(json.dumps([{"package": "com.a", "version_code": 1, "verdict": "ok",
                                               "label": "Aplikacja A"}]), encoding="utf-8")
    got = restore_failures(copy, "NEW")
    assert got == [
        Failure("file", "docs", "a.txt", "Download", "denied"),
        Failure("file", "music", "b.mp3", "Music", "other"),
        Failure("file", "music", "d.mp3", "Music", "vanished", retryable=False),
        Failure("app", "apps", "Aplikacja A", "com.a", "rejected", retryable=False),
        Failure("app", "apps", "com.b", "com.b", "disconnected"),
        Failure("tel", "sms", "sms", "", "other", count=3),
    ]


def test_failures_sorted_files_first_by_folder_then_name(copy):
    state = _backup(copy)
    state.insert(_file("/sdcard/Z/b.jpg", "error"))
    state.insert(_file("/sdcard/A/z.jpg", "error"))
    state.insert(_file("/sdcard/A/a.jpg", "error"))
    state.commit()
    state.set_meta("apps", {"com.z": {"status": "failed", "error": "x"},
                            "com.a": {"status": "failed", "error": "x"}})
    state.set_meta("telephony", {"sms": {"status": "failed", "error": "x"},
                                 "calls": {"status": "failed", "error": "x"}})
    state.close()
    got = backup_failures(copy)
    assert [(f.kind, f.folder, f.name) for f in got] == [
        ("file", "A", "a.jpg"), ("file", "A", "z.jpg"), ("file", "Z", "b.jpg"),
        ("app", "com.a", "com.a"), ("app", "com.z", "com.z"),
        ("tel", "", "calls"), ("tel", "", "sms")]


def test_failures_of_2000_files_in_one_query(copy):
    state = _backup(copy)
    for i in range(2000):
        state.insert(_file(f"/sdcard/DCIM/f{i}.jpg", "error", "pull_failed"))
    state.close()
    assert len(backup_failures(copy)) == 2000


# ---- ponowne otwarcie kopii i wgrywania ----------------------------------------------------------------

@pytest.fixture
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))


def _device(serial: str) -> DeviceInfo:
    now = datetime(2026, 10, 25, 12, 0, 0)
    return DeviceInfo(serial=serial, brand="oppo", manufacturer="OPPO", model="CPH2127", device="x",
                      market_name=None, android_release="11", sdk=30, security_patch=None, uptime_s=1.0,
                      local_now=now)


def _stored(serial: str = "ABC", status: str = "incomplete", hours: int = 0) -> CopyDir:
    now = datetime(2026, 10, 25, 12, 0, 0) + timedelta(hours=hours)
    stored = store.create_copy(serial, _device(serial), None, now)
    meta = stored.read_meta()
    meta.status = status  # type: ignore[assignment]
    stored.write_meta(meta)
    return stored


def _fail_some(stored: CopyDir) -> None:
    state = State(stored.state_path)
    state.insert(_file("/sdcard/DCIM/a.jpg", "error", "pull_failed"))
    state.insert(_file("/sdcard/DCIM/b.jpg", "error", "denied"))
    state.commit()
    state.set_meta("apps", {"com.a": {"status": "failed", "error": "OSError"}})
    state.close()


def test_reopen_copy_sets_in_progress_and_counts_retryable(_data_dir):
    stored = _stored()
    _fail_some(stored)
    assert store.find_resumable("ABC") is None
    assert store.reopen_copy_for_retry(stored) == 3
    assert stored.read_meta().status == "in_progress"
    found = store.find_resumable("ABC")
    assert found is not None and found.path == stored.path


def test_reopen_copy_counts_only_retryable(_data_dir):
    stored = _stored()
    state = State(stored.state_path)
    state.insert(_file("/sdcard/DCIM/a.jpg", "error", "pull_failed"))
    state.set_meta("apps", {"com.a": {"status": "failed", "error": "too_old"}})
    state.set_meta("telephony", {"sms": {"status": "failed", "error": "x"}})
    state.close()
    assert store.reopen_copy_for_retry(stored) == 2


def test_reopen_copy_without_failures_raises_nothing_to_retry(_data_dir):
    stored = _stored()
    with pytest.raises(store.RetryError) as exc:
        store.reopen_copy_for_retry(stored)
    assert exc.value.key == "nothing_to_retry"
    assert stored.read_meta().status == "incomplete"


def test_reopen_copy_refuses_when_other_copy_in_progress(_data_dir):
    stored = _stored(hours=0)
    _fail_some(stored)
    _stored(status="in_progress", hours=1)
    with pytest.raises(store.RetryError) as exc:
        store.reopen_copy_for_retry(stored)
    assert exc.value.key == "copy_resume_other"
    assert stored.read_meta().status == "incomplete"


def test_reopen_copy_in_progress_raises_copy_in_progress(_data_dir):
    stored = _stored(status="in_progress")
    _fail_some(stored)
    with pytest.raises(store.RetryError) as exc:
        store.reopen_copy_for_retry(stored)
    assert exc.value.key == "copy_in_progress"


def test_reopen_restore_repends_files_and_transient_apps(copy):
    path = restore_state_path(copy, "NEW")
    state = RestoreState(path)
    state.insert(RestoreRow("/sdcard/a.txt", "/sdcard/a.txt", "docs", 1, 1, "error", 3, "push_failed"))
    state.insert(RestoreRow("/sdcard/b.txt", "/sdcard/b.txt", "docs", 1, 1, "denied", 1, "denied"))
    state.insert(RestoreRow("/sdcard/c.txt", "/sdcard/c.txt", "docs", 1, 1, "error", 1, "vanished"))
    state.insert(RestoreRow("/sdcard/d.txt", "/sdcard/d.txt", "docs", 1, 1, "done", 1))
    state.commit()
    state.app_set("com.t", "failed", "disconnected", "ERR")
    state.app_set("com.c", "failed", "conflict")
    state.app_set("com.i", "installed")
    state.tel_set("sms", ["1", "2"], "error", "file", "write_failed")
    state.set_meta("serial", "NEW")
    state.set_meta("status", "complete")
    state.close()
    assert reopen_restore_for_retry(copy, "NEW") == 4  # 2 pliki + 1 aplikacja + 1 rodzaj telefonii
    state = RestoreState(path)
    try:
        rows = state.all_files()
        for name in ("a", "b"):
            row = rows[f"/sdcard/{name}.txt"]
            assert (row.status, row.attempts, row.error) == ("pending", 0, None)
        assert rows["/sdcard/c.txt"].status == "error"
        assert rows["/sdcard/d.txt"].status == "done"
        apps = state.apps_status()
        assert apps["com.t"] == ("pending", None, None)
        assert apps["com.c"] == ("failed", "conflict", None)
        assert apps["com.i"][0] == "installed"
        assert state.get_meta("status") == "incomplete"
    finally:
        state.close()
    (summary,) = read_restores(copy)
    assert summary.resumable is True


def test_reopen_restore_is_atomic_when_a_meta_write_fails(copy, monkeypatch):
    """Błąd przy ostatnim zapisie meta cofa też wiersze: stan zostaje `complete` z błędami do ponowienia."""
    path = restore_state_path(copy, "NEW")
    state = RestoreState(path)
    state.insert(RestoreRow("/sdcard/a.txt", "/sdcard/a.txt", "docs", 1, 1, "error", 3, "push_failed"))
    state.tel_set("sms", ["1"], "error", "file", "write_failed")
    state.set_meta("serial", "NEW")
    state.set_meta("status", "complete")
    state.close()
    real = RestoreState.set_meta

    def failing(self, key, value, **kw):
        if key == "tel_left":
            raise sqlite3.OperationalError("disk full")
        real(self, key, value, **kw)

    monkeypatch.setattr(RestoreState, "set_meta", failing)
    with pytest.raises(sqlite3.OperationalError):
        reopen_restore_for_retry(copy, "NEW")
    monkeypatch.undo()
    state = RestoreState(path)
    try:
        assert state.all_files()["/sdcard/a.txt"].status == "error"
        assert state.get_meta("status") == "complete"
    finally:
        state.close()


def test_reopen_restore_only_tel_failed_is_resumable(copy):
    state = RestoreState(restore_state_path(copy, "NEW"))
    state.tel_set("sms", ["1"], "error", "file", "write_failed")
    state.set_meta("serial", "NEW")
    state.set_meta("status", "complete")
    state.close()
    assert reopen_restore_for_retry(copy, "NEW") == 1
    (summary,) = read_restores(copy)
    assert summary.resumable is True


def test_reopen_restore_without_failures_raises_nothing_to_retry(copy):
    state = RestoreState(restore_state_path(copy, "NEW"))
    state.insert(RestoreRow("/sdcard/a.txt", "/sdcard/a.txt", "docs", 1, 1, "done", 1))
    state.set_meta("serial", "NEW")
    state.close()
    with pytest.raises(RetryError) as exc:
        reopen_restore_for_retry(copy, "NEW")
    assert exc.value.key == "nothing_to_retry"
