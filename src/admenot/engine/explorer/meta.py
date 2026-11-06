"""Metadane plików dla eksploratora: EXIF (ręczny spacer po segmentach JPEG, bo głowa pliku jest ucięta)
i MediaStore (`content query`)."""

from __future__ import annotations

import struct
from collections.abc import Iterator
from typing import Any

from PIL import ExifTags, Image

from admenot.engine.explorer.guard import ExplorerAdb, safe_read_path
from admenot.engine.transfer.guard import CONTENT_TAIL, q
from admenot.engine.transfer.telephony import parse_content_rows

__all__ = ["exif_and_payload", "image_meta", "jpeg_thumbnail", "media_meta", "storage_path"]

_EXIF_HEADER = b"Exif\x00\x00"
_NO_LENGTH = {0x01, *range(0xD0, 0xDA)}  # TEM, RSTn, SOI, EOI: marker bez długości
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
_MEDIA_COLUMNS = ["_size", "duration", "width", "height", "bitrate", "mime_type", "datetaken",
                  "title", "artist", "album"]  # tekst dowolny na końcu (parser po ", <następna>=")
_MEDIA_URI = "content://media/external/file"
_ORIENTATION, _IFD1_OFFSET, _IFD1_LENGTH = 0x0112, 0x0201, 0x0202
_PIXEL_X, _PIXEL_Y = 0xA002, 0xA003
_MAX_TEXT = 256


def _segments(head: bytes) -> Iterator[tuple[int, int, int]]:
    """(marker, początek ładunku, koniec ładunku) kolejnych segmentów JPEG aż do SOS (włącznie) albo końca danych.

    Koniec ładunku może wykraczać poza `head` — segment jest wtedy niekompletny."""
    if not head.startswith(b"\xff\xd8"):
        return
    pos, n = 2, len(head)
    while pos + 1 < n:
        if head[pos] != 0xFF:
            return
        marker = head[pos + 1]
        if marker == 0xFF:  # wypełnienie
            pos += 1
            continue
        if marker in _NO_LENGTH:
            pos += 2
            continue
        if pos + 4 > n:
            return
        length = struct.unpack(">H", head[pos + 2:pos + 4])[0]
        yield marker, pos + 4, pos + 2 + length
        if marker == 0xDA:
            return
        pos += 2 + length


def exif_and_payload(head: bytes) -> tuple[Image.Exif, bytes] | None:
    """EXIF z kompletnego segmentu APP1 w `head` i jego ładunek (od nagłówka TIFF) albo None."""
    for marker, start, end in _segments(head):
        if marker == 0xE1 and head[start:start + 6] == _EXIF_HEADER:
            if end > len(head):
                return None  # APP1 nie mieści się w głowie
            payload = head[start + 6:end]
            exif = Image.Exif()
            try:
                exif.load(payload)
            except Exception:  # noqa: BLE001 — uszkodzony EXIF = brak EXIF
                return None
            return exif, payload
    return None


def jpeg_thumbnail(head: bytes) -> tuple[bytes, int] | None:
    """(JPEG miniatury z IFD1, orientacja głównego obrazu) albo None."""
    found = exif_and_payload(head)
    if found is None:
        return None
    exif, payload = found
    try:
        ifd1 = exif.get_ifd(ExifTags.IFD.IFD1)
    except Exception:  # noqa: BLE001
        return None
    offset, length = ifd1.get(_IFD1_OFFSET), ifd1.get(_IFD1_LENGTH)
    if not isinstance(offset, int) or not isinstance(length, int) or length <= 0:
        return None
    blob = payload[offset:offset + length]
    if len(blob) != length or not blob.startswith(b"\xff\xd8"):
        return None
    return blob, int(exif.get(_ORIENTATION, 1) or 1)


def _plain(value: Any) -> Any:
    if isinstance(value, bytes):
        return value[:_MAX_TEXT].decode("utf-8", errors="replace").rstrip("\x00") if len(value) <= _MAX_TEXT else None
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    try:
        return float(value)  # IFDRational
    except (TypeError, ValueError, ZeroDivisionError):
        return str(value)


