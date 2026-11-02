"""Składanie JPEG-ów z EXIF (w tym GPS i miniatura w IFD1) do testów eksploratora — bez binarnych fixtur."""

from __future__ import annotations

import io
import struct
from typing import Any

from PIL import Image

ASCII, SHORT, LONG, RATIONAL = 2, 3, 4, 5
Entry = tuple[int, int, Any]  # (tag, typ, wartość lub lista)


def _pack(typ: int, value: Any) -> tuple[int, bytes]:
    vals = value if isinstance(value, list) else [value]
    if typ == ASCII:
        data = str(value).encode() + b"\x00"
        return len(data), data
    if typ == SHORT:
        return len(vals), b"".join(struct.pack("<H", v) for v in vals)
    if typ == LONG:
        return len(vals), b"".join(struct.pack("<I", v) for v in vals)
    return len(vals), b"".join(struct.pack("<II", *v) for v in vals)  # RATIONAL: (licznik, mianownik)


def _ifd(entries: list[Entry], at: int, next_ifd: int, patch: dict[int, int]) -> bytes:
    """Jeden IFD zapisany od offsetu `at`; `patch` podmienia wartości LONG (wskaźniki do innych IFD)."""
    head = struct.pack("<H", len(entries))
    extra_at = at + 2 + 12 * len(entries) + 4
    body, extra = b"", b""
    for tag, typ, value in sorted(entries):
        if tag in patch:
            value = patch[tag]
        count, data = _pack(typ, value)
        if len(data) <= 4:
            body += struct.pack("<HHI", tag, typ, count) + data.ljust(4, b"\x00")
        else:
            body += struct.pack("<HHII", tag, typ, count, extra_at + len(extra))
            extra += data + (b"\x00" if len(data) % 2 else b"")
    return head + body + struct.pack("<I", next_ifd) + extra


def build_exif(ifd0: list[Entry], exif: list[Entry] | None = None, gps: list[Entry] | None = None,
               thumb: bytes | None = None) -> bytes:
    """Ładunek APP1 (`Exif\\0\\0` + TIFF little-endian); miniatura trafia do IFD1 (tagi 0x0201/0x0202)."""
    ifd0 = list(ifd0)
    if exif is not None:
        ifd0.append((0x8769, LONG, 0))
    if gps is not None:
        ifd0.append((0x8825, LONG, 0))
    ifd1: list[Entry] = []
    if thumb is not None:
        ifd1 = [(0x0201, LONG, 0), (0x0202, LONG, len(thumb))]
    # rozmiary nie zależą od wartości wskaźników, więc dwa przebiegi wystarczą
    patch: dict[int, int] = {}
    for _ in range(2):
        pos, parts, offsets = 8, [], {}
        for name, entries, nxt in (("ifd0", ifd0, None), ("exif", exif, 0), ("gps", gps, 0), ("ifd1", ifd1, 0)):
            if entries is None or (name == "ifd1" and not entries):
                continue
            offsets[name] = pos
            blob = _ifd(entries, pos, 0, patch)
            parts.append((name, blob))
            pos += len(blob)
        patch = {0x8769: offsets.get("exif", 0), 0x8825: offsets.get("gps", 0), 0x0201: pos}
        if "ifd1" in offsets:
            ifd0_blob = _ifd(ifd0, 8, offsets["ifd1"], patch)
            parts[0] = ("ifd0", ifd0_blob)
    tiff = b"II*\x00" + struct.pack("<I", 8) + b"".join(blob for _, blob in parts) + (thumb or b"")
    return b"Exif\x00\x00" + tiff


def segment(marker: int, payload: bytes) -> bytes:
    return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload


def jpeg_bytes(size: tuple[int, int] = (320, 240), color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def with_segments(jpeg: bytes, segments: list[bytes]) -> bytes:
    """Wstawia gotowe segmenty zaraz po SOI."""
    assert jpeg.startswith(b"\xff\xd8")
    return jpeg[:2] + b"".join(segments) + jpeg[2:]


def oppo_style_jpeg(thumb_color: tuple[int, int, int] = (10, 200, 10), orientation: int = 1) -> bytes:
    """Kształt zdjęcia z aparatu OPPO: APP1 z miniaturą w IFD1, potem duże APP5–APP8, SOF dopiero za 128 KiB."""
    thumb = jpeg_bytes((160, 120), thumb_color)
    exif = build_exif([(0x010F, ASCII, "OPPO"), (0x0112, SHORT, orientation)], thumb=thumb)
    big = [segment(m, b"\x00" * 65000) for m in (0xE5, 0xE6, 0xE7, 0xE8)]
    return with_segments(jpeg_bytes((640, 480)), [segment(0xE1, exif), *big])
