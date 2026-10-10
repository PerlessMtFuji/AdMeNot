import json
from datetime import datetime, timedelta

import pytest

from admenot.engine import donate
from admenot.engine.journal.db import Order
from admenot.engine.paths import settings_path
from admenot.engine.settings import load_settings, save_internal
from admenot.engine.workflow import AppStatus, OrderResult

DAY = datetime(2026, 10, 10, 12, 0)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def _result(*statuses, stopped=False, order_status="done"):
    apps = [AppStatus(f"pkg{i}", status) for i, status in enumerate(statuses)]
    order = Order(1, "ZS/2026/1010/01", "SERIAL", None, None, DAY, order_status)
    return OrderResult(order=order, apps=apps, stopped=stopped)


@pytest.mark.parametrize(("statuses", "stopped", "expected"), [
    (("ok", "ok"), False, True),
    (("ok", "still_active"), False, False),
    (("ok", "failed"), False, False),
    (("ok",), True, False),
    ((), False, False),
])
def test_succeeded(statuses, stopped, expected):
    assert donate.succeeded(_result(*statuses, stopped=stopped)) is expected


def test_resume_after_a_failed_app_is_not_a_success():
    # `resume` zwraca tylko aplikacje z dokończonej części; o całości mówi status zlecenia
    assert donate.succeeded(_result("ok", order_status="failed")) is False


def test_first_reminder_after_the_first_successful_order():
    assert donate.note_success(DAY) is True
    s = load_settings()
    assert (s.donate_count, s.donate_shown_at) == (0, "2026-10-10")


def test_next_reminder_after_five_orders_once_fourteen_days_passed():
    donate.note_success(DAY)
    later = DAY + timedelta(days=20)
    assert [donate.note_success(later) for _ in range(5)] == [False, False, False, False, True]


def test_five_orders_within_fourteen_days_wait_for_the_first_order_after():
    donate.note_success(DAY)
    assert not any(donate.note_success(DAY + timedelta(days=1)) for _ in range(7))
    assert donate.note_success(DAY + timedelta(days=13)) is False
    assert donate.note_success(DAY + timedelta(days=14)) is True
    assert load_settings().donate_count == 0


def test_turned_off_never_reminds_and_turning_on_restores():
    donate.set_reminders(False)
    assert donate.note_success(DAY) is False
    assert load_settings().donate_count == 1
    assert donate.set_reminders(True).donate_off is False
    assert donate.note_success(DAY) is True


def test_reminder_date_in_the_future_counts_as_none():
    save_internal({"donate_shown_at": "2027-01-01"})
    assert donate.note_success(DAY) is True
    assert load_settings().donate_shown_at == "2026-10-10"


def test_impossible_date_counts_as_none():
    save_internal({"donate_shown_at": "2026-13-45"})  # przechodzi DAY_RE, ale nie istnieje
    assert donate.note_success(DAY) is True


def test_count_success_only_counts():
    donate.count_success()
    donate.count_success()
    s = load_settings()
    assert (s.donate_count, s.donate_shown_at) == (2, None)
    assert donate.note_success(DAY) is True  # pierwsze przypomnienie nadal czeka na GUI


def test_failed_save_never_raises(monkeypatch):
    def broken(changes, path=None):
        raise OSError("disk full")

    monkeypatch.setattr(donate, "save_internal", broken)
    assert donate.note_success(DAY) is False
    donate.count_success()


def test_settings_from_a_newer_program_are_left_alone():
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 99}), "utf-8")
    assert donate.note_success(DAY) is False
    donate.count_success()
    assert json.loads(path.read_text("utf-8")) == {"schema": 99}
