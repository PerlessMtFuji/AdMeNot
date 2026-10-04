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
    assert app_main.run_gui() == 0
    assert created["title"] == app_main.window_title() and created["url"] == str(web / "index.html")
    assert created["min_size"] == (1024, 700) and created["start"]["http_server"] is True
    assert created["closing"].__self__ is created["js_api"]


def test_cli_gui_command(monkeypatch):
    monkeypatch.setattr(app_main, "run_gui", lambda: 7)
    assert cli_main(["gui"]) == 7
