"""Lokalny serwer HTTP do testów klienta (spec backendu §5.2): odpowiedź ustawiana per test."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Stub:
    status: int = 200
    body: bytes = b'{"ok": true}'
    content_type: str = "application/json"
    delay: float = 0.0  # opóźnienie przed wysłaniem treści (nagłówki idą od razu)
    truncate_body: bool = False  # jeśli True, wysłanie mniej bajtów niż Content-Length mówi
    redirects: dict[str, str] = field(default_factory=dict)  # ścieżka → Location (302)
    routes: dict[str, tuple[int, bytes]] = field(default_factory=dict)  # ścieżka → (status, treść)
    requests: list[tuple[str, str, dict[str, str], bytes]] = field(default_factory=list)
    url: str = ""


def serve(stub: Stub):
    """Uruchamia serwer w wątku; zwraca funkcję zatrzymującą. Ustawia stub.url."""

    class Handler(BaseHTTPRequestHandler):
        def _reply(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(length) if length else b""
            stub.requests.append((self.command, self.path, dict(self.headers), data))
            if self.path in stub.redirects:
                self.send_response(302)
                self.send_header("Location", stub.redirects[self.path])
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status, body = stub.routes.get(self.path, (stub.status, stub.body))
            self.send_response(status)
            self.send_header("Content-Type", stub.content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.flush()
            time.sleep(stub.delay)
            try:
                if stub.truncate_body:  # wysłanie tylko połowy bajtów, potem zamknięcie
                    self.wfile.write(body[:len(body) // 2])
                else:
                    self.wfile.write(body)
            except OSError:  # klient mógł już zamknąć gniazdo po timeoucie — bez śladu w stderr
                pass

        do_GET = do_POST = _reply

        def log_message(self, *args) -> None:  # cisza w wyjściu pytest
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    stub.url = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def stop() -> None:
        server.shutdown()
        server.server_close()

    return stop


def serve_garbage() -> tuple[str, Callable[[], None]]:
    """Uruchamia surowy serwer wysyłający śmieci zamiast HTTP; zwraca (url, stop_fn)."""

    def handler():
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("127.0.0.1", 0))
        server_socket.listen(1)
        port = server_socket.getsockname()[1]

        def accept_connections():
            while True:
                try:
                    client, _ = server_socket.accept()
                    client.sendall(b"garbage\r\n\r\n")  # nie-HTTP odpowiedź
                    client.close()
                except OSError:
                    break

        thread = threading.Thread(target=accept_connections, daemon=True)
        thread.start()
        return server_socket, port

    server_socket, port = handler()
    url = f"http://127.0.0.1:{port}"

    def stop() -> None:
        server_socket.close()

    return url, stop
