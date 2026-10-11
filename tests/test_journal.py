import sqlite3
from contextlib import closing
from datetime import datetime

import pytest

from admenot.engine.journal.db import (
    MAX_REPORT_SCREENSHOTS,
    MIGRATIONS,
    Journal,
    JournalTooNew,
    ScreenshotLimit,
)
from admenot.engine.paths import backups_dir, journal_path, logs_dir


def _step(package, kind="force_stop"):
    return {"kind": kind, "package": package, "params": {}}


class Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def test_order_numbers_count_per_day(tmp_path):
    clock = Clock(datetime(2026, 9, 26, 10, 0))
    with Journal(tmp_path / "j.db", now=clock) as j:
        a = j.create_order("S1", "CPH2271")
        b = j.create_order("S2", None, "Jan Kowalski")
        clock.t = datetime(2026, 9, 27, 9, 0)
        c = j.create_order("S1", "CPH2271", "")
    assert (a.number, b.number, c.number) == ("ZS/2026/0926/01", "ZS/2026/0926/02", "ZS/2026/0927/01")
    assert b.client_name == "Jan Kowalski" and a.client_name is None and c.client_name is None
    assert a.status == "running" and a.created_at == datetime(2026, 9, 26, 10, 0)


def test_actions_survive_reopen_and_parent_dir_is_created(tmp_path):
    path = tmp_path / "nested" / "journal.db"
    step = {"kind": "enabled", "package": "com.x", "params": {"enabled": "0"}}
    with Journal(path) as j:
        order = j.create_order("S1", "M")
        aid = j.add_action(order.id, "com.x", "disable", step, "pm disable-user --user 0 com.x")
        assert j.action(aid).status == "pending" and j.action(aid).prev_state is None
        j.record_prev_state(aid, {"enabled": True},
                            {"kind": "enabled", "package": "com.x", "params": {"enabled": "1"}})
        j.set_action_status(aid, "done")
    with Journal(path) as j:
        (action,) = j.actions(order.id)
    assert action.status == "done" and action.error is None
    assert action.step == step and action.prev_state == {"enabled": True}
    assert action.inverse["params"] == {"enabled": "1"}
    assert action.command == "pm disable-user --user 0 com.x" and action.level == "disable"


def test_interrupted_orders_have_pending_actions(tmp_path):
    with Journal(tmp_path / "j.db") as j:
        done = j.create_order("S1", "M")
        a = j.add_action(done.id, "com.a", "silence", _step("com.a"), "am force-stop com.a")
        j.set_action_status(a, "done")
        cut = j.create_order("S1", "M")
        j.add_action(cut.id, "com.b", "silence", _step("com.b"), "am force-stop com.b")
        other = j.create_order("S2", "M")
        j.add_action(other.id, "com.c", "silence", _step("com.c"), "am force-stop com.c")
        assert [o.id for o in j.interrupted_orders("S1")] == [cut.id]
        assert [o.id for o in j.orders_for("S1")] == [cut.id, done.id]
        assert j.order_by_number(cut.number).id == cut.id
        assert j.order_by_number("ZS/1999/0101/01") is None


def test_failed_action_keeps_error_key_and_invalid_status_is_rejected(tmp_path):
    with Journal(tmp_path / "j.db") as j:
        order = j.create_order("S1", "M")
        aid = j.add_action(order.id, "com.a", "silence", _step("com.a"), "am force-stop com.a")
        j.set_action_status(aid, "failed", "security")
        assert j.action(aid).error == "security"
        with pytest.raises(ValueError):
            j.set_action_status(aid, "weird")
        with pytest.raises(ValueError):
            j.set_order_status(order.id, "weird")
        j.set_order_status(order.id, "failed")
        assert j.order(order.id).status == "failed"


def test_data_paths_follow_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert journal_path() == tmp_path / "AdMeNot" / "journal.db"
    assert backups_dir() == tmp_path / "AdMeNot" / "backups"
    assert logs_dir() == tmp_path / "AdMeNot" / "logs"


def test_recent_serials_newest_first(tmp_path):
    with Journal(tmp_path / "j.db") as j:
        j.create_order("A", None)
        j.create_order("B", None)
        j.create_order("A", None)
        assert j.recent_serials() == ["A", "B"]
        assert j.recent_serials(limit=1) == ["A"]


