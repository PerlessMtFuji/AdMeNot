"""Firefox na Androidzie przez Remote Debugging Protocol: zgody na powiadomienia witryn.

Firefox nie ma polecenia powłoki do tych zgód, ale jego gniazdo debugowania (włączane przez
użytkownika w ustawieniach) wystawia konsolę procesu rodzica, w której `Services.perms` czyta
i zmienia magazyn uprawnień. Ramki RDP: `<długość>:<json>`. Do JS trafia wyłącznie origin
wstawiony jako literał JSON (`json.dumps`) i liczba 0/1/2 — nic poza szablonem.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Callable
from typing import Any, Literal, Protocol

from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.browsers.known import known_browsers

FIREFOX = "org.mozilla.firefox"
MAX_FRAME = 4 * 1024 * 1024  # jedna ramka RDP; większa to błąd protokołu, nie dane
_MAX_HEAD = 12  # tyle znaków przed ':' ma sens dla długości ramki

READ_JS = ("JSON.stringify(Services.perms.all.filter(p=>p.type=='desktop-notification')"
           ".map(p=>[p.principal.origin,p.capability]))")
_PRINCIPAL = "Services.scriptSecurityManager.createContentPrincipalFromOrigin({origin})"
ADD_JS = ("Services.perms.addFromPrincipal(" + _PRINCIPAL + ",'desktop-notification',{capability});"
          "JSON.stringify(true)")
REMOVE_JS = ("Services.perms.removeFromPrincipal(" + _PRINCIPAL + ",'desktop-notification');"
             "JSON.stringify(true)")

RdpKey = Literal["rdp_unavailable", "rdp_failed"]


class RdpError(Exception):
    """`rdp_unavailable`: brak połączenia/gniazda; `rdp_failed`: błąd protokołu albo wyjątek JS."""

    def __init__(self, key: RdpKey, message: str) -> None:
        super().__init__(f"{key}: {message}")
        self.key = key
        self.message = message


class RdpStream(Protocol):
    def sendall(self, data: bytes, /) -> None: ...

    def recv(self, size: int, /) -> bytes: ...

    def close(self) -> None: ...


Connect = Callable[[int], RdpStream]


def tcp_connect(port: int) -> RdpStream:
    return socket.create_connection(("127.0.0.1", port), timeout=10.0)


def socket_present(adb: AdbTransport, socket_name: str) -> bool:
    """Czy gniazdo abstrakcyjne istnieje, czyli Firefox ma włączone zdalne debugowanie."""
    wanted = "@" + socket_name
    return any(line.split()[-1:] == [wanted] for line in adb.shell("cat /proc/net/unix").splitlines())


class _Session:
    def __init__(self, stream: RdpStream) -> None:
        self.stream = stream
        self.buf = b""

    def _fill(self) -> None:
        try:
            chunk = self.stream.recv(65536)
        except OSError as exc:  # także TimeoutError
            raise RdpError("rdp_unavailable", f"{type(exc).__name__}: {exc}") from exc
        if not chunk:
            raise RdpError("rdp_unavailable", "connection closed")
        self.buf += chunk

    def recv(self) -> dict[str, Any]:
        while b":" not in self.buf:
            if len(self.buf) > _MAX_HEAD:
                raise RdpError("rdp_failed", "bad frame header")
            self._fill()
        head, rest = self.buf.split(b":", 1)
        try:
            size = int(head)
        except ValueError as exc:
            raise RdpError("rdp_failed", "bad frame header") from exc
        if not 0 <= size <= MAX_FRAME:
            raise RdpError("rdp_failed", f"frame of {size} bytes")
        self.buf = rest
        while len(self.buf) < size:
            self._fill()
        raw, self.buf = self.buf[:size], self.buf[size:]
        try:
            packet = json.loads(raw)
        except ValueError as exc:
            raise RdpError("rdp_failed", "frame is not JSON") from exc
        if not isinstance(packet, dict):
            raise RdpError("rdp_failed", "frame is not an object")
        return packet

    def send(self, packet: dict[str, Any]) -> None:
        data = json.dumps(packet).encode()
        try:
            self.stream.sendall(str(len(data)).encode() + b":" + data)
        except OSError as exc:
            raise RdpError("rdp_unavailable", f"{type(exc).__name__}: {exc}") from exc

    def request(self, packet: dict[str, Any]) -> dict[str, Any]:
        """Odpowiedź aktora, do którego wysłano pakiet; zdarzenia innych aktorów są pomijane."""
        self.send(packet)
        while True:
            reply = self.recv()
            if reply.get("from") != packet["to"]:
                continue
            if "error" in reply:
                raise RdpError("rdp_failed", f"{reply['error']}: {str(reply.get('message', ''))[:200]}")
            return reply

    def evaluate(self, console: str, text: str) -> str:
        reply = self.request({"to": console, "type": "evaluateJSAsync", "text": text})
        result_id = reply.get("resultID")
        if result_id is None:
            raise RdpError("rdp_failed", "evaluateJSAsync without resultID")
        while True:
            msg = self.recv()
            if msg.get("from") == console and msg.get("type") == "evaluationResult" \
                    and msg.get("resultID") == result_id:
                break
        if msg.get("hasException"):
            raise RdpError("rdp_failed", f"JS exception: {str(msg.get('exceptionMessage'))[:200]}")
        result = msg.get("result")
        if isinstance(result, dict) and result.get("type") == "longString":  # ponad 10 000 znaków
            part = self.request({"to": result["actor"], "type": "substring",
                                 "start": 0, "end": result["length"]})
            result = part.get("substring")
        if not isinstance(result, str):
            raise RdpError("rdp_failed", "JS result is not a string")
        return result


def _forward(adb: AdbTransport, socket_name: str) -> int:
    out = adb.run(["forward", "tcp:0", f"localabstract:{socket_name}"]).strip()
    try:
        return int(out)
    except ValueError as exc:
        raise RdpError("rdp_failed", f"adb forward printed {out[:60]!r}") from exc


def _evaluate(adb: AdbTransport, text: str, connect: Connect, timeout: float) -> Any:
    """Jedno wyrażenie w konsoli procesu Firefoxa; wynik (JSON.stringify) zdekodowany z JSON."""
    socket_name = known_browsers()[FIREFOX].rdp_socket
    assert socket_name is not None
    port = _forward(adb, socket_name)
    stream: RdpStream | None = None
    try:
        try:
            stream = connect(port)
        except OSError as exc:
            raise RdpError("rdp_unavailable", f"{type(exc).__name__}: {exc}") from exc
        if hasattr(stream, "settimeout"):
            stream.settimeout(timeout)
        session = _Session(stream)
        session.recv()  # powitanie: {"from":"root","applicationType":...}
        descriptor = session.request({"to": "root", "type": "getProcess", "id": 0})
        process = session.request({"to": descriptor["processDescriptor"]["actor"], "type": "getTarget"})
        console = process["process"]["consoleActor"]
        raw = session.evaluate(console, text)
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise RdpError("rdp_failed", f"result is not JSON: {raw[:60]!r}") from exc
    except (KeyError, TypeError) as exc:  # odpowiedź bez oczekiwanych pól
        raise RdpError("rdp_failed", f"unexpected reply ({type(exc).__name__}: {exc})") from exc
    finally:
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
        try:
            adb.run(["forward", "--remove", f"tcp:{port}"])
        except AdbError:
            pass  # przekierowanie samo zniknie z restartem adb; nie zasłaniamy pierwotnego błędu


def notification_permissions(adb: AdbTransport, *, connect: Connect = tcp_connect,
                             timeout: float = 10.0) -> dict[str, int]:
    """origin → capability (1 = zezwól, 2 = zablokuj) zgód 'desktop-notification'."""
    data = _evaluate(adb, READ_JS, connect, timeout)
    try:
        return {str(origin): int(capability) for origin, capability in data}
    except (TypeError, ValueError) as exc:
        raise RdpError("rdp_failed", "permission list has an unexpected shape") from exc


def set_notification_permission(adb: AdbTransport, origin: str, capability: int, *,
                                connect: Connect = tcp_connect, timeout: float = 10.0) -> None:
    """capability 0 = usuń wpis, 1 = zezwól, 2 = zablokuj."""
    if capability not in (0, 1, 2):
        raise ValueError(f"capability {capability!r}")
    literal = json.dumps(origin)
    if capability == 0:
        text = REMOVE_JS.format(origin=literal)
    else:
        text = ADD_JS.format(origin=literal, capability=capability)
    _evaluate(adb, text, connect, timeout)
