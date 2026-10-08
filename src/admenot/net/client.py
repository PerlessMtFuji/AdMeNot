"""Klient serwera AdMeNot (spec backendu §4.1): tylko biblioteka standardowa, jeden typ błędu.

Proxy: `urllib` na Windows bierze ustawienia systemowe. Certyfikaty: `ssl` ładuje magazyn Windows,
więc w paczce PyInstallera nie potrzeba `certifi`.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from admenot import __version__

BASE_URL = "https://admenot.e-wlodarski.workers.dev"
ENV_URL = "ADMENOT_API_URL"  # nadpisuje BASE_URL: testy, `wrangler dev`
TIMEOUT = 5.0  # sekundy; bez ponowień
DOWNLOAD_TIMEOUT = 30.0  # sekundy na operację gniazda przy pobieraniu instalatora
CHUNK = 64 * 1024

Kind = Literal["offline", "http", "invalid"]


class BackendError(Exception):
    """offline: brak połączenia, DNS, TLS, timeout; http: kod ≠ 2xx; invalid: to nie obiekt JSON."""

    def __init__(self, kind: Kind, status: int | None = None) -> None:
        super().__init__(kind if status is None else f"{kind} {status}")
        self.kind = kind
        self.status = status


class Cancelled(Exception):
    """Pobieranie przerwane przez `cancelled()`."""


class TooLarge(Exception):
    """Serwer wysłał więcej bajtów, niż pozwala `max_bytes` (np. przekierowanie na cudzy plik)."""


def base_url() -> str:
    return (os.environ.get(ENV_URL) or BASE_URL).rstrip("/")


def user_agent() -> str:
    return f"AdMeNot/{__version__}"  # nic więcej: bez systemu, języka, identyfikatorów


def _fetch(path: str, data: bytes | None = None) -> bytes:
    headers = {"User-Agent": user_agent(), "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        request = urllib.request.Request(base_url() + path, data=data, headers=headers,
                                         method="GET" if data is None else "POST")
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:  # przed OSError: HTTPError to też URLError
        exc.close()
        raise BackendError("http", exc.code) from None
    except (OSError, http.client.HTTPException, ValueError):  # URLError, TimeoutError, błędy TLS, zerwane połączenie, BadStatusLine, IncompleteRead, InvalidURL
        raise BackendError("offline") from None


def _request(path: str, data: bytes | None = None) -> dict[str, Any]:
    raw = _fetch(path, data)
    try:
        value = json.loads(raw)
    except ValueError:  # także UnicodeDecodeError — np. strona logowania do Wi-Fi
        raise BackendError("invalid") from None
    if not isinstance(value, dict):
        raise BackendError("invalid")
    return value


def get_bytes(path: str) -> bytes:
    """Surowa treść (manifest aktualizacji sprawdza sam podpis i format)."""
    return _fetch(path)


def get_json(path: str) -> dict[str, Any]:
    return _request(path)


def post_json(path: str, body: dict[str, Any]) -> dict[str, Any]:
    return _request(path, json.dumps(body).encode("utf-8"))


def _open_download(url: str) -> http.client.HTTPResponse:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    try:
        return urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise BackendError("http", exc.code) from None
    except (OSError, http.client.HTTPException, ValueError):
        raise BackendError("offline") from None


def download(url: str, dest: Path, on_progress: Callable[[int, int | None], None] | None = None,
             cancelled: Callable[[], bool] = lambda: False, max_bytes: int | None = None) -> None:
    """Pobiera pełny adres `url` (nie ścieżkę API) do `dest`, kawałkami.

    Sieć → `BackendError`, anulowanie → `Cancelled`, błąd dysku → `OSError` (bez przepakowania,
    żeby brak miejsca nie udawał braku sieci), więcej niż `max_bytes` → `TooLarge`.
    Przy każdym błędzie `dest` jest usuwany.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _open_download(url) as response, dest.open("wb") as out:
            length = response.headers.get("Content-Length")
            total = int(length) if length and length.isdigit() else None
            done = 0
            while True:
                try:
                    chunk = response.read(CHUNK)
                except (OSError, http.client.HTTPException, ValueError):
                    raise BackendError("offline") from None
                if not chunk:
                    break
                if cancelled():
                    raise Cancelled
                done += len(chunk)
                if max_bytes is not None and done > max_bytes:
                    raise TooLarge(f"więcej niż {max_bytes} B")  # zanim dysk się zapełni
                out.write(chunk)
                if on_progress is not None:
                    on_progress(done, total)
        if total is not None and done != total:
            raise BackendError("offline")  # serwer zerwał połączenie przed końcem pliku
    except BaseException:
        with contextlib.suppress(OSError):  # sprzątanie nie może zasłonić pierwotnego błędu
            dest.unlink(missing_ok=True)
        raise
