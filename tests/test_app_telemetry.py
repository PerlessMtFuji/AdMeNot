import json
import threading
from datetime import UTC, datetime, timedelta

import pytest

from admenot.app import telemetry
from admenot.engine.paths import telemetry_delete_path, telemetry_path
from admenot.engine.settings import load_settings, save_settings
from admenot.net.client import BackendError

NOW = datetime(2026, 10, 10, 14, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_settings({"lang": "pl"})


def body(with_packages):
    return {"apps": 3, "packages": ["x"] if with_packages else None}


def lines():
    path = telemetry_path()
    return [json.loads(x) for x in path.read_text("utf-8").splitlines()] if path.exists() else []


class Server:
    def __init__(self, fail=None):
        self.batches, self.deleted, self.fail = [], [], fail

    def post(self, path, payload):
        if self.fail:
            raise self.fail
        assert path == telemetry.ENDPOINT and payload["format"] == 1
        self.batches.append(payload["events"])
        return {"ok": True, "stored": len(payload["events"])}

    def delete(self, path):
        if self.fail:
            raise self.fail
        self.deleted.append(path.rsplit("/", 1)[1])
        return {"deleted": 1}


def consent(packages=False):
    return telemetry.set_consent(True, packages, NOW)


def test_without_consent_nothing_is_recorded():
    called = []
    telemetry.record("scan", lambda p: called.append(p) or body(p), now=lambda: NOW)
    assert not telemetry_path().exists() and called == []


def test_record_adds_common_fields_and_respects_package_consent():
    s = consent(packages=False)
    telemetry.record("scan", body, now=lambda: NOW)
    (e,) = lines()
    assert e["install"] == s.telemetry_id and e["type"] == "scan" and e["t"] == "2026-10-10T14:00:00Z"
    assert e["packages"] is None and e["lang"] == "pl"
    telemetry.set_consent(True, True, NOW)
    telemetry.record("scan", body, now=lambda: NOW)
    assert lines()[1]["packages"] == ["x"]


def test_exception_in_build_never_escapes():
    consent()

    def broken(_):
        raise RuntimeError("boom")

    telemetry.record("scan", broken, now=lambda: NOW)  # bez wyjątku
    assert lines() == []


def test_enabling_twice_keeps_the_id():
    first = consent().telemetry_id
    assert consent(packages=True).telemetry_id == first


def test_packages_need_basic_consent():
    s = telemetry.set_consent(False, True, NOW)
    assert (s.telemetry, s.telemetry_packages, s.telemetry_id) == (False, False, None)


def test_old_and_oversized_queue_is_trimmed(monkeypatch):
    consent()
    telemetry.record("scan", body, now=lambda: NOW - timedelta(days=31))
    telemetry.record("scan", body, now=lambda: NOW)
    assert [e["t"] for e in lines()] == ["2026-10-10T14:00:00Z"]
    monkeypatch.setattr(telemetry, "MAX_BYTES", 400)
    for _ in range(10):
        telemetry.record("scan", body, now=lambda: NOW)
    assert telemetry_path().stat().st_size <= 400


def test_future_events_are_kept():
    consent()
    telemetry.record("scan", body, now=lambda: NOW + timedelta(days=400))  # zły zegar w serwisie
    telemetry.record("scan", body, now=lambda: NOW)
    assert len(lines()) == 2


def test_corrupt_lines_are_dropped():
    consent()
    telemetry.record("scan", body, now=lambda: NOW)
    with telemetry_path().open("a", encoding="utf-8") as f:
        f.write('{"ucięty\n[1,2]\n')
    server = Server()
    telemetry.send_pending(post=server.post, delete=server.delete, now=lambda: NOW)
    assert len(server.batches) == 1 and len(server.batches[0]) == 1 and lines() == []


def test_sends_in_batches_of_100_and_empties_queue():
    consent()
    for _ in range(150):
        telemetry.record("scan", body, now=lambda: NOW)
    server = Server()
    telemetry.send_pending(post=server.post, delete=server.delete, now=lambda: NOW)
    assert [len(b) for b in server.batches] == [100, 50] and lines() == []


@pytest.mark.parametrize("error", [BackendError("offline"), BackendError("http", 429),
                                   BackendError("http", 503), BackendError("invalid")])
def test_unreachable_server_keeps_events(error):
    consent()
    telemetry.record("scan", body, now=lambda: NOW)
    telemetry.send_pending(post=Server(fail=error).post, delete=Server().delete, now=lambda: NOW)
    assert len(lines()) == 1


def test_rejected_batch_is_dropped():
    consent()
    telemetry.record("scan", body, now=lambda: NOW)
    telemetry.send_pending(post=Server(fail=BackendError("http", 400)).post,
                           delete=Server().delete, now=lambda: NOW)
    assert lines() == []


def test_events_of_old_install_are_dropped_unsent():
    old = consent().telemetry_id
    telemetry.record("scan", body, now=lambda: NOW)
    rows = lines()
    telemetry.set_consent(False, False, NOW)
    telemetry.set_consent(True, False, NOW)  # nowy ID
    telemetry_path().write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")  # wyścig z cofnięciem
    server = Server()
    telemetry.send_pending(post=server.post, delete=server.delete, now=lambda: NOW)
    assert server.batches == [] and lines() == [] and old in server.deleted


def test_withdraw_deletes_queue_and_schedules_delete():
    old = consent().telemetry_id
    telemetry.record("scan", body, now=lambda: NOW)
    s = telemetry.set_consent(False, False, NOW)
    assert s.telemetry_id is None and not telemetry_path().exists()
    assert telemetry.delete_pending()
    offline = Server(fail=BackendError("offline"))
    telemetry.send_pending(post=offline.post, delete=offline.delete, now=lambda: NOW)
    assert telemetry.delete_pending()  # czeka na sieć
    server = Server()
    telemetry.send_pending(post=server.post, delete=server.delete, now=lambda: NOW)
    assert server.deleted == [old] and not telemetry.delete_pending()


def test_delete_404_counts_as_done():
    consent()
    telemetry.set_consent(False, False, NOW)
    gone = Server(fail=BackendError("http", 404))
    telemetry.send_pending(post=gone.post, delete=gone.delete, now=lambda: NOW)
    assert not telemetry.delete_pending()


def test_turning_packages_off_strips_queued_packages():
    consent(packages=True)
    telemetry.record("scan", body, now=lambda: NOW)
    telemetry.set_consent(True, False, NOW)
    assert lines()[0]["packages"] is None


def test_start_event_once_per_utc_day():
    consent()
    save_settings({"mode": "expert"})
    telemetry.note_start("expert", NOW)
    telemetry.note_start("expert", NOW + timedelta(hours=5))
    telemetry.note_start("expert", NOW + timedelta(days=1))
    assert [e["type"] for e in lines()] == ["start", "start"]
    assert lines()[0]["mode"] == "expert" and load_settings().telemetry_start_day == "2026-10-11"


def test_corrupt_delete_list_is_ignored():
    telemetry_delete_path().parent.mkdir(parents=True, exist_ok=True)
    telemetry_delete_path().write_text("{zły", "utf-8")
    assert not telemetry.delete_pending()
    server = Server()
    telemetry.send_pending(post=server.post, delete=server.delete, now=lambda: NOW)  # bez wyjątku


def test_loop_stops_promptly():
    stop, wake = threading.Event(), threading.Event()
    thread = threading.Thread(target=telemetry._loop, args=(wake, stop), daemon=True)
    thread.start()
    stop.set()
    wake.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
