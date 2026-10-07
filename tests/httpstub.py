"""Lokalny serwer HTTP do testów klienta (spec backendu §5.2): odpowiedź ustawiana per test."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Stub:
    status: int = 200
    body: bytes = b'{"ok": true}'
    content_type: str = "application/json"
    delay: float = 0.0  # opóźnienie przed wysłaniem treści (nagłówki idą od razu)
    requests: list[tuple[str, str, dict[str, str], bytes]] = field(default_factory=list)
    url: str = ""


def serve(stub: Stub):
    """Uruchamia serwer w wątku; zwraca funkcję zatrzymującą. Ustawia stub.url."""

    class Handler(BaseHTTPRequestHandler):
        def _reply(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(length) if length else b""
            stub.requests.append((self.command, self.path, dict(self.headers), data))
            self.send_response(stub.status)
            self.send_header("Content-Type", stub.content_type)
            self.send_header("Content-Length", str(len(stub.body)))
            self.end_headers()
            self.wfile.flush()
            time.sleep(stub.delay)
            self.wfile.write(stub.body)

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
