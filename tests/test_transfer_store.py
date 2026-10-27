from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from admenot.engine.device.info import DeviceInfo
from admenot.engine.paths import device_dir_name, transfers_dir
from admenot.engine.transfer import store
from admenot.engine.transfer.state import FileRow, State

NOW = datetime(2026, 10, 25, 12, 0, 0)


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))


def _device(serial: str = "ABC123", imei: str | None = "356938035643809") -> DeviceInfo:
    return DeviceInfo(
        serial=serial, brand="oppo", manufacturer="OPPO", model="CPH2127", device="x",
        market_name=None, android_release="11", sdk=30, security_patch=None, uptime_s=1.0,
        local_now=NOW, imei=imei)


def _copy(serial: str = "ABC123", now: datetime = NOW) -> store.CopyDir:
    return store.create_copy(serial, _device(serial), "Jan Kowalski", now)


def test_create_copy_layout():
    copy = _copy()
    meta = copy.read_meta()
    assert copy.meta_path.is_file()
    assert copy.path == transfers_dir() / device_dir_name("ABC123") / "20261025-120000"
    assert meta.id == f"{device_dir_name('ABC123')}/20261025-120000"
    assert meta.created == NOW
    assert meta.expires == NOW + timedelta(days=7)
    assert meta.status == "in_progress"
    assert (meta.serial, meta.manufacturer, meta.model, meta.android) == ("ABC123", "OPPO", "CPH2127", "11")
    assert meta.imei == "356938035643809"
    assert meta.client == "Jan Kowalski"
    assert copy.files_dir.is_dir() and copy.phone_dir.is_dir() and copy.apps_dir.is_dir()
    assert sorted(p.name for p in copy.path.iterdir()) == ["apps", "files", "meta.json", "phone"]
    assert copy.state_path.name == "state.sqlite"


def test_create_copy_same_second_never_overwrites():
    first = _copy()
    second = _copy()
    assert first.path != second.path
    assert second.path.name == "20261025-120001"
    assert second.read_meta().created == NOW + timedelta(seconds=1)
    assert first.read_meta().created == NOW


def test_meta_roundtrip_without_imei_and_client():
    copy = store.create_copy("S", _device("S", imei=None), None, NOW)
    meta = copy.read_meta()
    assert meta.imei is None and meta.client is None
    meta.status = "complete"
    meta.selection = {"files": True}
    meta.counts = {"sms": 3}
    meta.bytes = 42
    copy.write_meta(meta)
    assert copy.read_meta() == meta
    assert not list(copy.path.glob("*.tmp"))


def test_verdicts_roundtrip():
    from admenot.engine.transfer.inventory import AppEntry
    copy = _copy()
    copy.write_verdicts([AppEntry("com.a", "A", 5, "safe", True), AppEntry("com.b", "B", None, "malicious", False)])
    assert copy.verdicts_path.name == store.VERDICTS
    assert copy.read_verdicts() == {"com.a": (5, "safe"), "com.b": (None, "malicious")}


def test_read_verdicts_missing_is_none():
    copy = _copy()
    assert copy.read_verdicts() is None
    copy.verdicts_path.write_text("{not json", encoding="utf-8")
    assert copy.read_verdicts() is None


def test_find_resumable_newest_in_progress():
    old = _copy(now=NOW)
    mid = _copy(now=NOW + timedelta(hours=1))
    newest = _copy(now=NOW + timedelta(hours=2))
    other = _copy("OTHER", now=NOW + timedelta(hours=3))
    meta = newest.read_meta()
    meta.status = "complete"
    newest.write_meta(meta)
    assert store.find_resumable("ABC123").path == mid.path
    assert store.find_resumable("OTHER").path == other.path
    assert store.find_resumable("NONE") is None
    assert old.path != mid.path


def test_extend_adds_seven_days_each_time():
    meta = _copy().read_meta()
    store.extend(meta.id)
    result = store.extend(meta.id)
    assert result.expires == meta.created + timedelta(days=21)
    assert store.list_copies()[0].expires == meta.created + timedelta(days=21)


def test_purge_deletes_expired_only():
    expired = _copy(now=NOW - timedelta(days=8))
    fresh = _copy(now=NOW - timedelta(days=1))
    expired_id = expired.read_meta().id
    assert store.purge_expired(NOW, lambda serial: False, lambda copy_id: False) == [expired_id]
    assert not expired.path.exists()
    assert fresh.path.exists()


def test_purge_skips_locked_copy():
    expired = _copy(now=NOW - timedelta(days=8))
    seen: list[str] = []

    def busy(serial: str) -> bool:
        seen.append(serial)
        return True

    assert store.purge_expired(NOW, busy, lambda copy_id: False) == []
    assert seen == ["ABC123"]
    assert expired.path.exists()


def test_purge_skips_copy_in_use():
    """Kopia wgrywana właśnie na nowy telefon (`busy_copy(id)`) zostaje, choć jej telefon jest wolny."""
    used = _copy(now=NOW - timedelta(days=8))
    other = _copy(now=NOW - timedelta(days=9))
    used_id, other_id = used.read_meta().id, other.read_meta().id
    assert used_id != other_id
    assert store.purge_expired(NOW, lambda serial: False, lambda copy_id: copy_id == used_id) == [other_id]
    assert used.path.exists() and not other.path.exists()


