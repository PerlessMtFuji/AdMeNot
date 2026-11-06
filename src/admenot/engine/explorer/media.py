"""Lokalny serwer mediów eksploratora: strumieniuje pliki z telefonu (Range), miniatury i metadane.

Nasłuch tylko na 127.0.0.1, adres z losowym tokenem; pliki czytamy `dd` przez `adb exec-out` od bloku
zawierającego żądany bajt i zabijamy proces po wysłaniu `length` bajtów (okno WebView przerywa połączenia
przy każdym przewinięciu filmu)."""

from __future__ import annotations

import logging
import mimetypes
import re
import secrets
import subprocess
import sys
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePosixPath
from typing import Literal, Protocol
from urllib.parse import parse_qs, quote, urlsplit

from admenot.engine.adb.transport import AdbError, RealAdb
from admenot.engine.explorer.guard import (
    STREAM_BLOCK,
    ExplorerAdb,
    UnsafeCommand,
    safe_read_path,
    stream_args,
)
from admenot.engine.explorer.thumbs import FULL_IMAGE_LIMIT, ThumbCache, thumbnail
from admenot.engine.transfer.guard import STAT_TAIL, q
from admenot.engine.transfer.puller import _CREATE_NO_WINDOW, _kill_tree

__all__ = ["MediaServer", "Stream"]

_LOG = logging.getLogger(__name__)
_CHUNK = 65536
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")
_DEFAULT_THUMB = 256
_MAX_THUMB = 1024
_NO: Literal["unsatisfiable"] = "unsatisfiable"
_QUIET = (ConnectionError, TimeoutError)  # przerwane połączenia (przewijanie filmu) nie są błędem


class Stream(Protocol):
    def read(self, n: int, /) -> bytes: ...
    def close(self) -> None: ...


class _ProcStream:
    """Standardowe wyjście `adb exec-out dd …`; `close()` zabija proces razem z potomkami."""

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        self.proc = proc
        assert proc.stdout is not None
        self._out = proc.stdout

    def read(self, n: int, /) -> bytes:
        return self._out.read1(n)  # type: ignore[attr-defined]

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                _kill_tree(self.proc)
        finally:
            self._out.close()


def _adb_stream(adb_path: str, serial: str) -> Callable[[str, int], Stream]:
    def open_stream(path: str, start: int) -> Stream:
        flags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.Popen([adb_path, "-s", serial, *stream_args(path, start)], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=flags)
        return _ProcStream(proc)
    return open_stream


def _adb_size(adb_path: str, serial: str) -> Callable[[str], int]:
    adb = ExplorerAdb(RealAdb(serial=serial, adb_path=adb_path))

    def size_of(path: str) -> int:
        return stat_size(adb, path)
    return size_of


def stat_size(adb: ExplorerAdb, path: str) -> int:
    """Rozmiar zwykłego pliku (`stat`); FileNotFoundError dla brakującego pliku i folderu."""
    out = adb.shell("stat -c '%f|%s|%Y|%n' " + q(safe_read_path(path)) + STAT_TAIL)
    for line in out.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4 and parts[0].isalnum() and parts[1].isdigit():
            try:
                if int(parts[0], 16) & 0o170000 == 0o040000:
                    break
            except ValueError:
                break
            return int(parts[1])
    raise FileNotFoundError(path)


