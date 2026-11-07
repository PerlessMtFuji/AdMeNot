"""Schowek Windows: lista plików i folderów po Ctrl+C w Eksploratorze Windows (`CF_HDROP`).

Wgrywanie na telefon przez Ctrl+V w eksploratorze plików (spec §5.5). Odczyt przez `ctypes`
(`OpenClipboard` / `GetClipboardData(CF_HDROP)` / `DragQueryFileW`) — pełne ścieżki, także z polskimi
znakami i foldery. Bez listy plików w schowku (tekst, obrazek, pusty, zajęty schowek) — pusta lista.
"""

from __future__ import annotations

import os
import time

__all__ = ["clipboard_files"]

CF_HDROP = 15
_ALL = 0xFFFFFFFF  # `DragQueryFileW(h, 0xFFFFFFFF, …)` zwraca liczbę plików
_OPEN_TRIES = 5  # schowek bywa chwilowo otwarty przez inny program
_OPEN_PAUSE = 0.02  # s


def clipboard_files() -> list[str]:
    """Pełne ścieżki plików i folderów skopiowanych w Eksploratorze Windows; brak → `[]`."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    # Własne instancje bibliotek: `argtypes` nie zmieniają współdzielonego `ctypes.windll`.
    user32 = ctypes.WinDLL("user32")
    shell32 = ctypes.WinDLL("shell32")
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT

    if not user32.IsClipboardFormatAvailable(CF_HDROP):
        return []
    for attempt in range(_OPEN_TRIES):
        if user32.OpenClipboard(None):
            break
        if attempt + 1 < _OPEN_TRIES:
            time.sleep(_OPEN_PAUSE)
    else:
        return []
    try:
        handle = user32.GetClipboardData(CF_HDROP)
        if not handle:
            return []
        paths: list[str] = []
        for i in range(shell32.DragQueryFileW(handle, _ALL, None, 0)):
            length = shell32.DragQueryFileW(handle, i, None, 0)
            if not length:
                continue
            buf = ctypes.create_unicode_buffer(length + 1)
            if shell32.DragQueryFileW(handle, i, buf, length + 1):
                paths.append(buf.value)
        return paths
    finally:
        user32.CloseClipboard()