def test_copy_dir_resolves_id_only():
    copy = _copy()
    assert store.copy_dir(copy.read_meta().id).path == copy.path.resolve()
    with pytest.raises(ValueError):
        store.copy_dir("../x")


def test_purge_leaves_broken_meta():
    broken = _copy(now=NOW - timedelta(days=30))
    broken.meta_path.write_text("{nie json", encoding="utf-8")
    assert store.purge_expired(NOW, lambda serial: False, lambda copy_id: False) == []
    assert broken.path.exists()


def test_delete_refuses_foreign_dir(tmp_path):
    victim = tmp_path / "data" / "x"
    victim.mkdir(parents=True)
    (victim / "meta.json").write_text("{}", encoding="utf-8")
    copy = _copy()
    dev = device_dir_name("ABC123")
    for bad in ("../x", "..", "", "x", f"{dev}/..", f"{dev}/20261025-120000/pliki",
                f"{dev}\\20261025-120000", "/etc/20261025-120000", "C:/x/20261025-120000",
                f"{dev}/99999999-000000", f"{dev}/20261025-120000\n", f"{dev}\n/20261025-120000",
                f"{dev}/２０２６１０２５-120000"):
        with pytest.raises(ValueError):
            store.delete(bad)
    assert victim.exists() and copy.path.exists()


def test_delete_requires_meta_json():
    copy = _copy()
    copy.meta_path.unlink()
    with pytest.raises(ValueError):
        store.delete(f"{device_dir_name('ABC123')}/20261025-120000")
    assert copy.path.exists()


def test_delete_removes_copy():
    copy = _copy()
    (copy.files_dir / "a.txt").write_text("x", encoding="utf-8")
    store.delete(copy.read_meta().id)
    assert not copy.path.exists()


def test_list_newest_first_and_skips_broken_meta():
    a = _copy(now=NOW)
    b = _copy(now=NOW + timedelta(hours=1))
    c = _copy("OTHER", now=NOW + timedelta(hours=2))
    b.meta_path.write_text("{", encoding="utf-8")
    assert [m.id for m in store.list_copies()] == [c.read_meta().id, a.read_meta().id]


def test_list_empty_when_no_transfers_dir():
    assert store.list_copies() == []


# ---- port testów State ze skryptu adb-backup ----------------------------------------------

def _row(remote: str, size: int = 10, status: str = "pending") -> FileRow:
    return FileRow(remote, "/sdcard", size, 1700000000, remote.lstrip("/"), False, status, 0)


def test_state_resume_and_totals(tmp_path):
    path = tmp_path / "state.sqlite"
    st = State(path)
    for i in range(3):
        st.insert(_row(f"/sdcard/f{i}", size=100 + i))
    st.update("/sdcard/f0", status="done", sha256="ab", attempts=1)
    st.update("/sdcard/f1", status="error", error="boom")
    st.set_meta("scan", {"roots": ["/sdcard"]})
    st.close()

    again = State(path)  # wznowienie po przerwaniu
    assert [r.remote for r in again.pending()] == ["/sdcard/f2"]
    assert [r.remote for r in again.by_status("done")] == ["/sdcard/f0"]
    assert again.all_files()["/sdcard/f1"].error == "boom"
    assert again.totals() == {"done": (1, 100), "error": (1, 101), "pending": (1, 102)}
    assert again.get_meta("scan") == {"roots": ["/sdcard"]}
    assert again.get_meta("missing", 7) == 7
    assert again.used_local() == {"sdcard/f0", "sdcard/f1", "sdcard/f2"}
    again.close()


def test_delete_failure_keeps_meta_and_retry_succeeds(monkeypatch):
    copy = _copy(now=NOW - timedelta(days=8))
    (copy.files_dir / "a.txt").write_text("x", encoding="utf-8")
    copy_id = copy.read_meta().id
    real_rmtree = store.shutil.rmtree
    calls = {"n": 0}

    def flaky(path, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("zablokowany plik")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(store.shutil, "rmtree", flaky)
    assert store.purge_expired(NOW, lambda serial: False, lambda copy_id: False) == []
    assert copy.meta_path.is_file()
    assert [m.id for m in store.list_copies()] == [copy_id]
    assert store.purge_expired(NOW, lambda serial: False, lambda copy_id: False) == [copy_id]
    assert not copy.path.exists()


def test_create_copy_failure_leaves_no_orphan(monkeypatch):
    def boom(self, meta):
        raise OSError("dysk pełny")

    monkeypatch.setattr(store.CopyDir, "write_meta", boom)
    with pytest.raises(OSError):
        _copy()
    assert list((transfers_dir() / device_dir_name("ABC123")).iterdir()) == []


def test_extend_broken_meta_is_value_error():
    copy = _copy()
    copy.meta_path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        store.extend(f"{device_dir_name('ABC123')}/20261025-120000")
