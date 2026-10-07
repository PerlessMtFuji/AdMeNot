"""Klient serwera AdMeNot (spec backendu §4.1): tylko biblioteka standardowa, jeden typ błędu.

Proxy: `urllib` na Windows bierze ustawienia systemowe. Certyfikaty: `ssl` ładuje magazyn Windows,
więc w paczce PyInstallera nie potrzeba `certifi`.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Literal

from admenot import __version__

BASE_URL = "https://admenot.<subdomena>.workers.dev"
ENV_URL = "ADMENOT_API_URL"  # nadpisuje BASE_URL: testy, `wrangler dev`
TIMEOUT = 5.0  # sekundy; bez ponowień

Kind = Literal["offline", "http", "invalid"]


class BackendError(Exception):
    """offline: brak połączenia, DNS, TLS, timeout; http: kod ≠ 2xx; invalid: to nie obiekt JSON."""

    def __init__(self, kind: Kind, status: int | None = None) -> None:
        super().__init__(kind if status is None else f"{kind} {status}")
        self.kind = kind
        self.status = status


def base_url() -> str:
    return (os.environ.get(ENV_URL) or BASE_URL).rstrip("/")


def user_agent() -> str:
    return f"AdMeNot/{__version__}"  # nic więcej: bez systemu, języka, identyfikatorów


def _request(path: str, data: bytes | None = None) -> dict[str, Any]:
    headers = {"User-Agent": user_agent(), "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base_url() + path, data=data, headers=headers,
                                     method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:  # przed OSError: HTTPError to też URLError
        exc.close()
        raise BackendError("http", exc.code) from None
    except OSError:  # URLError, TimeoutError, błędy TLS, zerwane połączenie
        raise BackendError("offline") from None
    try:
        value = json.loads(raw)
    except ValueError:  # także UnicodeDecodeError — np. strona logowania do Wi-Fi
        raise BackendError("invalid") from None
    if not isinstance(value, dict):
        raise BackendError("invalid")
    return value


def get_json(path: str) -> dict[str, Any]:
    return _request(path)


def post_json(path: str, body: dict[str, Any]) -> dict[str, Any]:
    return _request(path, json.dumps(body).encode("utf-8"))
