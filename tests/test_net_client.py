import json
import socket

import pytest
from httpstub import Stub, serve, serve_garbage

from admenot import __version__
from admenot.net import client
from admenot.net.client import BackendError


@pytest.fixture
def stub(monkeypatch):
    s = Stub()
    stop = serve(s)
    monkeypatch.setenv(client.ENV_URL, s.url)
    yield s
    stop()


def test_get_json_returns_object(stub):
    stub.body = b'{"ok": true, "db": true}'
    assert client.get_json("/api/v1/health") == {"ok": True, "db": True}
    method, path, _, _ = stub.requests[0]
    assert (method, path) == ("GET", "/api/v1/health")


def test_user_agent_is_only_the_version(stub):
    client.get_json("/x")
    headers = stub.requests[0][2]
    assert headers["User-Agent"] == f"AdMeNot/{__version__}"


def test_post_json_sends_json(stub):
    assert client.post_json("/api/v1/echo", {"a": 1}) == {"ok": True}
    method, path, headers, data = stub.requests[0]
    assert (method, path) == ("POST", "/api/v1/echo")
    assert headers["Content-Type"] == "application/json"
    assert json.loads(data) == {"a": 1}


def test_http_error_keeps_status(stub):
    stub.status = 503
    stub.body = b'{"ok": false, "db": false}'
    with pytest.raises(BackendError) as err:
        client.get_json("/api/v1/health")
    assert (err.value.kind, err.value.status, str(err.value)) == ("http", 503, "http 503")


def test_error_with_json_body_is_still_http_error(stub):
    stub.status = 404
    stub.body = b'{"error": "not_found"}'
    with pytest.raises(BackendError) as err:
        client.get_json("/api/v1/nope")
    assert (err.value.kind, err.value.status) == ("http", 404)


def test_html_page_is_invalid(stub):
    stub.body = b"<html><body>Zaloguj si\xc4\x99 do sieci Wi-Fi</body></html>"
    stub.content_type = "text/html; charset=utf-8"
    with pytest.raises(BackendError) as err:
        client.get_json("/api/v1/health")
    assert (err.value.kind, str(err.value)) == ("invalid", "invalid")


def test_json_array_is_invalid(stub):
    stub.body = b"[1, 2]"
    with pytest.raises(BackendError) as err:
        client.get_json("/api/v1/health")
    assert err.value.kind == "invalid"


def test_slow_body_times_out_as_offline(stub, monkeypatch):
    monkeypatch.setattr(client, "TIMEOUT", 0.2)
    stub.delay = 1.0
    with pytest.raises(BackendError) as err:
        client.get_json("/api/v1/health")
    assert (err.value.kind, err.value.status) == ("offline", None)


def test_closed_port_is_offline(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv(client.ENV_URL, f"http://127.0.0.1:{port}")
    monkeypatch.setattr(client, "TIMEOUT", 1.0)
    with pytest.raises(BackendError) as err:
        client.get_json("/api/v1/health")
    assert err.value.kind == "offline"


def test_env_url_trailing_slash(stub, monkeypatch):
    monkeypatch.setenv(client.ENV_URL, stub.url + "/")
    client.get_json("/api/v1/health")
    assert stub.requests[0][1] == "/api/v1/health"


def test_default_base_url(monkeypatch):
    monkeypatch.delenv(client.ENV_URL, raising=False)
    assert client.base_url() == client.BASE_URL
    assert client.BASE_URL == "https://admenot.<subdomena>.workers.dev"


def test_garbage_non_http_reply_is_offline(monkeypatch):
    url, stop = serve_garbage()
    monkeypatch.setenv(client.ENV_URL, url)
    try:
        with pytest.raises(BackendError) as err:
            client.get_json("/api/v1/health")
        assert err.value.kind == "offline"
    finally:
        stop()


def test_truncated_body_is_offline(stub):
    stub.truncate_body = True
    with pytest.raises(BackendError) as err:
        client.get_json("/api/v1/health")
    assert err.value.kind == "offline"


def test_malformed_env_url_no_scheme_is_offline(monkeypatch):
    monkeypatch.setenv(client.ENV_URL, "admenot.invalid")
    with pytest.raises(BackendError) as err:
        client.get_json("/api/v1/health")
    assert err.value.kind == "offline"