def test_scan_snapshot_and_verification_are_stored_per_order(tmp_path):
    path = tmp_path / "j.db"
    snapshot = {"device": {"serial": "S1"}, "apps": [{"package": "com.x", "label": "Źle & <b>"}]}
    with Journal(path) as j:
        order = j.create_order("S1", "M")
        other = j.create_order("S1", "M")
        assert j.scan(order.id) is None and j.verification(order.id) is None
        j.save_scan(order.id, snapshot)
        j.save_verification(order.id, {"com.x": ["appop"]})
    with Journal(path) as j:
        assert j.scan(order.id) == snapshot
        assert j.verification(order.id) == {"com.x": ["appop"]}
        assert j.scan(other.id) is None and j.verification(other.id) is None


def test_verification_without_scan_and_both_overwrite(tmp_path):
    with Journal(tmp_path / "j.db") as j:
        order = j.create_order("S1", "M")
        j.save_verification(order.id, {"com.x": ["enabled"]})
        j.save_verification(order.id, {})
        assert j.verification(order.id) == {} and j.scan(order.id) is None
        j.save_scan(order.id, {"apps": []})
        j.save_scan(order.id, {"apps": [1]})
        assert j.scan(order.id) == {"apps": [1]} and j.verification(order.id) == {}


def test_journal_from_plan_2_gets_the_scan_table(tmp_path):
    path = tmp_path / "j.db"
    with Journal(path) as j:
        order = j.create_order("S1", "M")
        j._db.execute("DROP TABLE order_scans")  # stan bazy sprzed Planu 6
        j._db.execute("ALTER TABLE orders DROP COLUMN device_identity")  # i sprzed schematu v2
        j._db.execute("PRAGMA user_version = 0")  # i sprzed wersjonowania schematu
    with Journal(path) as j:
        assert j.order(order.id).number == order.number
        j.save_scan(order.id, {"apps": []})
        assert j.scan(order.id) == {"apps": []}


SHOT_NOW = datetime(2026, 9, 29, 10, 0, 0)
CONTEXT = {"foreground": {"package": "com.ad", "name": "Ad"}, "overlays": [], "black": False}


@pytest.fixture
def shots_journal():
    journal = Journal(":memory:", now=lambda: SHOT_NOW)
    yield journal
    journal.close()


def test_screenshot_waits_then_attaches_to_its_order(shots_journal):
    j = shots_journal
    shot = j.add_screenshot("S1", CONTEXT)
    assert shot.order_id is None and shot.in_report and shot.context == CONTEXT
    assert shot.taken_at == SHOT_NOW and shot.device_serial == "S1"
    order = j.create_order("S1", "SM-A145R")
    j.attach_screenshots([shot.id], order.id)
    assert [s.id for s in j.screenshots(order.id)] == [shot.id]
    assert j.screenshot_count(order.id) == 1
    assert j.orphan_screenshots() == []


def test_attach_keeps_the_eight_newest_in_the_report(shots_journal):
    j = shots_journal
    ids = [j.add_screenshot("S1", CONTEXT).id for _ in range(10)]
    order = j.create_order("S1", None)
    j.attach_screenshots(ids, order.id)
    chosen = [s.id for s in j.screenshots(order.id) if s.in_report]
    assert chosen == ids[-MAX_REPORT_SCREENSHOTS:]


def test_attach_to_a_resumed_order_keeps_the_servicers_choice(shots_journal):
    j = shots_journal
    order = j.create_order("S1", None)
    chosen = [j.add_screenshot("S1", CONTEXT, order.id).id for _ in range(MAX_REPORT_SCREENSHOTS - 2)]
    waiting = [j.add_screenshot("S1", CONTEXT).id for _ in range(3)]
    j.attach_screenshots(waiting, order.id)
    in_report = [s.id for s in j.screenshots(order.id) if s.in_report]
    assert in_report == chosen + waiting[-2:]


