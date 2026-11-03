"""Dekodowanie tekstu do podglądu: BOM, potem UTF-8 (ścisłe), inaczej cp1250."""

from __future__ import annotations

import codecs

__all__ = ["TEXT_LIMIT", "decode_chunk", "decode_text"]

TEXT_LIMIT = 2 * 1024 * 1024
_UTF8_TAIL = 3  # ucięty na końcu wielobajtowy znak (podgląd czyta tylko początek pliku)
_BOMS = {b"\xef\xbb\xbf": "utf-8", b"\xff\xfe": "utf-16-le", b"\xfe\xff": "utf-16-be"}


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


def decode_chunk(data: bytes, codec: str | None = None, final: bool = True) -> tuple[str, str, int]:
    """Kolejny kawałek pliku do podglądu: (tekst, kodek, zużyte bajty).

    `codec` None — pierwszy kawałek: kodowanie jak w `decode_text`, BOM pominięty, a zwrócony kodek
    (`utf-8` / `utf-16-le` / `utf-16-be` / `cp1250`) podaje się przy następnych kawałkach. Niepełny
    znak na końcu (gdy nie `final`) nie jest zużyty — następny kawałek zaczyna się od niego."""
    skip = 0
    if codec is None:
        bom = next((b for b in _BOMS if data.startswith(b)), None)
        if bom is not None:
            codec, skip = _BOMS[bom], len(bom)
        else:
            codec = decode_text(data)[1]
    decoder = codecs.getincrementaldecoder(codec)(errors="replace")
    text = decoder.decode(data[skip:], final=final)
    pending = len(decoder.getstate()[0])
    return text, codec, len(data) - pending
