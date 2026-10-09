"""Wycinanie danych z raportów błędów (spec raportów błędów §4): czyste funkcje tekst → tekst.

Kolejność: ścieżka profilu → numery seryjne → IMEI → telefony → e-maile → nazwa konta.
Nazwy pakietów zostają (w tracebacku to kod programu; log ADB wysyłamy tylko za zgodą).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

ADB_LINE_LIMIT = 300
_MIN_SERIAL = 4
_COMMON_USERS = frozenset({"admin", "administrator", "user", "owner", "pc", "użytkownik"})
_IMEI = re.compile(r"(?<!\d)\d{14,17}(?!\d)")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d \-]{7,14}\d(?![\w.])")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_EMAIL = re.compile(r"[^\s@<>\"'(),;]+@[^\s@<>\"'(),;]+\.\w+")
_ANY_PROFILE = re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s\"']+", re.IGNORECASE)


def _phone(match: re.Match[str]) -> str:
    text = match.group(0)
    if _DATE.search(text) or sum(c.isdigit() for c in text) < 9:
        return text
    return "<phone>"


def redact(text: str, serials: Iterable[str] = (), home: str | None = None,
           user: str | None = None) -> str:
    home = str(Path.home()) if home is None else home
    user = os.environ.get("USERNAME", "") if user is None else user
    if home:
        for variant in sorted({home, home.replace("\\", "/")}, key=len, reverse=True):
            text = re.sub(re.escape(variant), "%USERPROFILE%", text, flags=re.IGNORECASE)
    text = _ANY_PROFILE.sub("%USERPROFILE%", text)  # krótkie nazwy 8.3 (JANKOW~1) i cudze profile
    for serial in sorted({s for s in serials if len(s) >= _MIN_SERIAL}, key=len, reverse=True):
        text = text.replace(serial, "<serial>")
    text = _IMEI.sub("<imei>", text)
    text = _PHONE.sub(_phone, text)
    text = _EMAIL.sub("<email>", text)
    if len(user) >= 3 and user.lower() not in _COMMON_USERS:
        text = re.sub(rf"(?<!\w){re.escape(user)}(?!\w)", "<user>", text, flags=re.IGNORECASE)
    return text


def adb_line(line: str, serials: Iterable[str] = (), home: str | None = None,
             user: str | None = None) -> str | None:
    """Wiersz logu sesji bez numeru seryjnego i daty (zostaje godzina), po wycięciu."""
    parts = line.rstrip("\r\n").split("\t")
    if len(parts) < 5:
        return None
    stamp, _serial, status, duration = parts[:4]
    clock = stamp[11:19] if len(stamp) >= 19 else stamp
    shown = f"{clock}\t{status}\t{duration}\t{'\t'.join(parts[4:])}"
    return redact(shown, serials, home, user)[:ADB_LINE_LIMIT]