def test_attach_never_moves_a_shot_from_another_order(shots_journal):
    j = shots_journal
    first = j.create_order("S1", None)
    taken = j.add_screenshot("S1", CONTEXT, first.id)
    second = j.create_order("S1", None)
    j.attach_screenshots([taken.id], second.id)
    assert j.screenshot(taken.id).order_id == first.id


def test_ninth_shot_in_an_order_is_left_out_and_cannot_be_forced_in(shots_journal):
    j = shots_journal
    order = j.create_order("S1", None)
    for _ in range(MAX_REPORT_SCREENSHOTS):
        assert j.add_screenshot("S1", CONTEXT, order.id).in_report
    ninth = j.add_screenshot("S1", CONTEXT, order.id)
    assert ninth.in_report is False
    with pytest.raises(ScreenshotLimit):
        j.set_screenshot_in_report(ninth.id, True)
    first = j.screenshots(order.id)[0]
    assert j.set_screenshot_in_report(first.id, False).in_report is False
    assert j.set_screenshot_in_report(ninth.id, True).in_report is True


def test_orphans_and_delete(shots_journal):
    j = shots_journal
    orphan = j.add_screenshot("S1", CONTEXT)
    order = j.create_order("S1", None)
    kept = j.add_screenshot("S1", CONTEXT, order.id)
    assert j.orphan_screenshots() == [orphan.id]
    j.delete_screenshots([orphan.id])
    j.delete_screenshots([])
    with pytest.raises(KeyError):
        j.screenshot(orphan.id)
    assert j.screenshot(kept.id).order_id == order.id


def test_screenshot_paths(monkeypatch, tmp_path):
    from admenot.engine import paths

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.screenshots_dir() == tmp_path / "AdMeNot" / "screenshots"
    assert paths.screenshot_files(7) == (tmp_path / "AdMeNot" / "screenshots" / "7.png",
                                         tmp_path / "AdMeNot" / "screenshots" / "7.jpg")


# --- wersjonowanie schematu ---------------------------------------------------------------------

def _version(path) -> int:
    with closing(sqlite3.connect(path)) as db:
        return db.execute("PRAGMA user_version").fetchone()[0]


def test_new_journal_gets_latest_schema_version(tmp_path):
    with Journal(tmp_path / "j.db"):
        pass
    assert _version(tmp_path / "j.db") == len(MIGRATIONS)
    assert not list(tmp_path.glob("*.bak-*"))


def test_unversioned_journal_keeps_data_and_gets_version_1(tmp_path):
    path = tmp_path / "j.db"
    with closing(sqlite3.connect(path)) as db:
        db.executescript(MIGRATIONS[0])
        db.execute("INSERT INTO orders(number, device_serial, created_at, status)"
                   " VALUES ('ZS/1', 'S1', '2026-10-01T10:00:00', 'done')")
        db.commit()
    with Journal(path) as j:
        assert j.order_by_number("ZS/1").device_serial == "S1"
    assert _version(path) == len(MIGRATIONS)


def test_migration_adds_column_and_backs_up_previous_version(tmp_path):
    path = tmp_path / "j.db"
    with Journal(path) as j:
        j.create_order("S1", "M")
    latest = len(MIGRATIONS)
    newer = (*MIGRATIONS, "ALTER TABLE orders ADD COLUMN note TEXT;")
    with Journal(path, migrations=newer) as j:
        assert j.orders_for("S1")[0].device_model == "M"
    assert _version(path) == latest + 1
    backup = tmp_path / f"j.db.bak-v{latest}"
    assert _version(backup) == latest
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute("SELECT count(*) FROM orders").fetchone()[0] == 1


def test_failed_migration_rolls_back(tmp_path):
    path = tmp_path / "j.db"
    with Journal(path) as j:
        j.create_order("S1", "M")
    broken = (*MIGRATIONS, "ALTER TABLE orders ADD COLUMN note TEXT; SELECT * FROM nope;")
    with pytest.raises(sqlite3.OperationalError):
        Journal(path, migrations=broken)
    assert _version(path) == len(MIGRATIONS)
    with Journal(path) as j:
        assert len(j.orders_for("S1")) == 1
    with closing(sqlite3.connect(path)) as db:
        cols = [r[1] for r in db.execute("PRAGMA table_info(orders)")]
    assert "note" not in cols


