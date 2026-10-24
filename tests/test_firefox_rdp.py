"""Transport Firefox RDP (zgody na powiadomienia witryn) na FakePhone + FakeRdp."""

import json

import pytest
from fakephone import FIREFOX_SOCKET, FakePhone, FakeRdp

from admenot.engine.adb.transport import AdbError
from admenot.engine.browsers import firefox_rdp as R

FORWARD = f"forward tcp:0 localabstract:{FIREFOX_SOCKET}"


def phone(port: str = "40123\n", **kwargs) -> FakePhone:
    return FakePhone([], host={FORWARD: port}, **kwargs)


def test_reads_permissions_and_removes_forward():
    adb = phone()
    rdp = FakeRdp(results=['[["https://a.pl",1],["https://b.pl",2]]'])
    assert R.notification_permissions(adb, connect=rdp.connect) == {"https://a.pl": 1, "https://b.pl": 2}
    assert rdp.port == 40123
    assert f"host:{FORWARD}" in adb.calls
    assert "host:forward --remove tcp:40123" in adb.calls
    assert rdp.closed


def test_sends_the_documented_packet_sequence():
    rdp = FakeRdp(results=["[]"])
    R.notification_permissions(phone(), connect=rdp.connect)
    assert [(p["to"], p["type"]) for p in rdp.sent] == [
        ("root", "getProcess"), ("proc1", "getTarget"), ("console1", "evaluateJSAsync")]
    assert rdp.sent[0]["id"] == 0
    assert rdp.scripts == [R.READ_JS]


def test_frames_split_across_reads():
    rdp = FakeRdp(results=['[["https://a.pl",1],["https://b.pl",2]]'], chunk=7)
    assert R.notification_permissions(phone(), connect=rdp.connect) == {"https://a.pl": 1, "https://b.pl": 2}


def test_long_string_result_is_fetched_whole():
    perms = {f"https://site{i}.example.com": 1 for i in range(600)}
    rdp = FakeRdp(perms=perms, long_string=True)
    assert R.notification_permissions(phone(), connect=rdp.connect) == perms
    assert rdp.sent[-1]["type"] == "substring"


def test_origin_is_json_literal_in_script():
    origin = 'https://a.pl"); evil(); ("'
    rdp = FakeRdp()
    R.set_notification_permission(phone(), origin, 2, connect=rdp.connect)
    assert rdp.scripts == [R.ADD_JS.format(origin=json.dumps(origin), capability=2)]
    assert json.dumps(origin) in rdp.scripts[0]
    assert rdp.perms == {origin: 2}  # FakeRdp przeczytało origin z literału JSON, nie z kodu


def test_capability_zero_removes_and_state_roundtrips():
    adb = phone()
    rdp = FakeRdp(perms={"https://a.pl": 1, "https://b.pl": 2})
    R.set_notification_permission(adb, "https://a.pl", 0, connect=rdp.connect)
    assert R.notification_permissions(adb, connect=rdp.connect) == {"https://b.pl": 2}
    R.set_notification_permission(adb, "https://c.pl", 1, connect=rdp.connect)
    assert rdp.perms == {"https://b.pl": 2, "https://c.pl": 1}


def test_bad_capability_is_rejected_before_touching_the_phone():
    adb = phone()
    with pytest.raises(ValueError):
        R.set_notification_permission(adb, "https://a.pl", 3, connect=FakeRdp().connect)
    assert adb.calls == []


@pytest.mark.parametrize("closes_at", ["connect", "eval"])
def test_connection_closed_raises_rdp_unavailable_and_still_removes_forward(closes_at):
    adb = phone()
    rdp = FakeRdp(closes_at=closes_at)
    with pytest.raises(R.RdpError) as err:
        R.notification_permissions(adb, connect=rdp.connect)
    assert err.value.key == "rdp_unavailable"
    assert "host:forward --remove tcp:40123" in adb.calls


def test_refused_connection_raises_rdp_unavailable_and_removes_forward():
    adb = phone()

    def refuse(port):
        raise ConnectionRefusedError("refused")

    with pytest.raises(R.RdpError) as err:
        R.notification_permissions(adb, connect=refuse)
    assert err.value.key == "rdp_unavailable"
    assert "host:forward --remove tcp:40123" in adb.calls


def test_eval_exception_raises_rdp_failed():
    adb = phone()
    with pytest.raises(R.RdpError) as err:
        R.notification_permissions(adb, connect=FakeRdp(exception="TypeError: x").connect)
    assert err.value.key == "rdp_failed"
    assert "host:forward --remove tcp:40123" in adb.calls


def test_result_of_unexpected_shape_raises_rdp_failed():
    for result in ('{"a": 1}', "not json", '[["https://a.pl"]]'):
        with pytest.raises(R.RdpError) as err:
            R.notification_permissions(phone(), connect=FakeRdp(results=[result]).connect)
        assert err.value.key == "rdp_failed"


def test_oversize_frame_raises_rdp_failed():
    class Huge:
        def sendall(self, data):
            pass

        def recv(self, size):
            return f"{R.MAX_FRAME + 1}:".encode()

        def close(self):
            pass

    with pytest.raises(R.RdpError) as err:
        R.notification_permissions(phone(), connect=lambda port: Huge())
    assert err.value.key == "rdp_failed"


def test_garbage_header_raises_rdp_failed():
    class Garbage:
        def sendall(self, data):
            pass

        def recv(self, size):
            return b"HTTP/1.1 400 Bad Request\r\n"

        def close(self):
            pass

    with pytest.raises(R.RdpError) as err:
        R.notification_permissions(phone(), connect=lambda port: Garbage())
    assert err.value.key == "rdp_failed"


def test_forward_failure_propagates_adb_error():
    adb = FakePhone([], host={FORWARD: AdbError("no_device", "gone")})
    with pytest.raises(AdbError):
        R.notification_permissions(adb, connect=FakeRdp().connect)


def test_forward_is_allocated_and_released_by_the_fake_phone():
    adb = FakePhone([])  # bez wpisu w host: FakePhone sam przydziela port
    rdp = FakeRdp(results=["[]"])
    R.notification_permissions(adb, connect=rdp.connect)
    assert rdp.port is not None and adb.forwards == {}


def test_socket_present_reads_proc_net_unix():
    socket_name = known_socket()
    assert R.socket_present(phone(firefox_debugging=True), socket_name)
    assert not R.socket_present(phone(), socket_name)
    assert not R.socket_present(phone(firefox_debugging=True), "org.mozilla.fenix/firefox-debugger-socket")


def known_socket() -> str:
    from admenot.engine.browsers.known import known_browsers

    socket_name = known_browsers()[R.FIREFOX].rdp_socket
    assert socket_name == FIREFOX_SOCKET
    return socket_name
