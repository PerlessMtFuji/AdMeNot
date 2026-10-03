import threading
from pathlib import Path

import pytest

from admenot.engine.mirror import Mirror, MirrorUnavailable, args_for

FIXTURES = Path(__file__).parent / "fixtures" / "scrcpy"
OPPO = (FIXTURES / "oppo-cph2271-4.1.txt").read_text("utf-8").splitlines()
FAILURE = (FIXTURES / "start-failure-4.1.txt").read_text("utf-8").splitlines()
# Nagrane na Redmi 22101316G (Android 13, MIUI) 2026-09-30 po kliknięciu w okno scrcpy.
BLOCKED = [("[server] ERROR: Injecting input events requires the caller (or the source of the "
            "instrumentation, if any) to have the INJECT_EVENTS permission."),
           ('[server] ERROR: Make sure you have enabled "USB debugging (Security Settings)" '
            "and then rebooted your device.")]
# Nagrane na realme RMX3474 (Android 12) 2026-09-30: przy monitorowaniu uprawnień ColorOS
# `--stay-awake` nie może zmienić ustawienia, a podgląd działa dalej.
STAY_AWAKE_DENIED = [
    "[server] ERROR: Could not invoke method",
    ("Caused by: java.lang.SecurityException: Permission denial: writing to settings requires:"
     "android.permission.WRITE_SECURE_SETTINGS"),
    '[server] ERROR: Could not change "stay_on_while_plugged_in"',
    ("com.genymobile.scrcpy.util.SettingsException: Could not access settings: "
     "global put stay_on_while_plugged_in 7"),
]
EXE = Path("C:/tools/scrcpy.exe")


class FakeProc:
    """Proces scrcpy: oddaje linie, potem „działa”, aż okno się zamknie albo `kill` go ubije."""

    def __init__(self, lines, code=0, ends=False):
        self.pid = 4242
        self.lines = [line.encode("utf-8") + b"\r\n" for line in lines]
        self.code = code
        self.ended = threading.Event()
        if ends:
            self.ended.set()
        self.killed = False

    @property
    def stdout(self):
        yield from self.lines
        self.ended.wait(5)

    def wait(self, timeout=None):
        self.ended.wait(5)
        return self.code

    def close_window(self, code=0):
        self.code = code
        self.ended.set()


class Harness:
    def __init__(self, *procs, available=True):
        self.procs = list(procs)
        self.spawned = []
        self.states, self.warnings, self.lines = [], [], []
        self.mirror = Mirror(self.states.append, self.warnings.append,
                             lambda serial, line: self.lines.append((serial, line)),
                             adb=lambda: "C:/tools/adb.exe",
                             scrcpy=lambda: EXE if available else None,
                             spawn=self.spawn, kill=self.kill)

    def spawn(self, cmd, env):
        self.spawned.append((cmd, env))
        return self.procs.pop(0)

    @staticmethod
    def kill(proc):
        proc.killed = True
        proc.close_window(code=1)  # taskkill: kod 1 (nagranie z 2026-09-29)

    def names(self):
        return [(s["state"], s["reason"]) for s in self.states]


def test_args_match_the_plan():
    assert args_for("S1", "AdMeNot — OPPO") == [
        "--serial", "S1", "--window-title", "AdMeNot — OPPO", "--no-audio",
        "--max-size", "1280", "--stay-awake"]


def test_first_frame_means_running_and_lines_reach_the_log():
    proc = FakeProc(OPPO)
    h = Harness(proc)
    view = h.mirror.start("S1", "AdMeNot — OPPO")
    assert view == {"serial": "S1", "state": "starting", "reason": None}
    cmd, env = h.spawned[0]
    assert cmd == [str(EXE), *args_for("S1", "AdMeNot — OPPO")]
    assert env["ADB"] == "C:/tools/adb.exe"
    proc.close_window(0)
    h.mirror.wait()
    assert h.names() == [("starting", None), ("running", None), ("stopped", "closed")]
    assert [line for _serial, line in h.lines] == OPPO
    assert h.mirror.status() == {"available": True, "serial": None, "state": "stopped"}


def test_unplugged_phone_is_stopped_not_failed():
    proc = FakeProc(OPPO)
    h = Harness(proc)
    h.mirror.start("S1", "t")
    proc.close_window(2)
    h.mirror.wait()
    assert h.names()[-1] == ("stopped", "disconnected")


def test_start_failure_reports_the_last_error_line():
    h = Harness(FakeProc(FAILURE, code=1, ends=True))
    h.mirror.start("NOPE", "t")
    h.mirror.wait()
    assert h.names() == [("starting", None), ("failed", "ERROR: Server connection failed")]


def test_failure_without_error_lines_reports_the_exit_code():
    h = Harness(FakeProc(["scrcpy 4.1"], code=3, ends=True))
    h.mirror.start("S1", "t")
    h.mirror.wait()
    assert h.names()[-1] == ("failed", "exit 3")


