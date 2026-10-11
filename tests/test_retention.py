from datetime import datetime, timedelta

import pytest

from admenot.engine import retention
from admenot.engine.journal.db import Journal
from admenot.engine.oplock import device_lock
from admenot.engine.paths import journal_path, logs_dir, reports_dir, screenshot_files

NOW = datetime(2026, 10, 11, 12, 0)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def _backup(tmp_path, name, package="com.ad"):
    folder = tmp_path / "backups" / "dev" / package / name
    folder.mkdir(parents=True)
    (folder / "base.apk").write_bytes(b"APK")
    (folder / ".complete").write_text("{}", "utf-8")
    return folder


def _order(j, folder, package="com.ad", status="done"):
    order = j.create_order("S1", "M")
    action = j.add_action(order.id, package, "remove",
                          {"kind": "installed", "package": package,
                           "params": {"installed": "0", "backup_dir": str(folder)}}, "pm uninstall")
    j.set_action_status(action, status)
    return order


def test_delete_order_removes_shots_report_and_its_backup(tmp_path):
    folder = _backup(tmp_path, "7")
    with Journal(journal_path(), now=lambda: NOW) as j:
        order = _order(j, folder)
        shot = j.add_screenshot("S1", {}, order.id)
        png, _ = screenshot_files(shot.id)
        png.parent.mkdir(parents=True)
        png.write_bytes(b"PNG")
        reports_dir().mkdir(parents=True)
        (reports_dir() / f"{order.number.replace('/', '-')}.pdf").write_bytes(b"%PDF")
        retention.delete_order(j, order)
        assert j.order_by_number(order.number) is None
    assert not png.exists() and not folder.exists() and list(reports_dir().iterdir()) == []


def test_shared_backup_survives_deleting_one_order(tmp_path):
    folder = _backup(tmp_path, "7")
    with Journal(journal_path(), now=lambda: NOW) as j:
        first, _second = _order(j, folder), _order(j, folder)
        retention.delete_order(j, first)
    assert folder.exists()


def test_backup_outside_the_expected_shape_is_left_alone(tmp_path):
    stranger = tmp_path / "Documents"
    stranger.mkdir()
    with Journal(journal_path(), now=lambda: NOW) as j:
        retention.delete_order(j, _order(j, stranger))
    assert stranger.exists()


def test_delete_order_survives_an_open_pdf(tmp_path):
    with Journal(journal_path(), now=lambda: NOW) as j:
        order = _order(j, _backup(tmp_path, "7"))
        reports_dir().mkdir(parents=True)
        pdf = reports_dir() / f"{order.number.replace('/', '-')}.pdf"
        pdf.write_bytes(b"%PDF")
        with pdf.open("rb"):  # Windows: plik otwarty w czytniku PDF nie da się usunąć
            retention.delete_order(j, order)
        assert j.order_by_number(order.number) is None


def test_purge_deletes_old_finished_orders_only(tmp_path):
    clock = {"t": NOW - timedelta(days=400)}
    with Journal(journal_path(), now=lambda: clock["t"]) as j:
        old = _order(j, _backup(tmp_path, "1"))
        pending = _order(j, _backup(tmp_path, "2"), status="pending")
        clock["t"] = NOW - timedelta(days=10)
        fresh = _order(j, _backup(tmp_path, "3"))
        assert retention.purge(j, NOW, 365) == [old.number]
        assert j.order_by_number(pending.number) and j.order_by_number(fresh.number)


def test_purge_skips_a_phone_busy_in_another_process(tmp_path):
    with Journal(journal_path(), now=lambda: NOW - timedelta(days=400)) as j:
        old = _order(j, _backup(tmp_path, "1"))
        with device_lock(j.path, "S1"):
            assert retention.purge(j, NOW, 365) == []
        assert j.order_by_number(old.number) is not None


def test_prune_logs_keeps_recent_and_foreign_files():
    logs_dir().mkdir(parents=True)
    names = ["2026-01-01.log", "app-2026-01-01.log", "2026-10-01.log", "app-2026-10-01.log", "notes.log"]
    for name in names:
        (logs_dir() / name).write_text("x", "utf-8")
    assert retention.prune_logs(logs_dir(), NOW, 90) == 2
    assert sorted(p.name for p in logs_dir().iterdir()) == sorted(names[2:])