def _deg(dms: Any, ref: Any) -> float | None:
    try:
        d, m, s = (float(x) for x in dms)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    value = d + m / 60 + s / 3600
    return -value if ref in ("S", "W") else value


def _gps(gps: dict[int, Any]) -> dict[str, Any] | None:
    lat, lon = _deg(gps.get(2), gps.get(1)), _deg(gps.get(4), gps.get(3))
    if lat is None or lon is None:
        return None
    alt: float | None = None
    if gps.get(6) is not None:
        try:
            alt = float(gps[6]) * (-1 if gps.get(5) in (1, b"\x01") else 1)
        except (TypeError, ValueError, ZeroDivisionError):
            alt = None
    return {"lat": lat, "lon": lon, "alt": alt}


def _sof_size(head: bytes) -> tuple[int, int] | None:
    for marker, start, end in _segments(head):
        if marker in _SOF and end <= len(head) and end - start >= 5:
            height, width = struct.unpack(">HH", head[start + 1:start + 5])
            return width, height
    return None


def image_meta(head: bytes) -> dict[str, Any]:
    """Wszystkie tagi EXIF (nazwy z `ExifTags`), `gps`, `width`, `height` — z początku pliku JPEG."""
    meta: dict[str, Any] = {"gps": None, "width": None, "height": None}
    found = exif_and_payload(head)
    if found is not None:
        exif = found[0]
        tags: dict[int, Any] = dict(exif)
        sub = exif.get_ifd(ExifTags.IFD.Exif)
        tags.update(sub)
        for tag, value in tags.items():
            if tag in (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo, ExifTags.IFD.Interop):
                continue
            plain = _plain(value)
            if plain is not None:
                meta[ExifTags.TAGS.get(tag, f"Tag{tag:04X}")] = plain
        gps_raw = exif.get_ifd(ExifTags.IFD.GPSInfo)
        for tag, value in gps_raw.items():
            plain = _plain(value)
            if plain is not None:
                meta[ExifTags.GPSTAGS.get(tag, f"GPSTag{tag:04X}")] = plain
        meta["gps"] = _gps(gps_raw)
        w, h = tags.get(_PIXEL_X), tags.get(_PIXEL_Y)
        if isinstance(w, int) and isinstance(h, int):
            meta["width"], meta["height"] = w, h
    if meta["width"] is None:
        size = _sof_size(head)
        if size is not None:
            meta["width"], meta["height"] = size
    return meta


def storage_path(path: str) -> str:
    """`/sdcard/…` -> ścieżka widoczna dla MediaStore (`/storage/emulated/0/…`)."""
    safe_read_path(path)
    return "/storage/emulated/0/" + path.removeprefix("/sdcard/")


def media_meta(adb: ExplorerAdb, path: str) -> dict[str, Any]:
    """Wiersz MediaStore dla pliku: czas trwania, wymiary, bitrate, tagi audio… (wartości dosłownie, NULL pomijane)."""
    where = "_data='" + storage_path(path).replace("'", "''") + "'"
    cmd = (f"content query --uri {_MEDIA_URI} --projection {':'.join(_MEDIA_COLUMNS)} "
           f"--where {q(where)}")
    rows = parse_content_rows(adb.shell(cmd + CONTENT_TAIL), _MEDIA_COLUMNS)
    if not rows:
        return {}
    meta = {k: v for k, v in rows[0].items() if v is not None}
    for key in ("_size", "duration", "width", "height", "bitrate", "datetaken"):
        if key in meta:
            try:
                meta[key] = int(meta[key])
            except (TypeError, ValueError):
                meta.pop(key)
    if "datetaken" in meta:
        meta["date_taken"] = meta.pop("datetaken")
    if "_size" in meta:
        meta["size"] = meta.pop("_size")
    return meta
