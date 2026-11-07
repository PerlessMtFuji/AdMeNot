from __future__ import annotations

import http.client
import io
import socket
import subprocess
import threading
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from exifbuild import oppo_style_jpeg
from faketransfer import FakeStoragePhone
from PIL import Image

from admenot.engine.explorer.guard import ExplorerAdb, stream_args
from admenot.engine.explorer.media import MediaServer, parse_range, socket_stream, stat_size
from admenot.engine.explorer.meta import _segments
from admenot.engine.explorer.thumbs import EXIF_HEAD, ThumbCache, thumbnail

APP = "http://127.0.0.1:5555"
DATA = bytes(i * 7 % 251 for i in range(300_000))


class CountingStream(io.BytesIO):
    def __init__(self, data: bytes, log: list[int], opened: list[int]) -> None:
        super().__init__(data)
        self.log = log
        self.closed_flag = False

    def read(self, n: int | None = -1) -> bytes:
        chunk = super().read(n)
        self.log.append(len(chunk))
        return chunk

    read1 = read

    def close(self) -> None:
        self.closed_flag = True
        super().close()


@pytest.fixture
def phone(tmp_path: Path) -> FakeStoragePhone:
    p = FakeStoragePhone(tmp_path)
    p.local("/sdcard/DCIM").mkdir(parents=True)
    p.local("/sdcard/DCIM/clip.bin").write_bytes(DATA)
    return p


@pytest.fixture
def served(phone):
    adb = ExplorerAdb(phone)
    read_log: list[int] = []
    opened: list[tuple[str, int]] = []
    streams: list[CountingStream] = []

    def open_stream(path: str, start: int):
        opened.append((path, start))
        s = CountingStream(adb.run_bytes(stream_args(path, start)), read_log, [])
        streams.append(s)
        return s

    server = MediaServer("adb", "FAKE", lambda origin: origin == APP, open_stream=open_stream,
                         size_of=lambda path: stat_size(adb, path))
    base = server.start()
    server.read_log, server.opened, server.streams = read_log, opened, streams
    yield server, base
    server.stop()


def get(url: str, headers: dict[str, str] | None = None, method: str = "GET"):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        return urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as exc:
        return exc


def test_full_get(served):
    server, _ = served
    r = get(server.file_url("/sdcard/DCIM/clip.bin"))
    assert r.status == 200
    assert r.headers["Accept-Ranges"] == "bytes"
    assert r.headers["Content-Length"] == str(len(DATA))
    assert r.read() == DATA


def test_range_206_middle(served):
    server, _ = served
    r = get(server.file_url("/sdcard/DCIM/clip.bin"), {"Range": "bytes=1000-1999"})
    assert r.status == 206
    assert r.headers["Content-Range"] == f"bytes 1000-1999/{len(DATA)}"
    assert r.read() == DATA[1000:2000]


def test_range_far_offset_skips_blocks_and_kills_stream(served):
    server, _ = served
    start = 200_000 + 123
    r = get(server.file_url("/sdcard/DCIM/clip.bin"), {"Range": f"bytes={start}-{start + 99}"})
    assert r.read() == DATA[start:start + 100]
    assert server.opened[-1] == ("/sdcard/DCIM/clip.bin", start)
    assert server.streams[-1].closed_flag


def test_range_open_end_and_suffix(served):
    server, _ = served
    url = server.file_url("/sdcard/DCIM/clip.bin")
    r = get(url, {"Range": "bytes=299000-"})
    assert (r.status, r.read()) == (206, DATA[299000:])
    r = get(url, {"Range": "bytes=-500"})
    assert (r.status, r.headers["Content-Range"], r.read()) == (206, f"bytes 299500-299999/{len(DATA)}", DATA[-500:])


def test_range_unsatisfiable_416(served):
    server, _ = served
    r = get(server.file_url("/sdcard/DCIM/clip.bin"), {"Range": "bytes=999999-"})
    assert r.status == 416
    assert r.headers["Content-Range"] == f"bytes */{len(DATA)}"


def test_head(served):
    server, _ = served
    r = get(server.file_url("/sdcard/DCIM/clip.bin"), method="HEAD")
    assert r.status == 200 and r.read() == b""
    assert r.headers["Content-Length"] == str(len(DATA))
    assert server.opened == []  # HEAD nie otwiera strumienia


