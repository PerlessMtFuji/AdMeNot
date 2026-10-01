import os
import shutil
import time
from collections import namedtuple

import pytest

from demalware.engine.apk import cache as C

GB = C.GB
Disk = namedtuple("Disk", "total used free")


def _entry(root, package, name, size, age_s=0.0):
    """Wpis pamięci podręcznej `<pakiet>/<name>` z jednym plikiem i czasem sprzed `age_s` s."""
    d = root / package / name
    d.mkdir(parents=True)
    (d / "base.apk").write_bytes(b"x" * size)
    t = time.time() - age_s
    os.utime(d, (t, t))
    return d


@pytest.fixture
def disk(monkeypatch):
    """Wolne miejsce na sztywno: `disk.free` zmienia się razem z usuwaniem plików."""
    state = {"free": 100 * GB, "total": 500 * GB}

    def fake(path):
        return Disk(state["total"], state["total"] - state["free"], state["free"])

    real_rmtree = shutil.rmtree

    def tracking_rmtree(path, ignore_errors=False):
        freed = C.cache_size(path)
        real_rmtree(path, ignore_errors=ignore_errors)
        state["free"] += freed

    monkeypatch.setattr(C, "disk_usage", fake)
    monkeypatch.setattr(C.shutil, "rmtree", tracking_rmtree)
    return state


def test_usage_and_effective_limit_follow_free_space(tmp_path, disk):
    _entry(tmp_path, "com.a", "id1", 1000)
    use = C.usage(tmp_path, 10 * GB)
    assert (use.size_bytes, use.limit_bytes, use.effective_bytes) == (1000, 10 * GB, 10 * GB)
    disk["free"] = 4 * GB  # spec §3.2: dysk 120 GB, wolne 4 GB → limit efektywny 2 GB (+ to, co już jest)
    assert C.usage(tmp_path, 10 * GB).effective_bytes == 2 * GB + 1000
    disk["free"] = GB
    assert C.usage(tmp_path, 10 * GB).effective_bytes == 0


def test_usage_of_a_missing_directory_is_zero(tmp_path, disk):
    assert C.usage(tmp_path / "nope" / "apk-cache", GB).size_bytes == 0


def test_prune_order_other_scans_then_safe_then_flagged(tmp_path, disk):
    old_other = _entry(tmp_path, "com.other", "id1", 300, age_s=500)
    new_other = _entry(tmp_path, "com.other2", "id1", 300, age_s=100)
    safe = _entry(tmp_path, "com.safe", "id1", 300, age_s=900)
    flagged = _entry(tmp_path, "com.bad", "id1", 300, age_s=950)
    scan = frozenset({"com.safe", "com.bad"})
    done = frozenset({"com.safe", "com.bad"})
    flagged_set = frozenset({"com.bad"})

    assert C.prune(tmp_path, 900, scan=scan, done=done, flagged=flagged_set) == 300
    assert not old_other.exists() and new_other.exists()
    C.prune(tmp_path, 600, scan=scan, done=done, flagged=flagged_set)
    assert not new_other.exists() and safe.exists()
    C.prune(tmp_path, 300, scan=scan, done=done, flagged=flagged_set)
    assert not safe.exists() and flagged.exists()
    C.prune(tmp_path, 0, scan=scan, done=done, flagged=flagged_set)
    assert not flagged.exists()
    assert not (tmp_path / "com.other").exists()  # pusty katalog pakietu znika


def test_pending_scan_entries_go_last(tmp_path, disk):
    pending = _entry(tmp_path, "com.next", "id1", 300, age_s=999)
    safe = _entry(tmp_path, "com.safe", "id1", 300, age_s=1)
    C.prune(tmp_path, 300, scan=frozenset({"com.next", "com.safe"}), done=frozenset({"com.safe"}))
    assert pending.exists() and not safe.exists()


def test_prune_never_touches_work_dirs_fresh_unverified_or_busy(tmp_path, disk):
    part = _entry(tmp_path, "com.a", ".part-x1", 300)
    fresh = _entry(tmp_path, "com.a", ".unverified-y1", 300, age_s=60)
    stale = _entry(tmp_path, "com.a", ".unverified-y2", 300, age_s=2 * 3600)
    busy = _entry(tmp_path, "com.busy", "id1", 300, age_s=9999)
    C.prune(tmp_path, 0, busy=frozenset({"com.busy"}))
    assert part.exists() and fresh.exists() and busy.exists()
    assert not stale.exists()


def test_prune_with_little_free_space_frees_down_to_the_reserve(tmp_path, disk):
    a = _entry(tmp_path, "com.a", "id1", 1000, age_s=10)
    disk["free"] = C.RESERVE - 500  # efektywny = 1000 + free − RESERVE = 500 → nadmiar 500
    assert C.prune(tmp_path, 10 * GB) == 1000
    assert not a.exists()


def test_clear_cache_removes_finished_entries_and_reports_bytes(tmp_path, disk):
    _entry(tmp_path, "com.a", "id1", 1000)
    part = _entry(tmp_path, "com.b", ".part-z", 50)
    assert C.clear_cache(tmp_path) == 1000
    assert part.exists() and not (tmp_path / "com.a").exists()
    assert C.clear_cache(tmp_path / "missing") == 0


def test_locked_entry_is_skipped_and_not_counted(tmp_path, disk, monkeypatch):
    locked = _entry(tmp_path, "com.locked", "id1", 1000, age_s=50)
    other = _entry(tmp_path, "com.other", "id1", 1000, age_s=10)
    real = C.shutil.rmtree

    def rmtree(path, ignore_errors=False):
        if "com.locked" in str(path):
            return  # Windows: plik otwarty w innym procesie, ignore_errors połyka błąd
        real(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(C.shutil, "rmtree", rmtree)
    assert C.clear_cache(tmp_path) == 1000
    assert locked.exists() and not other.exists()


def test_has_room_and_prunable(tmp_path, disk):
    _entry(tmp_path, "com.other", "id1", 700)
    _entry(tmp_path, "com.mine", "id1", 300)
    disk["free"] = C.RESERVE + 100
    assert C.has_room(tmp_path, 100) and not C.has_room(tmp_path, 101)
    assert C.prunable_bytes(tmp_path, frozenset({"com.mine"})) == 700
