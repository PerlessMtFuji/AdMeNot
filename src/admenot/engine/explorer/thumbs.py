"""Miniatury obrazów: JPEG z miniatury EXIF (pierwsze 128 KiB), inaczej cały plik przez Pillow."""

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
_JPEG = {".jpg", ".jpeg", ".jpe"}
_OTHER = {".png", ".webp", ".gif", ".bmp"}
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


def thumbnail(read_head: Callable[[int], bytes], read_all: Callable[[], bytes], size: int,
              name: str) -> tuple[bytes, str] | None:
    """(JPEG, kolor dominujący `#rrggbb`) albo None (filmy i nieobrazy — klatkę rysuje UI).

    `read_all` zwraca b"" dla pliku większego niż `FULL_IMAGE_LIMIT`."""
    ext = PurePosixPath(name).suffix.lower()
    if ext in _JPEG:
        head = read_head(EXIF_HEAD)
        return _from_exif(head, size) or _from_full(read_all(), size, jpeg=True)
    if ext in _OTHER:
        return _from_full(read_all(), size, jpeg=False)
    return None
