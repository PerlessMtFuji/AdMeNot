import threading

import pytest
from apphelpers import FakeScrcpy, make_api, mirror_factory
from conftest import SERIAL
from fakephone import make_cli_phone


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("DEMALWARE_ASSETS", str(tmp_path / "no-assets"))
    monkeypatch.setattr("shutil.which", lambda name: None)
    return tmp_path


def _api(fake=None, **kw):
    fake = fake or FakeScrcpy()
    api, rec = make_api(make_cli_phone(), mirror_factory=mirror_factory(fake), **kw)
    return fake, api, rec


def test_start_emits_states_and_logs_scrcpy_lines():
    fake, api, rec = _api()
    assert api.mirror_status() == {"available": True, "serial": None, "state": "stopped"}
    view = api.mirror_start(SERIAL, " Galaxy A14 ")
    assert view == {"serial": SERIAL, "state": "starting", "reason": None}
    assert fake.cmds[0][fake.cmds[0].index("--window-title") + 1] == "DeMalware — Galaxy A14"
    assert rec.wait_for("mirror:state") and api._mirror.status()["state"] in ("starting", "running")
    fake.procs[0].ended.set()
    api._mirror.wait()
    assert [e["state"] for e in rec.of("mirror:state")] == ["starting", "running", "stopped"]
    lines = [e for e in rec.of("adb:command") if e["tag"] == "scrcpy"]
    assert [e["command"] for e in lines] == FakeScrcpy.LINES
    assert {e["status"] for e in lines} == {"info"}


def test_title_falls_back_to_the_serial():
    fake, api, _rec = _api()
    api.mirror_start(SERIAL)
    assert fake.cmds[0][fake.cmds[0].index("--window-title") + 1] == f"DeMalware — {SERIAL}"
    api.mirror_stop()


def test_scrcpy_gets_the_same_adb_as_the_program():
    fake, api, _rec = _api()
    api.save_settings({"adb_path": "D:\\platform-tools\\adb.exe"})
    api.mirror_start(SERIAL)
    assert fake.envs[0]["ADB"] == "D:\\platform-tools\\adb.exe"
    api.mirror_stop()


def test_errors():
    _fake, api, _rec = _api(FakeScrcpy(available=False))
    assert api.mirror_status()["available"] is False
    assert api.mirror_start(SERIAL)["error"]["key"] == "mirror_missing"
    assert api.mirror_start("  ")["error"]["key"] == "bad_request"
    assert api.mirror_stop() == {"ok": True}


def test_start_rejects_a_non_string_name():
    fake, api, _rec = _api()
    assert api.mirror_start(SERIAL, 42)["error"]["key"] == "bad_request"
    assert fake.cmds == []


def test_stop_and_shutdown_kill_scrcpy():
    fake, api, rec = _api()
    api.mirror_start(SERIAL)
    assert api.mirror_stop() == {"ok": True}
    # zdarzenia mostu idą przez kolejkę/dyspozytora Mirror — poczekać, zanim sprawdzimy `rec`
    api._mirror.wait()
    assert rec.of("mirror:state")[-1] == {"serial": SERIAL, "state": "stopped", "reason": "closed"}
    api.mirror_start(SERIAL)
    api._shutdown()
    assert fake.procs[1].ended.is_set()
    assert api.mirror_status()["state"] == "stopped"


def test_mirror_survives_a_scan_and_an_order():
    fake, api, rec = _api(sync=True)
    api.mirror_start(SERIAL)
    api.start_scan(SERIAL)
    rec.wait_for("apk:done")
    api.execute({"com.wlive.forecast": "disable"}, [])
    rec.wait_for("exec:done")
    assert not fake.procs[0].ended.is_set()
    assert len(fake.procs) == 1
    assert api.mirror_status()["serial"] == SERIAL
    assert [e["state"] for e in rec.of("mirror:state")].count("stopped") == 0
    # Review Focus: adb nie jest restartowany, choć podgląd i skan/wykonanie dzielą ten sam adb
    commands = [e["command"] for e in rec.of("adb:command")]
    assert not any("kill-server" in c or "start-server" in c for c in commands)
    api.mirror_stop()


class _BlocksOnThreadEmitter:
    """Emiter do regresji na Critical 1: `emit()` wisi na zawsz, jeśli wywołany z wątku, który
    zamknął okno (`blocked_thread`) — tak zachowuje się `window.run_js`, kiedy czeka na wątek
    GUI, a to właśnie ten wątek próbuje w tej chwili zamknąć podgląd. Poprawka nie wywołuje
    już `on_state`/`on_warning` z tego wątku, więc `emit()` z niego nigdy nie powinno paść."""

    def __init__(self):
        self.blocked_thread: threading.Thread | None = None
        self.events: list[tuple[str, object]] = []
        self._lock = threading.Lock()

    def emit(self, name, detail=None):
        if threading.current_thread() is self.blocked_thread:
            threading.Event().wait()  # zawieszenie na zawsze — symulacja zakleszczenia z GUI
            return
        with self._lock:
            self.events.append((name, detail))


def test_closing_with_an_active_mirror_does_not_deadlock():
    fake, api, _rec = _api()
    api.mirror_start(SERIAL)
    blocker = _BlocksOnThreadEmitter()
    api._emitter = blocker
    result: dict[str, bool] = {}

    def run_closing():
        blocker.blocked_thread = threading.current_thread()
        result["ok"] = api._on_closing()

    thread = threading.Thread(target=run_closing)
    thread.start()
    thread.join(5.0)
    assert not thread.is_alive(), "_on_closing zawiesił się (deadlock GUI <-> podgląd)"
    assert result.get("ok") is True
    assert fake.procs[0].ended.wait(5)
