import threading
from pathlib import Path

from admenot.engine import applabels
from admenot.engine.applabels import LabelFetch, PhoneLabel, list_apps, parse_list_apps

FIXTURE = Path(__file__).parent / "fixtures" / "scrcpy" / "list-apps-oppo-cph2271-4.1.txt"


class FakeProc:
    """scrcpy z rurą wyjścia; `hang` = procesy adb trzymają rurę, dopóki drzewo nie zginie."""

    pid = 4242

    def __init__(self, text: str = "", hang: bool = False) -> None:
        self.killed = threading.Event()
        self._lines = [line.encode("utf-8") + b"\r\n" for line in text.splitlines()]
        self._hang = hang

    @property
    def stdout(self):
        yield from self._lines
        if self._hang:
            self.killed.wait(10)


def _scrcpy(monkeypatch, tmp_path):
    monkeypatch.setattr(applabels, "resolve_scrcpy", lambda: tmp_path / "scrcpy.exe")


def test_parses_labels_from_scrcpy_output():
    labels = parse_list_apps(FIXTURE.read_text("utf-8"))
    assert {p: x.label for p, x in labels.items()} == {
        "com.android.chrome": "Chrome",
        "com.coloros.calculator": "Kalkulator",
        "com.Adblockerplus.ahmadprokhan": "Adblock Plus",
        "com.trusted.pdfeditor.pdfreader": "PDF Reader, PDF Viewer",  # bez wiodącej twardej spacji
        "com.thirtythreeapps.facefilters": "Śmieszne Filtry",
    }
    # …ale sztuczka „na górę listy” zostaje zapamiętana (DM-LABEL-02)
    assert [p for p, x in labels.items() if x.padded] == ["com.trusted.pdfeditor.pdfreader"]


def test_long_label_without_padding_still_splits_on_the_last_word():
    line = " - A very long application label that exceeds the column com.example.app"
    assert parse_list_apps(line) == {
        "com.example.app": PhoneLabel("A very long application label that exceeds the column", False)}


def test_passes_serial_and_the_programs_adb_and_logs_scrcpy_messages(monkeypatch, tmp_path):
    _scrcpy(monkeypatch, tmp_path)
    calls, log = [], []

    def spawn(cmd, env):
        calls.append((cmd, env["ADB"]))
        return FakeProc(FIXTURE.read_text("utf-8"))

    found = list_apps("SER1", "C:/adb.exe", threading.Event(), log.append, spawn=spawn)
    assert found["com.android.chrome"] == PhoneLabel("Chrome", False)
    assert calls == [([str(tmp_path / "scrcpy.exe"), "--serial", "SER1", "--list-apps"], "C:/adb.exe")]
    assert log[0].startswith("--list-apps") and log[-1] == "--list-apps: 5 nazw"
    assert not any("com.android.chrome" in line for line in log)  # wiersze listy nie zaśmiecają logu


def test_missing_scrcpy_or_spawn_error_means_no_labels(monkeypatch, tmp_path):
    monkeypatch.setattr(applabels, "resolve_scrcpy", lambda: None)
    assert list_apps("SER1", None, threading.Event(), spawn=lambda cmd, env: FakeProc()) == {}
    _scrcpy(monkeypatch, tmp_path)

    def broken(cmd, env):
        raise OSError("no exe")

    log = []
    assert list_apps("SER1", None, threading.Event(), log.append, spawn=broken) == {}
    assert log[-1] == "--list-apps: no exe"


def test_hung_scrcpy_is_killed_with_its_adb_children_after_the_timeout(monkeypatch, tmp_path):
    _scrcpy(monkeypatch, tmp_path)
    proc, killed, log = FakeProc("INFO: scrcpy 4.1", hang=True), [], []

    def kill(p):
        killed.append(p.pid)
        p.killed.set()  # taskkill /T zamyka rurę, którą trzymały procesy adb

    found = list_apps("SER1", None, threading.Event(), log.append,
                      spawn=lambda cmd, env: proc, kill=kill, timeout=0.3)
    assert found == {} and killed == [4242]
    assert log[-1] == "--list-apps: brak odpowiedzi po 0 s, przerwano"


def test_stop_kills_scrcpy_without_waiting_for_the_timeout(monkeypatch, tmp_path):
    _scrcpy(monkeypatch, tmp_path)
    proc, stop = FakeProc(hang=True), threading.Event()
    stop.set()
    found = list_apps("SER1", None, stop, spawn=lambda cmd, env: proc,
                      kill=lambda p: p.killed.set(), timeout=60)
    assert found == {} and proc.killed.is_set()


def test_label_fetch_reports_errors_and_returns_nothing():
    errors = []

    def boom(stop):
        raise TypeError("bug")

    fetch = LabelFetch(boom, errors.append)
    assert fetch.wait() == {}
    assert [str(e) for e in errors] == ["bug"]


def test_label_fetch_wait_checks_for_a_stopped_job_and_cancel_reaches_fetch():
    started = threading.Event()

    def slow(stop):
        started.set()
        stop.wait(10)
        return {"com.a": PhoneLabel("A", False)} if not stop.is_set() else {}

    fetch = LabelFetch(slow, lambda exc: None)
    started.wait(5)

    class Stopped(Exception):
        pass

    def check():
        raise Stopped

    try:
        fetch.wait(check)
    except Stopped:
        pass
    else:
        raise AssertionError("wait() nie sprawdził zatrzymania zadania")
    fetch.cancel()
    assert fetch.wait(timeout=5) == {} and not fetch.running
