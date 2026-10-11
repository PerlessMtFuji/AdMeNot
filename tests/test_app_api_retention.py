from datetime import timedelta

import pytest
from apphelpers import NOW, make_api
from conftest import SERIAL
from fakephone import make_cli_phone

from admenot.engine.journal.db import Journal
from admenot.engine.paths import journal_path, logs_dir
from admenot.engine.settings import save_settings

WLIVE = {"com.wlive.forecast": "disable"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))


def _repaired():
    phone = make_cli_phone()
    api, rec = make_api(phone)
    api.start_scan(SERIAL, "Anna")
    rec.wait_for("apk:done")
    api.execute(WLIVE, [])
    return api, rec.of("exec:order")[0]["order"]


def test_delete_order_from_history():
    api, number = _repaired()
    assert api.delete_order(number) == {"deleted": number}
    assert api.history()["orders"] == []
    assert api.delete_order(number)["error"]["key"] == "unknown_order"
    assert api.delete_order("  ")["error"]["key"] == "bad_request"


def _age(days):
    with Journal(journal_path()) as j:  # cofamy datę zlecenia
        j._db.execute("UPDATE orders SET created_at = ?",
                      ((NOW - timedelta(days=days)).isoformat(timespec="seconds"),))
        j._db.commit()


def test_default_retention_purges_orders_older_than_60_days_and_old_logs():
    _repaired()
    _age(61)
    old_log = logs_dir() / "2025-01-01.log"
    old_log.write_text("x", "utf-8")
    fresh, _ = make_api(make_cli_phone())  # bez ustawienia: domyślne 60 dni
    assert fresh.history(SERIAL)["orders"] == []
    assert not old_log.exists()


def test_default_retention_keeps_an_order_from_59_days_ago():
    _api, number = _repaired()
    _age(59)
    fresh, _ = make_api(make_cli_phone())
    assert [o["number"] for o in fresh.history(SERIAL)["orders"]] == [number]


def test_never_delete_keeps_old_orders():
    _api, number = _repaired()
    _age(400)
    save_settings({"retention_days": None})
    fresh, _ = make_api(make_cli_phone())
    assert [o["number"] for o in fresh.history(SERIAL)["orders"]] == [number]
