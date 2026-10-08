import threading

import pytest
from updatehelpers import signed

from admenot.app.updates import UpdateService, update_view
from admenot.net import client, update


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def service(fetch, *, enabled=lambda: True, version="0.9.2", **kw):
    changes = []
    svc = UpdateService(lambda: changes.append(svc.state()), enabled, fetch=fetch, version=version, **kw)
    return svc, changes


def test_check_stores_and_reports_a_new_version(signing_key):
    svc, changes = service(lambda: update.verify(signed(signing_key)))
    assert svc.state().available is False
    st = svc.check_now()
    assert st.available and update.cached() is not None and len(changes) == 1
    svc.check_now()
    assert len(changes) == 1  # bez zmiany stanu — bez zdarzenia


def test_offline_keeps_the_cached_state(signing_key):
    update.store(update.verify(signed(signing_key, min_supported="9.0.0")))

    def offline():
        raise client.BackendError("offline")

    svc, changes = service(offline)
    assert svc.state().retired
    assert svc.check_now().retired and changes == []


def test_bad_manifest_is_logged_and_ignored(tmp_path):
    def bad():
        raise update.ManifestError("zły podpis")

    svc, _ = service(bad)
    assert svc.check_now().manifest is None
    (log,) = (tmp_path / "AdMeNot" / "logs").glob("app-*.log")
    assert "zły podpis" in log.read_text("utf-8")


def test_loop_checks_after_the_first_delay(signing_key):
    called = threading.Event()

    def fetch():
        called.set()
        return update.verify(signed(signing_key))

    svc, _ = service(fetch, first_delay=0.0, interval=3600)
    svc.start()
    try:
        assert called.wait(5)
    finally:
        svc.stop()


def test_disabled_check_makes_no_requests():
    asked = threading.Event()
    fetched = []

    def enabled():
        asked.set()
        return False

    svc, _ = service(lambda: fetched.append(True), enabled=enabled, first_delay=0.0, interval=3600)
    svc.start()
    try:
        assert asked.wait(5)
        asked.clear()
        svc.poke()
        assert asked.wait(5)
    finally:
        svc.stop()
    assert fetched == []


def test_view_for_ui(signing_key):
    m = update.verify(signed(signing_key, min_supported="9.0.0",
                             min_reason={"pl": "Błąd cofania", "en": "Undo bug"}))
    view = update_view(update.state(m, "0.9.2"), "pl", dismissed=None, updated_to=None,
                       installable=True)
    assert view == {"available": {"version": "9.9.9", "notes": "Poprawki.", "size": 1234},
                    "dismissed": False,
                    "retired": {"min_supported": "9.0.0", "reason": "Błąd cofania"},
                    "updated_to": None, "updated_notes": None, "installable": True}


def test_view_dismissed_and_updated(signing_key):
    m = update.verify(signed(signing_key))
    assert update_view(update.state(m, "0.9.2"), "en", dismissed="9.9.9", updated_to=None,
                       installable=False)["dismissed"] is True
    view = update_view(update.state(m, "9.9.9"), "en", dismissed=None, updated_to="9.9.9",
                       installable=True)
    assert view["available"] is None and view["updated_notes"] == "Fixes."
    empty = update_view(update.state(None, "0.9.2"), "pl", dismissed="9.9.9", updated_to=None,
                        installable=True)
    assert empty["available"] is None and empty["dismissed"] is False


@pytest.mark.parametrize("broken", ["fetch", "enabled"])
def test_loop_survives_an_unexpected_error(signing_key, broken):
    calls = []
    second = threading.Event()

    def boom():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("pełny dysk")

    def fetch():
        if broken == "fetch":
            boom()
        second.set()
        return update.verify(signed(signing_key))

    def enabled():
        if broken == "enabled":
            boom()
        return True

    svc, _ = service(fetch, enabled=enabled, first_delay=0.0, interval=3600)
    svc.start()
    try:
        deadline = threading.Event()
        while not calls and not deadline.wait(0.01):
            pass
        assert not second.is_set()
        svc.poke()
        assert second.wait(5)
    finally:
        svc.stop()
