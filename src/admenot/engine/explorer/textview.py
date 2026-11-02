"""Dekodowanie tekstu do podglądu: BOM, potem UTF-8 (ścisłe), inaczej cp1250."""

from __future__ import annotations

__all__ = ["TEXT_LIMIT", "decode_text"]

TEXT_LIMIT = 2 * 1024 * 1024
_UTF8_TAIL = 3  # ucięty na końcu wielobajtowy znak (podgląd czyta tylko początek pliku)


def decode_text(data: bytes) -> tuple[str, str]:
    """(tekst, kodowanie): `utf-8` / `utf-16` / `cp1250`."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace"), "utf-16"
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "utf-8"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError as exc:
        if exc.reason == "unexpected end of data" and exc.start >= len(data) - _UTF8_TAIL:
            return data[: exc.start].decode("utf-8"), "utf-8"
    return data.decode("cp1250", errors="replace"), "cp1250"