def test_parse_range_variants():
    assert parse_range("bytes=0-0", 10) == (0, 0)
    assert parse_range("bytes=5-100", 10) == (5, 9)
    assert parse_range("bytes=-3", 10) == (7, 9)
    assert parse_range("bytes=-0", 10) == "unsatisfiable"
    assert parse_range("bytes=10-", 10) == "unsatisfiable"
    assert parse_range("bytes=0-1,4-5", 10) is None
    assert parse_range(None, 10) is None


def test_bad_token_404(served):
    _, base = served
    host = base.rsplit("/", 1)[0]
    assert get(f"{host}/wrong/file?p=%2Fsdcard%2FDCIM%2Fclip.bin").status == 404
    assert get(f"{host}/wrong/file?p=%2Fsdcard%2FDCIM%2Fclip.bin", method="OPTIONS").status == 404


def test_missing_file_and_unsafe_path(served):
    server, _ = served
    assert get(server.file_url("/sdcard/DCIM/nope.bin")).status == 404
    assert get(server.file_url("/etc/passwd")).status == 400
    assert get(server.file_url("/sdcard/../etc/passwd")).status == 400


def test_cors_only_for_app_origin(served):
    server, _ = served
    url = server.file_url("/sdcard/DCIM/clip.bin")
    ok = get(url, {"Origin": APP, "Range": "bytes=0-9"})
    assert ok.headers["Access-Control-Allow-Origin"] == APP
    assert "Content-Range" in ok.headers["Access-Control-Expose-Headers"]
    assert "X-Color" in ok.headers["Access-Control-Expose-Headers"]
    ok.read()
    other = get(url, {"Origin": "http://evil.example", "Range": "bytes=0-9"})
    assert "Access-Control-Allow-Origin" not in other.headers
    other.read()
    assert "Access-Control-Allow-Origin" not in get(url, {"Range": "bytes=0-9"}).headers
    pre = get(url, {"Origin": APP, "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "range"}, method="OPTIONS")
    assert pre.status == 204
    assert pre.headers["Access-Control-Allow-Origin"] == APP
    assert pre.headers["Access-Control-Allow-Headers"] == "Range"
    pre_bad = get(url, {"Origin": "http://evil.example"}, method="OPTIONS")
    assert "Access-Control-Allow-Origin" not in pre_bad.headers


def test_client_abort_is_quiet_and_kills_stream(served, capfd):
    server, _ = served
    parts = urlsplit(server.file_url("/sdcard/DCIM/clip.bin"))
    conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
    conn.request("GET", parts.path + "?" + parts.query)
    resp = conn.getresponse()
    resp.read(10)
    conn.sock.close()  # przerwanie w trakcie
    conn.close()
    for _ in range(100):
        if server.streams and server.streams[-1].closed_flag:
            break
        import time
        time.sleep(0.05)
    assert server.streams[-1].closed_flag
    assert "Traceback" not in capfd.readouterr().err


def test_keep_alive_serves_two_requests(served):
    server, _ = served
    parts = urlsplit(server.file_url("/sdcard/DCIM/clip.bin"))
    conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
    for a, b in ((0, 99), (5000, 5099)):
        conn.request("GET", parts.path + "?" + parts.query, headers={"Range": f"bytes={a}-{b}"})
        assert conn.getresponse().read() == DATA[a:b + 1]
    conn.close()


def test_polish_and_emoji_path_roundtrip(phone, served):
    server, _ = served
    name = "/sdcard/DCIM/Zażółć 😀 gęślą.txt"
    phone.local(name).write_bytes(b"cze\xc5\x9b\xc4\x87")
    r = get(server.file_url(name))
    assert r.status == 200 and r.read() == "cześć".encode()
    assert r.headers["Content-Type"].startswith("text/plain")


def test_pdf_range_headers_are_available_to_the_browser(served, phone):
    server, _ = served
    phone.local("/sdcard/DCIM/document.pdf").write_bytes(b"%PDF-1.7 test")
    response = get(server.file_url("/sdcard/DCIM/document.pdf"), {"Origin": APP, "Range": "bytes=0-3"})
    assert response.status == 206 and response.read() == b"%PDF"
    assert response.headers["Content-Type"] == "application/pdf"
    assert "Accept-Ranges" in response.headers["Access-Control-Expose-Headers"]


def test_read_range_helper(served):
    server, _ = served
    assert server.read_range("/sdcard/DCIM/clip.bin", 70_000, 300) == DATA[70_000:70_300]
    assert server.read_range("/sdcard/DCIM/clip.bin", 0, 10**9) == DATA


# ---- miniatury -------------------------------------------------------------------------------
def jpeg_of(color=(10, 20, 200), size=(400, 300)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def test_listing_size_and_small_jpeg_head_avoid_redundant_adb_calls():
    data = jpeg_of()
    reads = []

    def stream(path, start):
        reads.append((path, start))
        return io.BytesIO(data)

    def no_stat(path):
        raise AssertionError("size already supplied by listing")

    server = MediaServer("adb", "serial", lambda _: False, open_stream=stream, size_of=no_stat)
    server.remember_size("/sdcard/test.jpg", len(data))
    assert server.thumb("/sdcard/test.jpg", 128) is not None
    assert reads == [("/sdcard/test.jpg", 0)]
    assert server.thumb("/sdcard/test.jpg", 128) is not None
    assert len(reads) == 1


def test_thumb_from_exif_reads_only_head():
    data = oppo_style_jpeg()
    assert next(start for m, start, _ in _segments(data) if m == 0xC0) > EXIF_HEAD  # SOF daleko za głową
    read: list[int] = []

    def read_head(n: int) -> bytes:
        read.append(n)
        return data[:n]

    def read_all() -> bytes:
        raise AssertionError("pełny plik nie powinien być czytany")

    result = thumbnail(read_head, read_all, 256, "IMG_0001.JPG")
    assert result is not None
    assert sum(read) <= 131072 and max(read) <= EXIF_HEAD
    img = Image.open(io.BytesIO(result[0]))
    assert max(img.size) <= 256 and img.size == (160, 120)
    assert result[1].startswith("#") and len(result[1]) == 7
    r, g, b = (int(result[1][i:i + 2], 16) for i in (1, 3, 5))
    assert g > r and g > b  # zielona miniatura EXIF, nie czerwony cały obraz


def test_thumb_exif_orientation_applied():
    data = oppo_style_jpeg(orientation=6)
    result = thumbnail(lambda n: data[:n], lambda: b"", 256, "a.jpg")
    assert Image.open(io.BytesIO(result[0])).size == (120, 160)  # obrót o 90 stopni


def test_thumb_without_exif_thumbnail_falls_back_to_full_file():
    data = jpeg_of(size=(800, 600))
    result = thumbnail(lambda n: data[:n], lambda: data, 256, "a.jpeg")
    assert result is not None and max(Image.open(io.BytesIO(result[0])).size) == 256


def test_thumb_png_full():
    out = io.BytesIO()
    Image.new("RGBA", (300, 100), (0, 0, 255, 255)).save(out, "PNG")
    result = thumbnail(lambda n: b"", lambda: out.getvalue(), 128, "x.PNG")
    assert result is not None
    assert Image.open(io.BytesIO(result[0])).size == (128, 43)
    assert result[1] == "#0000ff"


def id3(art: bytes, version: int = 3, desc: bytes = b"opis", encoding: int = 0) -> bytes:
    body = bytes([encoding]) + b"image/jpeg\0" + b"\x03" + desc + b"\0" + art
    size = len(body)
    length = (bytes((size >> s) & 0x7F for s in (21, 14, 7, 0)) if version == 4 else size.to_bytes(4, "big"))
    frame = b"APIC" + length + b"\0\0" + body
    total = len(frame)
    return b"ID3" + bytes([version, 0, 0]) + bytes((total >> s) & 0x7F for s in (21, 14, 7, 0)) + frame + b"\xff\xfbaudio"


def flac(art: bytes) -> bytes:
    mime = b"image/jpeg"
    pic = (3).to_bytes(4, "big") + len(mime).to_bytes(4, "big") + mime + (0).to_bytes(4, "big") + bytes(16) \
        + len(art).to_bytes(4, "big") + art
    info = bytes([0]) + (34).to_bytes(3, "big") + bytes(34)
    return b"fLaC" + info + bytes([0x80 | 6]) + len(pic).to_bytes(3, "big") + pic


@pytest.mark.parametrize("version", [3, 4])
def test_thumb_from_mp3_cover(version):
    data = id3(jpeg_of((200, 10, 10)), version=version)
    result = thumbnail(lambda n: data[:n], lambda: b"", 128, "utwor.MP3")
    assert result is not None and result[1].startswith("#c")


def test_thumb_from_mp3_cover_with_utf16_description():
    data = id3(jpeg_of((200, 10, 10)), desc=b"\xff\xfe\xf3\x00\x00", encoding=1)  # helper dokłada drugie 00 końca
    assert thumbnail(lambda n: data[:n], lambda: b"", 128, "a.mp3") is not None


def test_thumb_from_flac_cover():
    data = flac(jpeg_of((200, 10, 10)))
    assert thumbnail(lambda n: data[:n], lambda: b"", 128, "utwor.flac") is not None


def test_audio_without_cover_or_with_cut_tag_has_no_thumb():
    assert thumbnail(lambda n: b"\xff\xfbaudio", lambda: b"", 128, "a.mp3") is None
    cut = id3(jpeg_of())[:30]
    assert thumbnail(lambda n: cut, lambda: b"", 128, "a.mp3") is None
    assert thumbnail(lambda n: b"fLaC\x80", lambda: b"", 128, "a.flac") is None


def test_thumb_video_and_unknown_are_none():
    assert thumbnail(lambda n: b"", lambda: b"x", 128, "v.mp4") is None
    assert thumbnail(lambda n: b"", lambda: b"x", 128, "notes.txt") is None
    assert thumbnail(lambda n: b"", lambda: b"not a jpeg", 128, "broken.jpg") is None


def test_thumb_has_color_header(phone, served):
    server, _ = served
    phone.local("/sdcard/DCIM/b.jpg").write_bytes(jpeg_of((250, 10, 10)))
    r = get(server.thumb_url("/sdcard/DCIM/b.jpg", 64), {"Origin": APP})
    assert r.status == 200 and r.headers["Content-Type"] == "image/jpeg"
    color = r.headers["X-Color"]
    assert len(color) == 7 and int(color[1:3], 16) > 200
    assert r.headers["Access-Control-Allow-Origin"] == APP
    assert max(Image.open(io.BytesIO(r.read())).size) == 64
    opened = len(server.opened)
    get(server.thumb_url("/sdcard/DCIM/b.jpg", 64)).read()
    assert len(server.opened) == opened  # druga miniatura z cache


def test_thumb_video_404(phone, served):
    server, _ = served
    phone.local("/sdcard/DCIM/v.mp4").write_bytes(b"\x00" * 100)
    assert get(server.thumb_url("/sdcard/DCIM/v.mp4")).status == 404


def test_thumb_cache_lru_evicts_by_size():
    cache = ThumbCache(limit=10)
    cache.put("a", (b"1234", "#000000"))
    cache.put("b", (b"1234", "#000000"))
    cache.get("a")
    cache.put("c", (b"1234", "#000000"))
    assert cache.get("b") is None and cache.get("a") is not None and cache.get("c") is not None


# ---- strumień przez serwer adb ---------------------------------------------------------------
class FakeAdbServer:
    """Serwer adb na gnieździe: `host:transport:<serial>`, potem `exec:<polecenie>` i dane."""

    def __init__(self, data: bytes = b"", refuse: bool = False) -> None:
        self.data = data
        self.refuse = refuse
        self.requests: list[str] = []
        self.closed = threading.Event()
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def request(self, conn) -> str:
        size = int(conn.recv(4), 16)
        text = conn.recv(size).decode()
        self.requests.append(text)
        return text

    def serve(self) -> None:
        conn, _ = self.sock.accept()
        with conn:
            self.request(conn)
            if self.refuse:
                conn.sendall(b"FAIL0009no device")
                return
            conn.sendall(b"OKAY")
            self.request(conn)
            conn.sendall(b"OKAY")
            try:
                conn.sendall(self.data)
            except OSError:
                pass
        self.closed.set()


def test_socket_stream_reads_through_the_adb_server():
    server = FakeAdbServer(b"zawartosc")
    stream = socket_stream(server.port, "SER1", "dd if=/sdcard/a bs=65536 skip=0 status=none")
    out = bytearray()
    while chunk := stream.read(4):
        out += chunk
    stream.close()
    assert bytes(out) == b"zawartosc"
    assert server.requests == ["host:transport:SER1", "exec:dd if=/sdcard/a bs=65536 skip=0 status=none"]


def test_socket_stream_refused_raises_so_the_process_fallback_can_run():
    server = FakeAdbServer(refuse=True)
    with pytest.raises(OSError):
        socket_stream(server.port, "SER1", "dd")


def test_closing_a_socket_stream_early_starts_no_process(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("zamknięcie nie może uruchamiać procesu"))
    server = FakeAdbServer(b"x" * 1000)
    stream = socket_stream(server.port, "SER1", "dd")
    assert stream.read(10)
    stream.close()
    assert server.closed.wait(2)
