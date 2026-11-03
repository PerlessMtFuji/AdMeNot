from __future__ import annotations

import shlex
from pathlib import Path

import pytest
from exifbuild import (
    ASCII,
    LONG,
    RATIONAL,
    SHORT,
    build_exif,
    jpeg_bytes,
    oppo_style_jpeg,
    segment,
    with_segments,
)
from faketransfer import FakeStoragePhone, write_provider

from admenot.engine.explorer.guard import ExplorerAdb
from admenot.engine.explorer.meta import image_meta, media_meta
from admenot.engine.explorer.textview import decode_chunk, decode_text


def photo(**kw) -> bytes:
    gps = [(1, ASCII, "N"), (2, RATIONAL, [(52, 1), (13, 1), (472, 10)]),
           (3, ASCII, "E"), (4, RATIONAL, [(21, 1), (0, 1), (421, 10)])]
    exif = [(0x829A, RATIONAL, (1, 250)), (0x829D, RATIONAL, (18, 10)), (0x8827, SHORT, 200),
            (0x9003, ASCII, "2026:10:05 14:03:09"), (0xA002, LONG, 4000), (0xA003, LONG, 3000)]
    payload = build_exif([(0x010F, ASCII, "OPPO"), (0x0110, ASCII, "CPH2005")], exif, gps)
    return with_segments(jpeg_bytes(), [segment(0xE1, payload)])


def test_image_meta_gps_decimal():
    gps = image_meta(photo())["gps"]
    assert gps["lat"] == pytest.approx(52.229778, abs=1e-6)
    assert gps["lon"] == pytest.approx(21.011694, abs=1e-6)
    assert gps["alt"] is None


def test_image_meta_all_tags():
    meta = image_meta(photo())
    assert meta["Make"] == "OPPO" and meta["Model"] == "CPH2005"
    assert meta["FNumber"] == pytest.approx(1.8)
    assert meta["ExposureTime"] == pytest.approx(0.004)
    assert meta["ISOSpeedRatings"] == 200
    assert meta["DateTimeOriginal"] == "2026:10:05 14:03:09"
    assert (meta["width"], meta["height"]) == (4000, 3000)
    assert meta["GPSLatitudeRef"] == "N"


def test_image_meta_southern_western_and_altitude():
    gps = [(1, ASCII, "S"), (2, RATIONAL, [(10, 1), (30, 1), (0, 1)]),
           (3, ASCII, "W"), (4, RATIONAL, [(20, 1), (0, 1), (0, 1)]), (6, RATIONAL, (1234, 10))]
    data = with_segments(jpeg_bytes(), [segment(0xE1, build_exif([], None, gps))])
    got = image_meta(data)["gps"]
    assert got == pytest.approx({"lat": -10.5, "lon": -20.0, "alt": 123.4})


def test_image_meta_oppo_shape_uses_segment_walk_not_truncated_open():
    data = oppo_style_jpeg()
    meta = image_meta(data[:131072])
    assert meta["Make"] == "OPPO"
    assert meta["width"] is None  # SOF dopiero za głową, brak EXIF PixelXDimension


def test_image_meta_width_from_sof_without_exif():
    meta = image_meta(jpeg_bytes((321, 123)))
    assert (meta["width"], meta["height"], meta["gps"]) == (321, 123, None)


def test_image_meta_garbage_is_empty():
    assert image_meta(b"not a jpeg") == {"gps": None, "width": None, "height": None}


def where_of(phone: FakeStoragePhone) -> str:
    argv = shlex.split(phone.commands[-1].removesuffix(" 2>&1"))
    return argv[argv.index("--where") + 1]


# ---- MediaStore ------------------------------------------------------------------------------
def test_media_meta_from_mediastore(tmp_path: Path):
    phone = FakeStoragePhone(tmp_path)
    cols = ["_size", "duration", "width", "height", "bitrate", "mime_type", "datetaken", "title", "artist", "album"]
    write_provider(tmp_path, "content://media/external/file", [
        {"_size": "5000", "duration": "61000", "width": "1920", "height": "1080", "bitrate": "8000000",
         "mime_type": "video/mp4", "datetaken": "1760000000000", "title": "Wesele, część 1", "artist": None,
         "album": "Rodzina"}], cols)
    meta = media_meta(ExplorerAdb(phone), "/sdcard/DCIM/Camera/VID_1.mp4")
    assert meta["duration"] == "61000" and meta["width"] == "1920" and meta["bitrate"] == "8000000"
    assert meta["title"] == "Wesele, część 1" and meta["album"] == "Rodzina" and "artist" not in meta
    assert meta["mime_type"] == "video/mp4" and meta["date_taken"] == "1760000000000"
    assert where_of(phone) == "_data='/storage/emulated/0/DCIM/Camera/VID_1.mp4'"


def test_media_meta_quotes_apostrophes_and_handles_no_row(tmp_path: Path):
    phone = FakeStoragePhone(tmp_path)
    write_provider(tmp_path, "content://media/external/file", [], ["_size"])
    assert media_meta(ExplorerAdb(phone), "/sdcard/Music/It's \"a\" $x `y`.mp3") == {}
    assert where_of(phone) == "_data='/storage/emulated/0/Music/It''s \"a\" $x `y`.mp3'"


# ---- tekst -----------------------------------------------------------------------------------
def test_decode_text_utf8():
    assert decode_text("zażółć gęślą jaźń".encode()) == ("zażółć gęślą jaźń", "utf-8")
    assert decode_text(b"\xef\xbb\xbfabc") == ("abc", "utf-8")
    assert decode_text("zażółć".encode()[:-1]) == ("zażół", "utf-8")  # ucięty znak na końcu limitu


def test_decode_text_cp1250():
    assert decode_text("zażółć gęślą jaźń".encode("cp1250")) == ("zażółć gęślą jaźń", "cp1250")


def test_decode_text_utf16_bom():
    assert decode_text("zażółć".encode("utf-16")) == ("zażółć", "utf-16")
    assert decode_text(b"\xfe\xff" + "ą".encode("utf-16-be")) == ("ą", "utf-16")


@pytest.mark.parametrize(("data", "codec"), [
    ("Zażółć\r\ngęślą".encode(), "utf-8"),
    (b"\xef\xbb\xbf" + "Zażółć gęślą".encode(), "utf-8"),
    (b"\xff\xfe" + "Zażółć gęślą".encode("utf-16-le"), "utf-16-le"),
    (b"\xfe\xff" + "Zażółć gęślą".encode("utf-16-be"), "utf-16-be"),
    ("Zażółć gęślą".encode("cp1250"), "cp1250"),
])
def test_decode_chunk_in_pieces_matches_whole(data, codec):
    """Kawałki po 5 bajtów (granica w środku znaku i BOM-u) składają się w ten sam tekst."""
    whole = decode_chunk(data)[0]
    text, used_codec, pos = "", None, 0
    while pos < len(data):
        piece = data[pos:pos + 5]
        part, used_codec, used = decode_chunk(piece, used_codec, final=pos + len(piece) >= len(data))
        text, pos = text + part, pos + used
        assert used > 0
    assert text == whole and used_codec == codec and "\ufffd" not in text