def test_blocked_control_warns_once_and_keeps_running():
    proc = FakeProc(OPPO + BLOCKED + BLOCKED)
    h = Harness(proc)
    h.mirror.start("S1", "t")
    proc.close_window(0)
    h.mirror.wait()
    assert h.warnings == [{"serial": "S1", "code": "control_blocked"}]
    assert ("failed", None) not in h.names() and h.names()[-1] == ("stopped", "closed")


def test_stay_awake_denied_warns_once_and_keeps_running():
    proc = FakeProc(OPPO[:1] + STAY_AWAKE_DENIED + OPPO[1:] + STAY_AWAKE_DENIED)
    h = Harness(proc)
    h.mirror.start("S1", "t")
    proc.close_window(0)
    h.mirror.wait()
    assert h.warnings == [{"serial": "S1", "code": "stay_awake_blocked"}]
    assert ("running", None) in h.names() and h.names()[-1] == ("stopped", "closed")


def test_both_warnings_come_once_each():
    proc = FakeProc(STAY_AWAKE_DENIED + OPPO + BLOCKED + STAY_AWAKE_DENIED + BLOCKED)
    h = Harness(proc)
    h.mirror.start("S1", "t")
    proc.close_window(0)
    h.mirror.wait()
    assert [w["code"] for w in h.warnings] == ["stay_awake_blocked", "control_blocked"]


def test_stop_kills_and_reports_stopped_exactly_once():
    proc = FakeProc(OPPO)
    h = Harness(proc)
    h.mirror.start("S1", "t")
    h.mirror.stop()
    h.mirror.wait()
    assert proc.killed
    assert h.names().count(("stopped", "closed")) == 1
    assert ("failed", "exit 1") not in h.names()  # kod 1 po taskkill to nie błąd
    h.mirror.stop()  # drugi raz: nic się nie dzieje
    assert h.names().count(("stopped", "closed")) == 1


def test_start_twice_for_the_same_phone_spawns_once():
    proc = FakeProc(OPPO)
    h = Harness(proc)
    first = h.mirror.start("S1", "t")
    second = h.mirror.start("S1", "t")
    assert len(h.spawned) == 1 and first["serial"] == second["serial"] == "S1"
    h.mirror.stop()


def test_start_for_another_phone_stops_the_first():
    first, second = FakeProc(OPPO), FakeProc(OPPO)
    h = Harness(first, second)
    h.mirror.start("S1", "t")
    h.mirror.start("S2", "t")
    # S2 zostaje naprawdę uruchomiony (test nie zamyka jego okna), więc dołączenie do jego
    # wątku wyczerpałoby cały timeout; krótki timeout + wait() i tak potwierdza opróżnienie
    # kolejki po zdarzeniu S1 (`stopped`), zanim sprawdzimy `h.states`.
    h.mirror.wait(0.3)
    assert first.killed and not second.killed
    assert {"serial": "S1", "state": "stopped", "reason": "closed"} in h.states
    assert h.mirror.status()["serial"] == "S2"
    h.mirror.stop()


def test_missing_scrcpy():
    h = Harness(available=False)
    assert h.mirror.available() is False
    assert h.mirror.status() == {"available": False, "serial": None, "state": "stopped"}
    with pytest.raises(MirrorUnavailable):
        h.mirror.start("S1", "t")


def test_spawn_error_is_a_failed_state():
    h = Harness()

    def broken(cmd, env):
        raise OSError("[WinError 2] The system cannot find the file specified")

    h.mirror._spawn = broken
    view = h.mirror.start("S1", "t")
    h.mirror.wait()
    assert view["state"] == "failed" and "WinError 2" in view["reason"]
    assert h.mirror.status()["state"] == "stopped"


def test_state_callbacks_never_run_on_the_caller_thread_and_do_not_deadlock():
    """Regresja na Critical 1 z przeglądu Task 7: most woła `on_state`/`on_warning` przez
    `window.run_js`, które czeka na wątek GUI. Gdyby te callbacki szły z wątku, który wywołał
    `start()`/`stop()` (albo z wątku czytającego pod `_lock`), a wątek GUI próbowałby w tym
    czasie zamknąć podgląd, powstałoby zakleszczenie. `on_state` tutaj samo wywołuje
    `status()` (bierze `_lock`) — musi to przejść bez zawieszenia, nawet z wątku dyspozytora."""
    caller = threading.current_thread()
    seen: list[threading.Thread] = []
    reached_stopped = threading.Event()

    def on_state(view):
        seen.append(threading.current_thread())
        mirror.status()  # nie może się zakleszczyć, choć bierze `_lock`
        if view["state"] == "stopped":
            reached_stopped.set()

    def kill(proc):
        proc.code = 1
        proc.ended.set()

    proc = FakeProc(OPPO)
    mirror = Mirror(on_state, lambda _v: None, lambda _s, _l: None,
                    adb=lambda: "C:/tools/adb.exe", scrcpy=lambda: EXE,
                    spawn=lambda cmd, env: proc, kill=kill)
    mirror.start("S1", "t")
    proc.close_window(0)
    mirror.wait()
    assert reached_stopped.wait(5)
    assert seen and caller not in seen
    assert all(t.name == "admenot-mirror-events" for t in seen)
