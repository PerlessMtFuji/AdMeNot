import os
import shutil
import time
from collections import namedtuple
from pathlib import Path

import pytest

from admenot.engine.adb.fake import FakeAdb
from admenot.engine.adb.transport import AdbError
from admenot.engine.apk import cache as C
from admenot.engine.facts import AppFacts

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


A_DIR = "/data/app/~~r1==/com.a-x1=="
B_DIR = "/data/app/~~r2==/com.b-y2=="
PRE = "/data/preload/com.vivo.widget"


def _facts():
    return [AppFacts("com.a", apk_path=f"{A_DIR}/base.apk"),
            AppFacts("com.b", apk_path=f"{B_DIR}/base.apk"),
            AppFacts("com.vivo.widget", apk_path=f"{PRE}/widget.apk"),
            AppFacts("com.nopath")]


def _stat_out():
    # Vivo (spec §3.4): katalogu /data/preload nie da się wylistować — tylko jawna ścieżka
    return (f"100 {A_DIR}/base.apk\n200 {A_DIR}/split_config.arm64_v8a.apk\n100 {A_DIR}/base.apk\n"
            f"1000 {B_DIR}/base.apk\n1000 {B_DIR}/base.apk\n50 {PRE}/widget.apk\n")


def _adb(out):
    facts = [f for f in _facts() if f.apk_path]
    return FakeAdb({C.stat_command(C._stat_paths(facts)[0]): out})


def test_stat_command_globs_directories_and_names_base_paths():
    paths = C._stat_paths([AppFacts("com.a", apk_path=f"{A_DIR}/base.apk")])[0]
    assert C.stat_command(paths) == (
        f"stat -c '%s %n' '{A_DIR}'/*.apk '{A_DIR}/base.apk' 2>/dev/null; true")


def test_estimate_sums_splits_and_counts_unknown(tmp_path):
    est = C.estimate(_adb(_stat_out()), _facts(), tmp_path)
    assert est.sizes == {"com.a": 300, "com.b": 1000, "com.vivo.widget": 50}
    assert (est.total_bytes, est.to_fetch_bytes, est.apps, est.unknown) == (1350, 1350, 4, 1)
    assert est.cached == 0
    assert est.largest_bytes == 1300  # dwie największe: 1000 + 300


def test_estimate_skips_what_is_already_cached(tmp_path):
    entry = tmp_path / "com.b" / "abc"
    entry.mkdir(parents=True)
    (entry / "base.apk").write_bytes(b"x" * 1000)
    est = C.estimate(_adb(_stat_out()), _facts(), tmp_path)
    assert est.to_fetch_bytes == 350 and est.largest_bytes == 350
    assert est.cached == 1


def test_estimate_without_stat_or_with_unknown_output_is_none(tmp_path):
    facts = [f for f in _facts() if f.apk_path]
    failing = FakeAdb({C.stat_command(C._stat_paths(facts)[0]): AdbError("command_failed", "x")})
    assert C.estimate(failing, _facts(), tmp_path) is None
    assert C.estimate(_adb("stat: not found\n"), _facts(), tmp_path) is None


def test_estimate_splits_long_commands_into_batches(tmp_path):
    facts = [AppFacts(f"com.app{i}", apk_path=f"/data/app/~~{'q' * 40}{i}==/com.app{i}-{'z' * 40}==/base.apk")
             for i in range(150)]
    batches = C._stat_paths(facts)
    assert len(batches) > 1 and all(len(C.stat_command(b)) <= C._MAX_COMMAND for b in batches)
    assert sum(len(b) for b in batches) == 300  # wzorzec + jawna ścieżka na aplikację


def test_estimate_shared_directory_uses_explicit_paths_only(tmp_path):
    facts = [AppFacts("com.foo", apk_path="/system/app/Foo.apk"),
             AppFacts("com.bar", apk_path="/system/app/Bar.apk")]
    paths = C._stat_paths(facts)[0]
    assert paths == ["/system/app/Foo.apk", "/system/app/Bar.apk"]
    adb = FakeAdb({C.stat_command(paths): "10 /system/app/Foo.apk\n20 /system/app/Bar.apk\n"})
    assert C.estimate(adb, facts, tmp_path).sizes == {"com.foo": 10, "com.bar": 20}


def test_estimate_single_target_in_shared_system_dir_uses_explicit_path(tmp_path):
    # Single target in /system/app should NOT use *.apk glob, ignoring stray Bar.apk in stat output
    facts = [AppFacts("com.foo", apk_path="/system/app/Foo.apk")]
    paths = C._stat_paths(facts)[0]
    assert "*.apk" not in C.stat_command(paths)
    assert paths == ["/system/app/Foo.apk"]
    adb = FakeAdb({
        C.stat_command(paths): "10 /system/app/Foo.apk\n20 /system/app/Bar.apk\n"
    })
    est = C.estimate(adb, facts, tmp_path)
    assert est.sizes == {"com.foo": 10}


def test_fits_counts_space_freed_by_pruning_other_scans(tmp_path, disk):
    _entry(tmp_path, "com.other", "id1", 1000)
    est = C.Estimate(total_bytes=5000, to_fetch_bytes=5000, apps=3, unknown=0,
                     largest_bytes=1500, sizes={})
    disk["free"] = C.RESERVE + 600
    assert C.fits(est, tmp_path, frozenset({"com.a"}))      # 600 wolne + 1000 do przycięcia
    assert not C.fits(est, tmp_path, frozenset({"com.other"}))  # wpis z tego skanu się nie liczy


def test_entries_skip_a_package_dir_that_cannot_be_listed(tmp_path, monkeypatch):
    good = tmp_path / "com.good" / "id"
    good.mkdir(parents=True)
    (good / "base.apk").write_bytes(b"x")
    (tmp_path / "com.gone" / "id").mkdir(parents=True)
    real = Path.iterdir

    def iterdir(self):
        if self.name == "com.gone":
            raise FileNotFoundError(self)
        return real(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    assert [e.package for e in C._entries(tmp_path, time.time())] == ["com.good"]


def test_prune_frees_room_for_the_next_download_below_the_limit(tmp_path, disk):
    """Pod limitem efektywnym przycinanie zwalnia jeszcze `need_bytes` + zapas (spec §3.6)."""
    a = _entry(tmp_path, "com.a", "id1", 1000, age_s=20)
    b = _entry(tmp_path, "com.b", "id1", 1000, age_s=10)
    disk["free"] = C.RESERVE + 500
    assert C.prune(tmp_path, 10 * GB) == 0  # w limicie: bez potrzeby nic
    assert C.prune(tmp_path, 10 * GB, need_bytes=1200) == 1000  # brakuje 700: najstarszy wpis
    assert not a.exists() and b.exists()
    assert C.has_room(tmp_path, 1200)


def test_cached_sets_of_an_unlistable_package_dir_is_empty(tmp_path, monkeypatch):
    (tmp_path / "com.gone" / "id").mkdir(parents=True)
    real = Path.iterdir

    def iterdir(self):
        if self.name == "com.gone":
            raise PermissionError(self)
        return real(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    assert C._cached_sets(tmp_path, "com.gone") == []


def test_estimate_lists_only_apps_that_need_fetching(tmp_path):
    entry = tmp_path / "com.b" / "abc"
    entry.mkdir(parents=True)
    (entry / "base.apk").write_bytes(b"x" * 1000)
    est = C.estimate(_adb(_stat_out()), _facts(), tmp_path)
    assert est.to_fetch == frozenset({"com.a", "com.vivo.widget"})
