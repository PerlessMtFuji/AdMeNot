"""Okno programu liczy na oszczędnej karcie, gdy komputer ma dwie.

WebView sam wybiera mocniejszą. Na laptopie z RTX 3050 Ti szybkie otwieranie i przybliżanie zdjęć 12 Mpx
zawieszało jego proces GPU w sterowniku NVIDII: okno spadało do klatki na sekundę, a gra na tej samej karcie
i kompozytor Windows klatkowały, aż strażnik WebView ubił proces. Na karcie zintegrowanej problem nie
występuje, a gra zachowuje swoją kartę dla siebie.
"""

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable, MutableMapping, Sequence
from ctypes import wintypes
from typing import NamedTuple

BROWSER_ARGS = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
ADAPTER_SWITCH = "--use-adapter-luid"

Luid = tuple[int, int]  # część wysoka, niska: tak (dziesiętnie) czyta je Chromium


class Adapter(NamedTuple):
    luid: Luid
    software: bool


def pick(adapters: Sequence[Adapter], preferred: Luid | None) -> Luid | None:
    """Oszczędna karta, gdy jest z czego wybierać: przy jednej prawdziwej nic nie zmieniamy."""
    real = [adapter.luid for adapter in adapters if not adapter.software]
    return preferred if len(real) > 1 and preferred in real else None


def prefer_low_power_gpu(env: MutableMapping[str, str] | None = None,
                         read: Callable[[], Luid | None] | None = None) -> None:
    """Dopisuje wybór karty do argumentów WebView. Błąd odczytu nigdy nie zatrzymuje programu."""
    env = os.environ if env is None else env
    current = env.get(BROWSER_ARGS, "")
    if ADAPTER_SWITCH in current:
        return
    try:
        luid = (read or low_power_adapter)()
    except (OSError, ValueError, AttributeError):
        return
    if luid is not None:
        env[BROWSER_ARGS] = f"{current} {ADAPTER_SWITCH}={luid[0]},{luid[1]}".strip()


class _Guid(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]


class _AdapterDesc(ctypes.Structure):
    """DXGI_ADAPTER_DESC1."""

    _fields_ = [("description", ctypes.c_wchar * 128), ("vendor", wintypes.UINT), ("device", wintypes.UINT),
                ("subsystem", wintypes.UINT), ("revision", wintypes.UINT), ("video", ctypes.c_size_t),
                ("system", ctypes.c_size_t), ("shared", ctypes.c_size_t), ("luid_low", wintypes.DWORD),
                ("luid_high", wintypes.LONG), ("flags", wintypes.UINT)]


def _guid(a: int, b: int, c: int, *d: int) -> _Guid:
    return _Guid(a, b, c, (ctypes.c_ubyte * 8)(*d))


_FACTORY6 = _guid(0xC1B6694F, 0xFF09, 0x44A9, 0xB0, 0x3C, 0x77, 0x90, 0x0A, 0x0A, 0x1D, 0x17)
_ADAPTER1 = _guid(0x29038F61, 0x3839, 0x4626, 0x91, 0xFD, 0x08, 0x68, 0x79, 0x01, 0x1A, 0x05)

# Numery metod w tablicach COM (dxgi1_6.h).
_RELEASE = 2
_ENUM_ADAPTERS1 = 12
_ENUM_BY_PREFERENCE = 29
_GET_DESC1 = 10
_MINIMUM_POWER = 1
_FLAG_SOFTWARE = 2


def _method(this: ctypes.c_void_p, index: int, *argtypes: object) -> Callable[..., int]:
    table = ctypes.cast(this, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    function = prototype(table[index])
    return lambda *args: function(this, *args)


def _release(this: ctypes.c_void_p) -> None:
    _method(this, _RELEASE)()


def _describe(adapter: ctypes.c_void_p) -> Adapter:
    desc = _AdapterDesc()
    if _method(adapter, _GET_DESC1, ctypes.POINTER(_AdapterDesc))(ctypes.byref(desc)) < 0:
        raise OSError("GetDesc1")
    return Adapter((desc.luid_high, desc.luid_low), bool(desc.flags & _FLAG_SOFTWARE))


def low_power_adapter() -> Luid | None:
    """Identyfikator oszczędnej karty albo None: jedna karta, inny system, stary Windows bez IDXGIFactory6."""
    if sys.platform != "win32":
        return None
    factory = ctypes.c_void_p()
    create = ctypes.WinDLL("dxgi").CreateDXGIFactory1
    if create(ctypes.byref(_FACTORY6), ctypes.byref(factory)) < 0 or not factory:
        return None
    try:
        adapters: list[Adapter] = []
        enum = _method(factory, _ENUM_ADAPTERS1, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))
        while True:
            adapter = ctypes.c_void_p()
            if enum(len(adapters), ctypes.byref(adapter)) < 0 or not adapter:
                break  # DXGI_ERROR_NOT_FOUND: koniec listy
            try:
                adapters.append(_describe(adapter))
            finally:
                _release(adapter)
        chosen = ctypes.c_void_p()
        by_preference = _method(factory, _ENUM_BY_PREFERENCE, wintypes.UINT, wintypes.UINT,
                                ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p))
        if by_preference(0, _MINIMUM_POWER, ctypes.byref(_ADAPTER1), ctypes.byref(chosen)) < 0 or not chosen:
            return None
        try:
            return pick(adapters, _describe(chosen).luid)
        finally:
            _release(chosen)
    finally:
        _release(factory)
