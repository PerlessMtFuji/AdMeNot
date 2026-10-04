"""VirusTotal API v3: wysyłka instalatora i wynik analizy (spec wydania §4.7).

Zawsze przez `upload_url` — instalator jest większy niż limit 32 MB zwykłej wysyłki.
Odpytywanie co 20 s mieści się w darmowym limicie 4 zapytań na minutę.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import secrets
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API = "https://www.virustotal.com/api/v3"
POLL_SECONDS = 20
TIMEOUT_SECONDS = 20 * 60


@dataclass(frozen=True)
class VtResult:
    link: str
    detections: int
    engines: int
    flagged: tuple[str, ...]


class VtError(Exception):
    pass


def http_request(method: str, url: str, headers: dict[str, str], body: bytes | None) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    # URLError i HTTPError to OSError; IncompleteRead itp. to HTTPException (spec §4.7: pominięte)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise VtError(str(exc)) from exc


def _multipart(filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = f"admenot{secrets.token_hex(16)}"
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def scan(path: Path, key: str, request=http_request, sleep=time.sleep, clock=time.monotonic) -> VtResult:
    headers = {"x-apikey": key, "accept": "application/json"}
    data = path.read_bytes()
    try:
        upload_url = request("GET", f"{API}/files/upload_url", headers, None)["data"]
        body, content_type = _multipart(path.name, data)
        analysis = request("POST", upload_url, {**headers, "content-type": content_type}, body)["data"]["id"]
        deadline = clock() + TIMEOUT_SECONDS
        while True:
            sleep(POLL_SECONDS)
            report = request("GET", f"{API}/analyses/{analysis}", headers, None)["data"]["attributes"]
            if report.get("status") == "completed":
                break
            if clock() > deadline:
                raise VtError(f"analiza {analysis} nie skończyła się w {TIMEOUT_SECONDS // 60} min")
        stats = report.get("stats", {})
        flagged = tuple(sorted(name for name, r in report.get("results", {}).items()
                               if r.get("category") in ("malicious", "suspicious")))
        detections = stats.get("malicious", 0) + stats.get("suspicious", 0)
        engines = detections + stats.get("undetected", 0) + stats.get("harmless", 0)
    except (KeyError, TypeError, AttributeError) as exc:
        raise VtError(f"nieoczekiwana odpowiedź VirusTotal: {exc!r}") from exc
    sha = hashlib.sha256(data).hexdigest()
    return VtResult(f"https://www.virustotal.com/gui/file/{sha}", detections, engines, flagged)
