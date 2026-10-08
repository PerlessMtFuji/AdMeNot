import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpstub import Stub, serve
from updatehelpers import signed

from admenot.net import client, update


@pytest.fixture(autouse=True)
def data(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path / "AdMeNot" / "update-manifest.json"


def test_store_and_read_back(signing_key, data):
    m = update.verify(signed(signing_key))
    assert update.store(m) is True
    assert data.read_bytes() == m.raw
    assert update.cached() == m


def test_no_file_means_no_manifest():
    assert update.cached() is None and update.retired("0.9.2") is None


@pytest.mark.parametrize("older", [{"published": "2026-10-19"}, {"min_supported": "0.8.0"}])
def test_older_manifest_never_replaces_newer(signing_key, older):
    newer = update.verify(signed(signing_key))
    update.store(newer)
    assert update.store(update.verify(signed(signing_key, **older))) is False
    assert update.cached() == newer


def test_same_age_manifest_replaces(signing_key):
    update.store(update.verify(signed(signing_key)))
    second = update.verify(signed(signing_key, notes={"pl": "Inne.", "en": "Other."}))
    assert update.store(second) is True and update.cached() == second


def test_edited_cache_file_is_ignored(signing_key, data):
    update.store(update.verify(signed(signing_key, min_supported="9.0.0")))
    data.write_bytes(data.read_bytes().replace(b"9.0.0", b"0.0.1"))
    assert update.cached() is None and update.retired("0.9.2") is None


def test_retired_reads_only_the_cache(signing_key, monkeypatch):
    def boom(path):
        raise AssertionError("retired() nie łączy się z siecią")

    monkeypatch.setattr(client, "get_bytes", boom)
    update.store(update.verify(signed(signing_key, min_supported="9.0.0")))
    assert update.retired("0.9.2").min_supported == "9.0.0"
    assert update.retired("9.0.0") is None


def test_fetch_verifies_the_server_file(signing_key, monkeypatch):
    stub = Stub(body=signed(signing_key))
    stop = serve(stub)
    monkeypatch.setenv(client.ENV_URL, stub.url)
    try:
        assert update.fetch().latest == "9.9.9"
        assert stub.requests[0][1] == "/updates/v1/manifest.json"
        stub.status, stub.body = 404, b'{"error": "not_found"}'
        with pytest.raises(client.BackendError) as err:
            update.fetch()
        assert err.value.status == 404
        stub.status, stub.body = 200, signed(Ed25519PrivateKey.generate())
        with pytest.raises(update.ManifestError):
            update.fetch()
    finally:
        stop()
