"""Miniatury obrazów (JPEG z miniatury EXIF, pierwsze 128 KiB, inaczej cały plik przez Pillow) i okładki muzyki."""

from __future__ import annotations

import io
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import PurePosixPath

from PIL import Image, ImageOps

from admenot.engine.explorer.meta import jpeg_thumbnail

__all__ = ["EXIF_HEAD", "FULL_IMAGE_LIMIT", "ThumbCache", "thumbnail"]

EXIF_HEAD = 131072  # 128 KiB: tyle czytamy w poszukiwaniu miniatury EXIF
FULL_IMAGE_LIMIT = 25 * 1024 * 1024
CACHE_LIMIT = 64 * 1024 * 1024
AUDIO_HEAD = 2 * 1024 * 1024  # okładka leży na początku pliku; większa zostaje bez miniatury
_JPEG = {".jpg", ".jpeg", ".jpe"}
_OTHER = {".png", ".webp", ".gif", ".bmp"}
_AUDIO = {".mp3", ".flac"}
_ID3_TEXT_UTF16 = (1, 2)  # kodowania z dwubajtowym końcem opisu
_TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


class ThumbCache:
    """LRU w pamięci ograniczony łącznym rozmiarem JPEG-ów."""

    def __init__(self, limit: int = CACHE_LIMIT) -> None:
        self.limit = limit
        self._items: OrderedDict[object, tuple[bytes, str]] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()

    def get(self, key: object) -> tuple[bytes, str] | None:
        with self._lock:
            item = self._items.get(key)
            if item is not None:
                self._items.move_to_end(key)
            return item

    def put(self, key: object, value: tuple[bytes, str]) -> None:
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self._size -= len(old[0])
            self._items[key] = value
            self._size += len(value[0])
            while self._size > self.limit and len(self._items) > 1:
                _, (dropped, _color) = self._items.popitem(last=False)
                self._size -= len(dropped)


def _encode(img: Image.Image, size: int) -> tuple[bytes, str]:
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        img = flat
    else:
        img = img.convert("RGB")
    img.thumbnail((size, size))
    r, g, b = img.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=80)
    return out.getvalue(), f"#{r:02x}{g:02x}{b:02x}"


def _from_exif(head: bytes, size: int) -> tuple[bytes, str] | None:
    found = jpeg_thumbnail(head)
    if found is None:
        return None
    blob, orientation = found
    try:
        with Image.open(io.BytesIO(blob)) as img:
            img.load()
            rotated = img.transpose(_TRANSPOSE[orientation]) if orientation in _TRANSPOSE else img
            return _encode(rotated, size)
    except Exception:  # noqa: BLE001 — uszkodzona miniatura: czytamy cały plik
        return None


def _from_full(data: bytes, size: int, jpeg: bool) -> tuple[bytes, str] | None:
    if not data:
        return None
    try:
        with Image.open(io.BytesIO(data)) as img:
            if jpeg:
                img.draft("RGB", (size * 2, size * 2))
            img.load()
            return _encode(ImageOps.exif_transpose(img), size)
    except Exception:  # noqa: BLE001 — nie obraz / uszkodzony plik: brak miniatury
        return None


def _syncsafe(raw: bytes) -> int:
    return (raw[0] << 21) | (raw[1] << 14) | (raw[2] << 7) | raw[3]


def _apic_image(body: bytes) -> bytes | None:
    """Obraz z ramki APIC: kodowanie, typ MIME, rodzaj, opis, dane."""
    mime_end = body.find(b"\0", 1)
    if mime_end < 0 or mime_end + 2 > len(body):
        return None
    start = mime_end + 2
    if body[0] in _ID3_TEXT_UTF16:
        at = start
        while at + 1 < len(body) and body[at:at + 2] != b"\0\0":
            at += 2
        return body[at + 2:]
    end = body.find(b"\0", start)
    return body[end + 1:] if end >= 0 else None


def _id3_cover(head: bytes) -> bytes | None:
    """Pierwsza ramka APIC znacznika ID3v2.3/2.4; urwany znacznik — brak okładki."""
    version = head[3]
    if version not in (3, 4) or len(head) < 10:
        return None
    end = min(10 + _syncsafe(head[6:10]), len(head))
    at = 10
    while at + 10 <= end and head[at] != 0:
        size = _syncsafe(head[at + 4:at + 8]) if version == 4 else int.from_bytes(head[at + 4:at + 8], "big")
        body = head[at + 10:at + 10 + size]
        if len(body) < size:
            return None
        if head[at:at + 4] == b"APIC":
            return _apic_image(body)
        at += 10 + size
    return None


def _flac_cover(head: bytes) -> bytes | None:
    """Blok PICTURE metadanych FLAC."""
    at = 4
    while at + 4 <= len(head):
        kind = head[at] & 0x7F
        last = head[at] & 0x80
        size = int.from_bytes(head[at + 1:at + 4], "big")
        block = head[at + 4:at + 4 + size]
        if kind == 6:
            if len(block) < size:
                return None
            mime = int.from_bytes(block[4:8], "big")
            desc = int.from_bytes(block[8 + mime:12 + mime], "big")
            data = 12 + mime + desc + 16
            return block[data + 4:data + 4 + int.from_bytes(block[data:data + 4], "big")]
        if last:
            return None
        at += 4 + size
    return None


def _cover(head: bytes) -> bytes | None:
    if head.startswith(b"ID3"):
        return _id3_cover(head)
    return _flac_cover(head) if head.startswith(b"fLaC") else None


def thumbnail(read_head: Callable[[int], bytes], read_all: Callable[[], bytes], size: int,
              name: str) -> tuple[bytes, str] | None:
    """(JPEG, kolor dominujący `#rrggbb`) albo None (filmy, muzyka bez okładki i reszta — klatkę filmu rysuje UI).

    `read_all` zwraca b"" dla pliku większego niż `FULL_IMAGE_LIMIT`."""
    ext = PurePosixPath(name).suffix.lower()
    if ext in _JPEG:
        head = read_head(EXIF_HEAD)
        return _from_exif(head, size) or _from_full(read_all(), size, jpeg=True)
    if ext in _OTHER:
        return _from_full(read_all(), size, jpeg=False)
    if ext in _AUDIO:
        art = _cover(read_head(AUDIO_HEAD))
        return _from_full(art, size, jpeg=False) if art else None
    return None
