import time

import pytest
from apphelpers import make_api
from conftest import SERIAL
from fakephone import make_cli_phone

from admenot.engine import share
from admenot.engine.journal.db import Journal
from admenot.engine.paths import journal_path
from admenot.net.client import BackendError

WLIVE = {"com.wlive.forecast": "disable"}
SID = "AbCdEfGhIjKlMnOpQrStUv"


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))
    monkeypatch.setenv("ADMENOT_API_URL", "https://admenot.test")


class Uploader:
    def __init__(self, fails: int = 0):
        self.fails = fails
        self.blobs: list[bytes] = []

    def __call__(self, blob: bytes) -> tuple[str, str]:
        self.blobs.append(blob)
        if self.fails:
            self.fails -= 1
            raise BackendError("offline")
        return SID, "2026-10-11T13:32:00Z"


def _scanned(uploader=None, **kw):
    api, rec = make_api(make_cli_phone(), share_upload=uploader or Uploader(),
                        share_retry_s=0.01, share_retry_window_s=0.5, **kw)
    api.start_scan(SERIAL, "Anna")
    rec.wait_for("apk:done")
    assert api._jobs.wait(5)
    rec.events.clear()
    return api, rec


def test_preview_carries_the_check_code():
    api, _ = _scanned()
    view = api.preview_plan(WLIVE, [])
    assert len(view["code"]) == 4 and set(view["code"]) <= set(share.CODE_ALPHABET)


def test_share_sends_encrypted_plan_and_emits_server_url():
    up = Uploader()
    api, rec = _scanned(up)
    code = api.preview_plan(WLIVE, [])["code"]
    assert api.share_plan(WLIVE, [], "ui-1") == {"share_id": "ui-1", "code": code}
    ready = rec.wait_for("share:ready")
    assert ready["share_id"] == "ui-1" and ready["mode"] == "server" and ready["code"] == code
    assert ready["url"].startswith(f"https://admenot.test/plan#s.{SID}.")
    assert ready["expires"] == "2026-10-11T13:32:00Z"
    key = ready["url"].rsplit(".", 1)[1]
    payload = share.decrypt(up.blobs[0], key)
    assert payload["code"] == code and payload["apps"][0]["l"] == "disable"
    # Bez analizy APK nazwą jest pakiet (spec §2); poza nazwą treść nie ma żadnych pól technicznych.
    assert all(set(app) <= {"n", "l", "b", "i"} for app in payload["apps"])


def test_offline_first_gives_local_url_then_upgrades_in_background():
    api, rec = _scanned(Uploader(fails=2), sync=False)
    api.share_plan(WLIVE, [], "ui-2")
    first = rec.wait_for("share:ready")
    assert first["mode"] == "local" and first["url"].startswith("https://admenot.test/plan#l.")
    assert first["expires"] is None
    rec.events.remove(("share:ready", first))
    second = rec.wait_for("share:ready")
    assert second["mode"] == "server" and second["share_id"] == "ui-2"


def test_offline_too_long_reports_failure(monkeypatch):
    monkeypatch.setattr(share, "LOCAL_LIMIT", 10)
    api, rec = _scanned(Uploader(fails=99))
    api.share_plan(WLIVE, [], "ui-3")
    failed = rec.wait_for("share:failed")
    assert failed == {"share_id": "ui-3", "code": api.preview_plan(WLIVE, [])["code"], "reason": "too_long"}


def test_cancel_stops_background_retries():
    up = Uploader(fails=10_000)
    api, rec = _scanned(up, sync=False)
    api.share_plan(WLIVE, [], "ui-4")
    rec.wait_for("share:ready")
    assert api.cancel_share() == {"ok": True}
    seen = len(up.blobs)
    time.sleep(0.1)
    assert len(up.blobs) <= seen + 1  # najwyżej jedna próba już w toku


def test_new_share_cancels_the_previous_one():
    up = Uploader(fails=10_000)
    api, rec = _scanned(up, sync=False)
    api.share_plan(WLIVE, [], "old")
    rec.wait_for("share:ready")
    api.share_plan(WLIVE, [], "new")  # najpierw anuluje stare ponawianie
    up.fails = 0
    deadline = time.monotonic() + 5
    while not [d for d in rec.of("share:ready") if d["mode"] == "server"] and time.monotonic() < deadline:
        time.sleep(0.01)
    ready = [d for d in rec.of("share:ready") if d["mode"] == "server"]
    assert ready and {d["share_id"] for d in ready} == {"new"}


def test_share_id_is_validated():
    api, _ = _scanned()
    assert api.share_plan(WLIVE, [], "../../x")["error"]["key"] == "bad_request"


def test_execute_with_matching_consent_stores_it_in_the_snapshot():
    api, rec = _scanned()
    api.share_plan(WLIVE, [], "ui-5")
    code = rec.wait_for("share:ready")["code"]
    api.execute(WLIVE, [], {"code": code})
    rec.wait_for("exec:done")
    with Journal(journal_path()) as journal:
        (order,) = journal.orders_for(SERIAL)
        consent = journal.scan(order.id)["consent"]
    assert consent["code"] == code
    assert consent["shown_at"] == "2026-09-26T14:30:00" and consent["confirmed_at"] == "2026-09-26T14:30:00"


def test_execute_with_stale_consent_changes_nothing():
    api, rec = _scanned()
    api.share_plan(WLIVE, [], "ui-6")
    rec.wait_for("share:ready")
    api.execute(WLIVE, [], {"code": "ZZZZ"})
    assert rec.wait_for("job:error")["key"] == "plan_changed"
    assert "exec:order" not in rec.names()
    assert api.history()["orders"] == []


def test_execute_with_consent_for_a_code_never_shown_is_plan_changed():
    api, rec = _scanned()
    code = api.preview_plan(WLIVE, [])["code"]
    api.execute(WLIVE, [], {"code": code})
    assert rec.wait_for("job:error")["key"] == "plan_changed"


def test_execute_without_consent_stores_nothing():
    api, rec = _scanned()
    api.execute(WLIVE, [])
    rec.wait_for("exec:done")
    with Journal(journal_path()) as journal:
        (order,) = journal.orders_for(SERIAL)
        assert "consent" not in journal.scan(order.id)
