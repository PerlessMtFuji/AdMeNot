"""Okno programu: pywebview (WebView2) + zbudowane UI z `app/web/` (spec §2, §3).

Uruchomienie: `admenot gui` albo `admenot-gui`. UI buduje `scripts/build_ui.ps1`.
"""

from __future__ import annotations

import faulthandler
import multiprocessing
import os
import sys
import threading
from pathlib import Path
from typing import Any

from admenot import __version__
from admenot.app import crash
from admenot.app.api import Api
from admenot.app.events import WindowEmitter
from admenot.engine.settings import effective_lang, load_settings

WEB_DIR = Path(__file__).resolve().parent / "web"
WINDOW = {"width": 1280, "height": 800, "min_size": (1024, 700)}

MESSAGES = {
    "pl": {
        "no_ui": "Brak zbudowanego interfejsu ({path}). Uruchom: "
                 "powershell -ExecutionPolicy Bypass -File scripts/build_ui.ps1",
        "no_webview": "Brak modułu pywebview. Zainstaluj: .venv\\Scripts\\pip install -e .[gui]",
        "no_webview2": "Nie udało się otworzyć okna ({error}). Zainstaluj Microsoft Edge WebView2 "
                       "Runtime: https://developer.microsoft.com/microsoft-edge/webview2/",
    },
    "en": {
        "no_ui": "The interface is not built ({path}). Run: "
                 "powershell -ExecutionPolicy Bypass -File scripts/build_ui.ps1",
        "no_webview": "The pywebview module is missing. Install: .venv\\Scripts\\pip install -e .[gui]",
        "no_webview2": "Could not open the window ({error}). Install Microsoft Edge WebView2 "
                       "Runtime: https://developer.microsoft.com/microsoft-edge/webview2/",
    },
}

MB_ICONERROR = 0x10


def _message_box(text: str) -> None:
    import ctypes

    ctypes.windll.user32.MessageBoxW(None, text, "AdMeNot", MB_ICONERROR)


def _fail(text: str) -> None:
    """Spakowany program nie ma konsoli — komunikat w oknie Windows (spec wydania §8)."""
    if getattr(sys, "frozen", False):
        _message_box(text)
    else:
        print(text, file=sys.stderr)


def window_title(version: str = __version__) -> str:
    """„beta" w tytule, dopóki główny numer wersji to 0 (spec wydania §2)."""
    return f"AdMeNot {version} beta" if version.startswith("0.") else f"AdMeNot {version}"


def run_gui() -> int:
    lang = effective_lang(load_settings())
    text = MESSAGES[lang]
    index = WEB_DIR / "index.html"
    if not index.is_file():
        _fail(text["no_ui"].format(path=WEB_DIR))
        return 2
    try:
        import webview
    except ImportError:
        _fail(text["no_webview"])
        return 4
    if crash.claim_session():  # druga instancja nie rusza cudzego znacznika
        crash.recover()
        crash.start_session()
    crash.install_hooks()
    if os.environ.get(crash.CRASH_TEST) == "fatal":  # próba ręczna (spec raportów §10.2)
        timer = threading.Timer(5.0, faulthandler._sigsegv)
        timer.daemon = True
        timer.start()
    try:
        holder: dict[str, Any] = {}
        api = Api(WindowEmitter(lambda: holder.get("window")))
        # http_server=True: moduły ES z file:// są w Chromium blokowane
        window = webview.create_window(window_title(), url=str(index), js_api=api,
                                       background_color="#eef2f6", **WINDOW)
        holder["window"] = window

        def pick_folder() -> str | None:
            chosen = window.create_file_dialog(webview.FileDialog.FOLDER)
            return chosen[0] if chosen else None

        def pick_file() -> str | None:
            chosen = window.create_file_dialog(
                webview.FileDialog.OPEN,
                file_types=("Logo (*.png;*.jpg;*.jpeg;*.webp;*.svg)",))
            return chosen[0] if chosen else None

        api._attach(pick_folder=pick_folder, close=window.destroy, pick_file=pick_file)
        api._start_updates()
        window.events.closing += api._on_closing
        try:
            webview.start(gui="edgechromium", http_server=True)
        except Exception as exc:  # noqa: BLE001 — np. brak WebView2 na Windows 10
            _fail(text["no_webview2"].format(error=exc))
            return 3
        return 0
    finally:
        crash.end_session()


def ensure_std_streams() -> None:
    """AdMeNot.exe (console=False) nie ma konsoli: sys.stdout/stderr to None, a androguard przy
    imporcie bierze `sys.stdout.write` — bez tego w paczce padała analiza manifestu każdej aplikacji."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115 — do końca procesu


def main() -> None:
    ensure_std_streams()  # przed freeze_support: proces analizy APK startuje właśnie stąd
    multiprocessing.freeze_support()  # PyInstaller + `spawn`: bez tego proces potomny otwiera drugie okno
    raise SystemExit(run_gui())