def test_journal_from_newer_version_is_refused(tmp_path):
    path = tmp_path / "j.db"
    with Journal(path):
        pass
    with closing(sqlite3.connect(path)) as db:
        db.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    with pytest.raises(JournalTooNew):
        Journal(path)


def test_order_keeps_the_phone_identity_and_old_journals_migrate(tmp_path):
    path = tmp_path / "j.db"
    with closing(sqlite3.connect(path)) as db:  # dziennik z 0.9.x (v1), bez kolumny tożsamości
        db.executescript(MIGRATIONS[0])
        db.execute("INSERT INTO orders(number, device_serial, device_model, created_at, status)"
                   " VALUES ('ZS/2026/1001/01', 'S1', 'M', '2026-10-01T10:00:00', 'done')")
        db.execute("PRAGMA user_version = 1")
        db.commit()
    with Journal(path) as j:
        old = j.order_by_number("ZS/2026/1001/01")
        assert old.device_identity is None
        new = j.create_order("S1", "M", None, {"android_id": "aaaa1111bbbb2222", "model": "M"})
        assert j.order(new.id).device_identity == {"android_id": "aaaa1111bbbb2222", "model": "M"}
        assert j.interrupted_orders("S1") == []
    assert (tmp_path / "j.db.bak-v1").exists()


def test_number_after_deleting_an_order_does_not_collide(tmp_path):
    clock = Clock(datetime(2026, 10, 11, 10, 0))
    with Journal(tmp_path / "j.db", now=clock) as j:
        first = j.create_order("S1", "M")
        j.create_order("S1", "M")
        j.delete_order(first.id)
        third = j.create_order("S1", "M")
    assert third.number == "ZS/2026/1011/03"


def test_delete_order_removes_its_rows_only(tmp_path):
    with Journal(tmp_path / "j.db") as j:
        keep, gone = j.create_order("S1", "M"), j.create_order("S1", "M")
        for order in (keep, gone):
            j.add_action(order.id, "com.ad", "remove",
                         {"kind": "backup", "package": "com.ad", "params": {"dir": f"C:/b/{order.id}"}}, "backup")
            j.save_scan(order.id, {"apps": []})
            j.add_screenshot("S1", {}, order.id)
        j.delete_order(gone.id)
        assert j.order_by_number(gone.number) is None and j.actions(gone.id) == []
        assert j.scan(gone.id) is None and j.screenshots(gone.id) == []
        assert len(j.actions(keep.id)) == 1 and j.scan(keep.id) == {"apps": []}
        assert j.backup_dirs() == {f"C:/b/{keep.id}"}
        assert j.backup_dirs(exclude=keep.id) == set()


def test_orders_before_a_cutoff(tmp_path):
    clock = Clock(datetime(2026, 1, 1, 9, 0))
    with Journal(tmp_path / "j.db", now=clock) as j:
        old = j.create_order("S1", "M")
        clock.t = datetime(2026, 10, 1, 9, 0)
        j.create_order("S1", "M")
        assert [o.number for o in j.orders_before(datetime(2026, 6, 1))] == [old.number]


def test_number_after_deleting_the_last_order_of_the_day_is_not_reused(tmp_path):
    """Protokół 02 mógł już trafić do klienta (albo zostać na dysku): nowe zlecenie nie dostaje 02."""
    clock = Clock(datetime(2026, 10, 11, 10, 0))
    with Journal(tmp_path / "j.db", now=clock) as j:
        j.create_order("S1", "M")
        second = j.create_order("S1", "M")
        j.delete_order(second.id)
        assert j.create_order("S1", "M").number == "ZS/2026/1011/03"
    with Journal(tmp_path / "j.db", now=clock) as j:
        last = j.create_order("S1", "M")
        j.delete_order(last.id)
        assert j.create_order("S1", "M").number == "ZS/2026/1011/05"


def test_deleted_rows_are_overwritten_on_disk(tmp_path):
    with Journal(tmp_path / "j.db") as j:
        order = j.create_order("S1", "M", "Klientka-Unikalna-Nazwa")
        j.delete_order(order.id)
    assert b"Klientka-Unikalna-Nazwa" not in (tmp_path / "j.db").read_bytes()
