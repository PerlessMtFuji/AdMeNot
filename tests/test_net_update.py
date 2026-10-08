import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from updatehelpers import DROP, public_b64, signed

from admenot.net import client, update, update_key
from admenot.net.update import ManifestError


def test_valid_manifest(signing_key):
    raw = signed(signing_key)
    m = update.verify(raw)
    assert (m.latest, m.min_supported, m.size, m.sha256) == ("9.9.9", "0.9.0", 1234, "a" * 64)
    assert m.published.isoformat() == "2026-10-20"
    assert m.notes_for("pl") == "Poprawki." and m.notes_for("de") == "Fixes."
    assert m.min_reason is None and m.reason_for("pl") is None
    assert m.raw == raw


def test_tampered_payload_is_rejected(signing_key):
    outer = json.loads(signed(signing_key))
    outer["payload"] = outer["payload"].replace('"0.9.0"', '"0.0.1"')
    with pytest.raises(ManifestError, match="podpis"):
        update.verify(json.dumps(outer).encode())


def test_foreign_key_is_rejected(signing_key):
    with pytest.raises(ManifestError, match="podpis"):
        update.verify(signed(Ed25519PrivateKey.generate()))


def test_no_trusted_keys_rejects_everything(signing_key, monkeypatch):
    monkeypatch.setattr(update, "PUBLIC_KEYS", ())
    with pytest.raises(ManifestError):
        update.verify(signed(signing_key))


def test_any_listed_key_is_enough(signing_key, monkeypatch):
    old = Ed25519PrivateKey.generate()
    monkeypatch.setattr(update, "PUBLIC_KEYS", (public_b64(old), public_b64(signing_key)))
    assert update.verify(signed(signing_key)).latest == "9.9.9"


def test_production_keys_are_raw_ed25519_keys():
    for key in update_key.PUBLIC_KEYS:
        assert len(base64.b64decode(key, validate=True)) == 32


@pytest.mark.parametrize("changes", [
    {"format": 2}, {"format": True}, {"format": DROP},
    {"latest": "0.9"}, {"latest": "9.9.9-beta"}, {"latest": 99},
    {"min_supported": "10.0.0"},  # wyżej niż latest
    {"published": "20261020"}, {"published": "2026-13-01"}, {"published": DROP},
    {"url": "https://evil.example/AdMeNot-9.9.9-setup.exe"},
    {"url": update.URL_PREFIX + "v9.9.9/AdMeNot-9.9.9-setup.zip"},
    {"sha256": "A" * 64}, {"sha256": "a" * 63},
    {"size": 0}, {"size": True}, {"size": "1234"},
    {"notes": {"pl": "x"}}, {"notes": {"pl": "x", "en": ""}}, {"notes": "x"},
    {"min_reason": {"pl": "x"}},
], ids=lambda c: ",".join(f"{k}={'DROP' if v is DROP else v!r}" for k, v in c.items()))
def test_invalid_payload_is_rejected(signing_key, changes):
    with pytest.raises(ManifestError):
        update.verify(signed(signing_key, **changes))


@pytest.mark.parametrize("raw", [
    b"<html>Zaloguj do Wi-Fi</html>", b"[]", b'{"payload": "{}"}',
    b'{"payload": 1, "sig": "eA=="}', b'{"payload": "{}", "sig": "***"}',
])
def test_malformed_file_is_rejected(signing_key, raw):
    with pytest.raises(ManifestError):
        update.verify(raw)


def test_versions_compare_as_numbers():
    assert update.parse_version("0.9.10") > update.parse_version("0.9.9")
    with pytest.raises(ManifestError):
        update.parse_version("1.0")


@pytest.mark.parametrize(("version", "available", "retired"), [
    ("9.9.9", False, False), ("9.0.0", True, False), ("0.8.0", True, True), ("10.0.0", False, False),
])
def test_state(signing_key, version, available, retired):
    st = update.state(update.verify(signed(signing_key)), version)
    assert (st.available, st.retired) == (available, retired)


def test_no_manifest_means_nothing():
    assert update.state(None, "0.9.2") == update.UpdateState(None, False, False)


def test_reason_for_language(signing_key):
    m = update.verify(signed(signing_key, min_reason={"pl": "Błąd cofania", "en": "Undo bug"}))
    assert m.reason_for("pl") == "Błąd cofania" and m.reason_for("xx") == "Undo bug"


def test_dev_server_url_only_with_the_env_override(signing_key, monkeypatch):
    url = "http://127.0.0.1:8787/AdMeNot-9.9.9-setup.exe"
    monkeypatch.delenv(client.ENV_URL, raising=False)
    with pytest.raises(ManifestError):
        update.verify(signed(signing_key, url=url))
    monkeypatch.setenv(client.ENV_URL, "http://127.0.0.1:8787/")
    assert update.verify(signed(signing_key, url=url)).url == url


def test_download_page_follows_the_language(monkeypatch):
    monkeypatch.delenv(client.ENV_URL, raising=False)
    assert update.download_page("pl") == client.BASE_URL + "/pl/"
    assert update.download_page("en") == client.BASE_URL + "/"