def parse_range(header: str | None, size: int) -> tuple[int, int] | Literal["unsatisfiable"] | None:
    """(start, end włącznie) dla jednego zakresu; None = brak/niezrozumiały nagłówek (serwujemy całość)."""
    if not header:
        return None
    m = _RANGE.fullmatch(header.strip())
    if m is None:
        return None
    first, last = m.groups()
    if not first and not last:
        return None
    if not first:  # sufiks: ostatnie n bajtów
        n = int(last)
        return _NO if n == 0 or size == 0 else (max(0, size - n), size - 1)
    start = int(first)
    end = min(int(last), size - 1) if last else size - 1
    if start >= size or end < start:
        return _NO
    return start, end


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def handle_error(self, request, client_address) -> None:
        _LOG.debug("media server request failed", exc_info=True)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _Server
    owner: MediaServer

    def log_message(self, format: str, *args: object) -> None:
        pass

    # ---- wejścia -------------------------------------------------------------------------
    def do_OPTIONS(self) -> None:
        self._guarded(self._options)

    def do_HEAD(self) -> None:
        self._guarded(lambda: self._route(head=True))

    def do_GET(self) -> None:
        self._guarded(lambda: self._route(head=False))

    def _guarded(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except _QUIET:
            self.close_connection = True
        except OSError:
            self.close_connection = True
            _LOG.debug("media server I/O error", exc_info=True)

    # ---- pomocnicze ----------------------------------------------------------------------
    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin and self.owner.allow_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Expose-Headers", "X-Color, Content-Range, Accept-Ranges")
            self.send_header("Vary", "Origin")

    def _reply(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None, head: bool = False) -> None:
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body and not head:
            self.wfile.write(body)

    def _parse(self) -> tuple[str, dict[str, list[str]]] | None:
        parts = urlsplit(self.path)
        segs = parts.path.strip("/").split("/")
        if len(segs) != 2 or not secrets.compare_digest(segs[0].encode(), self.owner.token.encode()):
            return None
        return segs[1], parse_qs(parts.query)

    def _options(self) -> None:
        if self._parse() is None:
            self._reply(404)
            return
        self._reply(204, headers={"Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                                  "Access-Control-Allow-Headers": "Range", "Access-Control-Max-Age": "600"})

    def _route(self, head: bool) -> None:
        parsed = self._parse()
        if parsed is None:
            self._reply(404, head=head)
            return
        endpoint, query = parsed
        path = (query.get("p") or [""])[0]
        try:
            safe_read_path(path)
        except UnsafeCommand:
            self._reply(400, head=head)
            return
        if endpoint == "file":
            self._file(path, head)
        elif endpoint == "thumb":
            self._thumb(path, query, head)
        else:
            self._reply(404, head=head)

    def _file(self, path: str, head: bool) -> None:
        try:
            size = self.owner.size_of(path)
        except (FileNotFoundError, AdbError, UnsafeCommand):
            self._reply(404, head=head)
            return
        rng = parse_range(self.headers.get("Range"), size)
        headers = {"Content-Type": mimetypes.guess_type(PurePosixPath(path).name)[0] or "application/octet-stream",
                   "Accept-Ranges": "bytes", "Cache-Control": "no-store"}
        if isinstance(rng, str):
            self._reply(416, headers={"Content-Range": f"bytes */{size}"}, head=head)
            return
        if rng is None:
            status, start, length = 200, 0, size
        else:
            start, end = rng
            status, length = 206, end - start + 1
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        try:
            stream = None if head or length == 0 else self.owner.open_stream(path, start)
        except (OSError, UnsafeCommand, AdbError):
            self._reply(502, head=head)
            return
        try:
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self._cors()
            self.send_header("Content-Length", str(length))
            self.end_headers()
            if stream is not None:
                self._pump(stream, start % STREAM_BLOCK, length)
        finally:
            if stream is not None:
                stream.close()

    def _pump(self, stream: Stream, skip: int, length: int) -> None:
        while skip > 0:
            chunk = stream.read(min(_CHUNK, skip))
            if not chunk:
                self.close_connection = True
                return
            skip -= len(chunk)
        remaining = length
        while remaining > 0:
            chunk = stream.read(min(_CHUNK, remaining))
            if not chunk:
                self.close_connection = True  # telefon skończył wcześniej: nie da się dopełnić Content-Length
                return
            self.wfile.write(chunk)
            remaining -= len(chunk)

    def _thumb(self, path: str, query: dict[str, list[str]], head: bool) -> None:
        try:
            size = max(16, min(int((query.get("s") or [_DEFAULT_THUMB])[0]), _MAX_THUMB))
        except ValueError:
            size = _DEFAULT_THUMB
        result = self.owner.thumb(path, size)
        if result is None:
            self._reply(404, head=head)
            return
        data, color = result
        self._reply(200, data, {"Content-Type": "image/jpeg", "X-Color": color, "Cache-Control": "no-store"}, head)


class MediaServer:
    """`start()` -> `http://127.0.0.1:<port>/<token>`; `file_url` / `thumb_url` budują adresy punktów końcowych."""

    def __init__(self, adb_path: str, serial: str, allow_origin: Callable[[str], bool], *,
                 open_stream: Callable[[str, int], Stream] | None = None,
                 size_of: Callable[[str], int] | None = None,
                 cache: ThumbCache | None = None) -> None:
        self.allow_origin = allow_origin
        self.open_stream = open_stream or _adb_stream(adb_path, serial)
        self._size_of = size_of or _adb_size(adb_path, serial)
        self._sizes: dict[str, int] = {}
        self._sizes_lock = threading.Lock()
        self.cache = cache or ThumbCache()
        self.token = secrets.token_urlsafe(16)
        self._httpd: _Server | None = None
        self._base = ""

    # ---- cykl życia ----------------------------------------------------------------------
    def start(self) -> str:
        if self._httpd is None:
            handler = type("Handler", (_Handler,), {"owner": self})
            self._httpd = _Server(("127.0.0.1", 0), handler)
            threading.Thread(target=self._httpd.serve_forever, name="explorer-media", daemon=True).start()
            self._base = f"http://127.0.0.1:{self._httpd.server_address[1]}/{self.token}"
        return self._base

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()

    def file_url(self, path: str) -> str:
        return f"{self._base}/file?p={quote(path, safe='')}"

    def thumb_url(self, path: str, size: int = _DEFAULT_THUMB) -> str:
        return f"{self._base}/thumb?p={quote(path, safe='')}&s={size}"

    # ---- odczyt --------------------------------------------------------------------------
    def size_of(self, path: str) -> int:
        with self._sizes_lock:
            size = self._sizes.get(path)
        if size is None:
            size = self._size_of(path)
            with self._sizes_lock:
                self._sizes[path] = size
        return size

    def forget_sizes(self, folder: str) -> None:
        """Zapomina rozmiary plików bezpośrednio w `folder` (przy każdym jego listowaniu — plik mógł się
        zmienić, np. nadpisany przez klienta na telefonie)."""
        prefix = folder.rstrip("/") + "/"
        with self._sizes_lock:
            for path in [p for p in self._sizes if p.startswith(prefix) and "/" not in p[len(prefix):]]:
                del self._sizes[path]

    def remember_size(self, path: str, size: int) -> None:
        """Listowanie już odczytało stat; miniatura nie musi pytać telefonu drugi raz."""
        with self._sizes_lock:
            self._sizes[path] = size

    def read_range(self, path: str, start: int, length: int) -> bytes:
        """`length` bajtów pliku od `start` tą samą drogą co serwer (np. podgląd tekstu)."""
        stream = self.open_stream(path, start)
        try:
            skip, out = start % STREAM_BLOCK, bytearray()
            while skip > 0:
                chunk = stream.read(min(_CHUNK, skip))
                if not chunk:
                    return b""
                skip -= len(chunk)
            while len(out) < length:
                chunk = stream.read(min(_CHUNK, length - len(out)))
                if not chunk:
                    break
                out += chunk
            return bytes(out)
        finally:
            stream.close()

    def thumb(self, path: str, size: int) -> tuple[bytes, str] | None:
        try:
            file_size = self.size_of(path)
        except (FileNotFoundError, AdbError, UnsafeCommand):
            return None
        key = (path, size, file_size)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        head = b""

        def read_head(n: int) -> bytes:
            nonlocal head
            head = self.read_range(path, 0, min(n, file_size))
            return head

        def read_all() -> bytes:
            if file_size > FULL_IMAGE_LIMIT:
                return b""
            return head if len(head) == file_size else self.read_range(path, 0, file_size)

        result = thumbnail(read_head, read_all, size,
                           PurePosixPath(path).name)
        if result is not None:
            self.cache.put(key, result)
        return result
