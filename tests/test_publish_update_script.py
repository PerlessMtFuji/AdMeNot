import hashlib
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest
from httpstub import Stub, serve
from updatehelpers import public_b64

from admenot.net import update

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish_update.py"
SHA = "b" * 64
DAY = date(2026, 10, 20)
NOTES = {"pl": "Poprawki.", "en": "Fixes."}


def _module():
    spec = importlib.util.spec_from_file_location("publish_update", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pub():
    return _module()


@pytest.fixture
def key(pub, tmp_path):
    path = tmp_path / "key.pem"
    pub.keygen(path, b"haslo")
    return pub.load_key(path, b"haslo")


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "AdMeNot-9.9.9-setup.exe.sha256").write_text(f"{SHA} *AdMeNot-9.9.9-setup.exe\n", "utf-8")
    return d


def test_keygen_refuses_to_overwrite(pub, tmp_path):
    path = tmp_path / "key.pem"
    public = pub.keygen(path, b"haslo")
    assert b"ENCRYPTED PRIVATE KEY" in path.read_bytes() and len(public) == 44
    with pytest.raises(pub.PublishError):
        pub.keygen(path, b"inne")
    with pytest.raises(ValueError):
        pub.load_key(path, b"zle-haslo")


def test_release_writes_a_manifest_the_program_accepts(pub, key, dist, tmp_path):
    out = tmp_path / "manifest.json"
    seen = []

    def fetch(url):
        seen.append(url)
        return SHA, 4321

    keys = (public_b64(key),)
    raw = pub.release("9.9.9", NOTES, key=key, today=DAY, fetch=fetch, dist=dist, out=out, keys=keys)
    assert out.read_bytes() == raw
    m = update.verify(raw, keys)
    assert (m.latest, m.min_supported, m.size, m.sha256) == ("9.9.9", "9.9.9", 4321, SHA)
    assert seen == [update.URL_PREFIX + "v9.9.9/AdMeNot-9.9.9-setup.exe"] and m.url == seen[0]


def test_release_refuses_a_different_file_on_github(pub, key, dist, tmp_path):
    out = tmp_path / "manifest.json"
    with pytest.raises(pub.PublishError, match="SHA-256"):
        pub.release("9.9.9", NOTES, key=key, today=DAY, fetch=lambda url: ("c" * 64, 1),
                    dist=dist, out=out, keys=(public_b64(key),))
    assert not out.exists()


def test_release_keeps_the_previous_minimum(pub, key, dist, tmp_path):
    out = tmp_path / "manifest.json"
    keys = (public_b64(key),)
    (dist / "AdMeNot-9.9.8-setup.exe.sha256").write_text(f"{SHA} *x\n", "utf-8")
    pub.release("9.9.8", NOTES, key=key, today=DAY, fetch=lambda url: (SHA, 1), dist=dist, out=out,
                keys=keys, min_supported="9.0.0", min_reason={"pl": "Błąd", "en": "Bug"})
    raw = pub.release("9.9.9", NOTES, key=key, today=DAY, fetch=lambda url: (SHA, 1), dist=dist,
                      out=out, keys=keys)
    m = update.verify(raw, keys)
    assert m.min_supported == "9.0.0" and m.reason_for("pl") == "Błąd"


def test_release_with_a_key_the_program_does_not_trust(pub, key, dist, tmp_path):
    with pytest.raises(pub.PublishError, match="update_key.py"):
        pub.release("9.9.9", NOTES, key=key, today=DAY, fetch=lambda url: (SHA, 1), dist=dist,
                    out=tmp_path / "m.json", keys=())


def test_retire_raises_the_minimum_only(pub, key, dist, tmp_path):
    out = tmp_path / "manifest.json"
    keys = (public_b64(key),)
    pub.release("9.9.9", NOTES, key=key, today=DAY, fetch=lambda url: (SHA, 1), dist=dist,
                out=out, keys=keys, min_supported="9.0.0")
    raw = pub.retire("9.9.0", {"pl": "Psuje cofanie", "en": "Breaks undo"}, key=key,
                     today=date(2026, 10, 21), out=out, keys=keys)
    m = update.verify(raw, keys)
    assert (m.latest, m.min_supported, m.reason_for("en")) == ("9.9.9", "9.9.0", "Breaks undo")
    assert m.published == date(2026, 10, 21) and m.notes == NOTES
    with pytest.raises(pub.PublishError):
        pub.retire("9.0.0", {"pl": "x", "en": "x"}, key=key, today=DAY, out=out, keys=keys)


def test_retire_needs_a_manifest(pub, key, tmp_path):
    with pytest.raises(pub.PublishError):
        pub.retire("9.9.0", {"pl": "x", "en": "x"}, key=key, today=DAY, out=tmp_path / "m.json",
                   keys=(public_b64(key),))


def test_fetch_digest_streams_the_file(pub):
    stub = Stub(body=b"MZ" * 1000, content_type="application/octet-stream")
    stop = serve(stub)
    try:
        digest, size = pub.fetch_digest(stub.url + "/setup.exe")
    finally:
        stop()
    assert (digest, size) == (hashlib.sha256(b"MZ" * 1000).hexdigest(), 2000)


def test_signed_file_is_pretty_and_utf8(pub, key):
    raw = pub.sign({"notes": {"pl": "Zażółć"}}, key)
    outer = json.loads(raw)
    assert set(outer) == {"payload", "sig"} and "Zażółć" in raw.decode("utf-8")
