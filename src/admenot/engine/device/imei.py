"""IMEI przez `service call iphonesubinfo` (do protokołu zamiast numeru seryjnego adb).

Numer transakcji getDeviceId różni się między wersjami Androida, a interfejs ma same odczyty —
próbujemy kilku i ufamy tylko 15 cyfrom z poprawną sumą Luhna. Bez uprawnienia (nowsze
Androidy, część producentów) wynik to None i zostaje numer seryjny.
"""

from __future__ import annotations

import re

from admenot.engine.adb.transport import AdbError, AdbTransport

CODES = (1, 2, 3, 4)
COMMAND = "service call iphonesubinfo {code} s16 com.android.shell"
_WORDS = re.compile(r"0x[0-9a-f]+: ((?:[0-9a-f]{8} ?)+)")


def parse_parcel_string(text: str) -> str | None:
    """Parcel: status 0, długość, potem znaki UTF-16 po dwa w słowie (młodszy znak w młodszej połowie)."""
    words = [w for m in _WORDS.finditer(text) for w in m.group(1).split()]
    if len(words) < 3 or int(words[0], 16) != 0:
        return None
    length = int(words[1], 16)
    if length in (0, 0xFFFFFFFF):
        return None
    chars = []
    for w in words[2:]:
        value = int(w, 16)
        chars += [chr(value & 0xFFFF), chr(value >> 16)]
    text = "".join(chars[:length])
    return text if len(text) == length else None


def luhn_ok(number: str) -> bool:
    if len(number) != 15 or not number.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def read_imei(adb: AdbTransport) -> str | None:
    for code in CODES:
        try:
            value = parse_parcel_string(adb.shell(COMMAND.format(code=code)))
        except AdbError:
            continue
        if value and luhn_ok(value):
            return value
    return None
