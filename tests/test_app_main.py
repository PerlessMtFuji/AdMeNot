import subprocess
import sys

import pytest

from admenot.app import main as app_main
from admenot.cli.main import main as cli_main


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))


def test_missing_ui_build(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(app_main, "WEB_DIR", tmp_path / "web")
    assert app_main.run_gui() == 2
    err = capsys.readouterr().err
    assert "build_ui.ps1" in err


def test_missing_pywebview(monkeypatch, tmp_path, capsys):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html>", "utf-8")
    monkeypatch.setattr(app_main, "WEB_DIR", web)
    monkeypatch.setitem(sys.modules, "webview", None)
    assert app_main.run_gui() == 4
    assert "pip install" in capsys.readouterr().err


def test_window_is_created_with_the_api(monkeypatch, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html>", "utf-8")
    monkeypatch.setattr(app_main, "WEB_DIR", web)
    created = {}

    class Events:
        def __init__(self):
            self.closing = self

        def __iadd__(self, handler):
            created["closing"] = handler
            return self

    class Window:
        def __init__(self):
            self.events = Events()

        def destroy(self):
            pass

    class FakeWebview:
        class FileDialog:
            FOLDER = "folder"

        @staticmethod
        def create_window(title, **kw):
            created.update(kw, title=title)
            return Window()

        @staticmethod
        def start(**kw):
            created["start"] = kw

    monkeypatch.setitem(sys.modules, "webview", FakeWebview)
    started = []
    monkeypatch.setattr(app_main.Api, "_start_updates", lambda self: started.append(self))
    assert app_main.run_gui() == 0
    assert created["title"] == app_main.window_title() and created["url"] == str(web / "index.html")
    assert created["min_size"] == (1024, 700) and created["start"]["http_server"] is True
    assert created["closing"].__self__ is created["js_api"]
    assert started == [created["js_api"]]  # wątek aktualizacji startuje tylko z prawdziwego okna


def test_cli_gui_command(monkeypatch):
    monkeypatch.setattr(app_main, "run_gui", lambda: 7)
    assert cli_main(["gui"]) == 7


def test_frozen_build_shows_startup_errors_in_a_window(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(app_main, "WEB_DIR", tmp_path / "web")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    shown = []
    monkeypatch.setattr(app_main, "_message_box", shown.append)
    assert app_main.run_gui() == 2
    assert len(shown) == 1 and str(tmp_path / "web") in shown[0]
    assert capsys.readouterr().err == ""


def test_frozen_build_reports_a_missing_webview2_in_a_window(monkeypatch, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html>", "utf-8")
    monkeypatch.setattr(app_main, "WEB_DIR", web)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    shown = []
    monkeypatch.setattr(app_main, "_message_box", shown.append)

    class Closing:
        def __iadd__(self, handler):  # `window.events.closing += …` w run_gui
            return self

    class Window:
        def __init__(self):
            self.events = type("Events", (), {"closing": Closing()})()

        def destroy(self):
            pass

    class FakeWebview:
        class FileDialog:
            FOLDER = "folder"

        @staticmethod
        def create_window(title, **kw):
            return Window()

        @staticmethod
        def start(**kw):
            raise RuntimeError("WebView2 not found")

    monkeypatch.setitem(sys.modules, "webview", FakeWebview)
    assert app_main.run_gui() == 3
    assert "WebView2" in shown[0] and "developer.microsoft.com" in shown[0]


def test_main_gives_a_windowed_process_writable_std_streams(monkeypatch):
    # AdMeNot.exe (console=False) ma sys.stdout = None; proces analizy APK dziedziczy to przez
    # freeze_support, a androguard przy imporcie bierze sys.stdout.write (próba wydania 0.9.0)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    seen = {}
    monkeypatch.setattr(app_main.multiprocessing, "freeze_support",
                        lambda: seen.update(out=sys.stdout, err=sys.stderr))
    monkeypatch.setattr(app_main, "run_gui", lambda: 0)
    with pytest.raises(SystemExit):
        app_main.main()
    seen["out"].write("x")
    seen["err"].write("x")


def test_androguard_imports_without_a_console():
    code = ("import sys; sys.stdout = sys.stderr = None\n"
            "from admenot.app.main import ensure_std_streams; ensure_std_streams()\n"
            "import androguard.core.apk\n")
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def _fake_webview(monkeypatch, tmp_path, start):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html>", "utf-8")
    monkeypatch.setattr(app_main, "WEB_DIR", web)

    class Closing:
        def __iadd__(self, handler):
            return self

    class Window:
        def __init__(self):
            self.events = type("Events", (), {"closing": Closing()})()

        def destroy(self):
            pass

    class FakeWebview:
        class FileDialog:
            FOLDER = "folder"

        @staticmethod
        def create_window(title, **kw):
            return Window()

        @staticmethod
        def start(**kw):
            start()

    monkeypatch.setitem(sys.modules, "webview", FakeWebview)
    monkeypatch.setattr(app_main.Api, "_start_updates", lambda self: None)


def _record_session(monkeypatch):
    seen = []
    monkeypatch.setattr(app_main.crash, "claim_session", lambda: seen.append("claim") or True)
    monkeypatch.setattr(app_main.crash, "recover", lambda now=None: seen.append("recover"))
    monkeypatch.setattr(app_main.crash, "start_session", lambda now=None: seen.append("start"))
    monkeypatch.setattr(app_main.crash, "install_hooks", lambda: seen.append("hooks"))
    monkeypatch.setattr(app_main.crash, "end_session", lambda: seen.append("end"))
    return seen


def test_gui_session_order_on_clean_exit(monkeypatch, tmp_path):
    seen = _record_session(monkeypatch)
    _fake_webview(monkeypatch, tmp_path, start=lambda: seen.append("window"))
    assert app_main.run_gui() == 0
    assert seen == ["claim", "recover", "start", "hooks", "window", "end"]


def test_gui_session_ends_even_when_webview_fails(monkeypatch, tmp_path):
    seen = _record_session(monkeypatch)

    def broken():
        raise RuntimeError("WebView2 not found")

    _fake_webview(monkeypatch, tmp_path, start=broken)
    assert app_main.run_gui() == 3
    assert seen[-1] == "end"


def test_real_session_leaves_no_marker(monkeypatch, tmp_path):
    import threading

    from admenot.engine.paths import crashes_dir

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)  # install_hooks nie może wyciec
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    _fake_webview(monkeypatch, tmp_path, start=lambda: None)
    assert app_main.run_gui() == 0
    assert not (crashes_dir() / "running.json").exists()


def test_missing_ui_creates_no_session(monkeypatch, tmp_path):
    seen = _record_session(monkeypatch)
    monkeypatch.setattr(app_main, "WEB_DIR", tmp_path / "missing")
    assert app_main.run_gui() == 2
    assert seen == []


def test_second_instance_skips_recover_and_start_but_installs_hooks(monkeypatch, tmp_path):
    seen = _record_session(monkeypatch)
    monkeypatch.setattr(app_main.crash, "claim_session", lambda: seen.append("claim") or False)
    _fake_webview(monkeypatch, tmp_path, start=lambda: seen.append("window"))
    assert app_main.run_gui() == 0
    assert seen == ["claim", "hooks", "window", "end"]
