from __future__ import annotations

import json

import pytest

from admenot.engine.transfer.failures import Failure, backup_failures, reason_key, restore_failures
from admenot.engine.transfer.restore_state import RestoreRow, RestoreState, restore_state_path
from admenot.engine.transfer.state import FileRow, State
from admenot.engine.transfer.store import CopyDir


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
