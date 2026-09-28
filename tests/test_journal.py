from datetime import datetime

import pytest

from demalware.engine.journal.db import Journal
from demalware.engine.paths import backups_dir, journal_path, logs_dir


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
    assert journal_path() == tmp_path / "DeMalware" / "journal.db"
    assert backups_dir() == tmp_path / "DeMalware" / "backups"
    assert logs_dir() == tmp_path / "DeMalware" / "logs"


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
    with Journal(path) as j:
        assert j.order(order.id).number == order.number
        j.save_scan(order.id, {"apps": []})
        assert j.scan(order.id) == {"apps": []}
