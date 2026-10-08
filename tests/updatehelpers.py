"""Podpisane manifesty do testów aktualizacji: klucz generowany w teście (spec aktualizacji §10.1)."""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from admenot.net import update

DROP = object()  # wartość w `signed(**changes)`: usuń to pole z payloadu
BASE = {
    "format": 1,
    "latest": "9.9.9",  # zawsze nowsza od __version__ programu
    "published": "2026-10-20",
    "min_supported": "0.9.0",
    "url": update.URL_PREFIX + "v9.9.9/AdMeNot-9.9.9-setup.exe",
    "sha256": "a" * 64,
    "size": 1234,
    "notes": {"pl": "Poprawki.", "en": "Fixes."},
}


def public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def signed(key: Ed25519PrivateKey, **changes: object) -> bytes:
    payload = {k: v for k, v in {**BASE, **changes}.items() if v is not DROP}
    text = json.dumps(payload, ensure_ascii=False)
    sig = base64.b64encode(key.sign(text.encode("utf-8"))).decode("ascii")
    return json.dumps({"payload": text, "sig": sig}).encode("utf-8")


def trust(monkeypatch) -> Ed25519PrivateKey:
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(update, "PUBLIC_KEYS", (public_b64(key),))
    return key
