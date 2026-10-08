"""Manifest aktualizacji (spec aktualizacji §2, §4, §5): podpis Ed25519 i stan wersji.

Plik to `{"payload": "<JSON jako string>", "sig": "<base64>"}`; podpisane są bajty UTF-8
stringu `payload`, więc nie trzeba kanonizacji JSON-a. Bez wątków i bez GUI.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from admenot import __version__
from admenot.engine.paths import update_manifest_path
from admenot.net import client
from admenot.net.update_key import PUBLIC_KEYS

MANIFEST_PATH = "/updates/v1/manifest.json"
FORMAT = 1
URL_PREFIX = "https://github.com/PerlessMtFuji/AdMeNot/releases/download/"
LANGS = ("pl", "en")
_VERSION = re.compile(r"\d+\.\d+\.\d+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SHA = re.compile(r"[0-9a-f]{64}")


class ManifestError(ValueError):
    """Manifest odrzucony: zły podpis, zły format albo niedozwolona wartość."""


def parse_version(text: object) -> tuple[int, int, int]:
    if not isinstance(text, str) or not _VERSION.fullmatch(text):
        raise ManifestError(f"wersja: {text!r}")
    major, minor, patch = (int(part) for part in text.split("."))
    return major, minor, patch


@dataclass(frozen=True)
class Manifest:
    latest: str
    published: date
    min_supported: str
    url: str
    sha256: str
    size: int
    notes: dict[str, str]
    min_reason: dict[str, str] | None
    raw: bytes  # cały plik z podpisem — tak trafia do pamięci podręcznej

    def notes_for(self, lang: str) -> str:
        return self.notes.get(lang) or self.notes["en"]

    def reason_for(self, lang: str) -> str | None:
        if self.min_reason is None:
            return None
        return self.min_reason.get(lang) or self.min_reason["en"]


@dataclass(frozen=True)
class UpdateState:
    manifest: Manifest | None
    available: bool  # jest nowsza wersja
    retired: bool  # ta wersja jest poniżej min_supported


def _signed(payload: bytes, sig: bytes, keys: Sequence[str]) -> bool:
    for key in keys:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(sig, payload)
        except (InvalidSignature, ValueError):
            continue
        return True
    return False


def _texts(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
            isinstance(value.get(lang), str) and value[lang].strip() for lang in LANGS):
        raise ManifestError(f"{field}: potrzebne niepuste pl i en")
    return {lang: value[lang] for lang in LANGS}


def _allowed_url(url: Any) -> bool:
    if not isinstance(url, str) or not url.endswith(".exe"):
        return False
    prefixes = [URL_PREFIX]
    if os.environ.get(client.ENV_URL):  # tylko próba ręczna z lokalnym serwerem (spec §10.2)
        prefixes.append(client.base_url() + "/")
    return url.startswith(tuple(prefixes))


def _parse(data: Any, raw: bytes) -> Manifest:
    if not isinstance(data, dict):
        raise ManifestError("payload: to nie obiekt")
    if type(data.get("format")) is not int or data["format"] != FORMAT:
        raise ManifestError(f"format: {data.get('format')!r}")
    latest, minimum = data.get("latest"), data.get("min_supported")
    if parse_version(minimum) > parse_version(latest):
        raise ManifestError("min_supported > latest")
    published = data.get("published")
    if not isinstance(published, str) or not _DATE.fullmatch(published):
        raise ManifestError(f"published: {published!r}")
    try:
        day = date.fromisoformat(published)
    except ValueError:
        raise ManifestError(f"published: {published!r}") from None
    if not _allowed_url(data.get("url")):
        raise ManifestError(f"url: {data.get('url')!r}")
    sha = data.get("sha256")
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ManifestError("sha256")
    size = data.get("size")
    if type(size) is not int or size <= 0:
        raise ManifestError(f"size: {size!r}")
    notes = _texts(data.get("notes"), "notes")
    reason = None if data.get("min_reason") is None else _texts(data["min_reason"], "min_reason")
    return Manifest(latest, day, minimum, data["url"], sha, size, notes, reason, raw)


def verify(raw: bytes, keys: Sequence[str] | None = None) -> Manifest:
    """Sprawdza podpis i treść; każde naruszenie → `ManifestError`."""
    try:
        outer = json.loads(raw)
    except ValueError:
        raise ManifestError("to nie JSON") from None
    if not isinstance(outer, dict) or not isinstance(outer.get("payload"), str) \
            or not isinstance(outer.get("sig"), str):
        raise ManifestError("brak payload/sig")
    try:
        payload = outer["payload"].encode("utf-8")
        sig = base64.b64decode(outer["sig"], validate=True)
    except (binascii.Error, ValueError):  # UnicodeEncodeError to też ValueError
        raise ManifestError("payload/sig: złe kodowanie") from None
    if not _signed(payload, sig, PUBLIC_KEYS if keys is None else keys):
        raise ManifestError("zły podpis")
    try:
        data = json.loads(payload)
    except ValueError:
        raise ManifestError("payload: to nie JSON") from None
    return _parse(data, bytes(raw))


def state(manifest: Manifest | None, version: str = __version__) -> UpdateState:
    if manifest is None:
        return UpdateState(None, False, False)
    current = parse_version(version)
    return UpdateState(manifest, parse_version(manifest.latest) > current,
                       current < parse_version(manifest.min_supported))


def download_page(lang: str) -> str:
    return client.base_url() + ("/pl/" if lang == "pl" else "/")


def fetch() -> Manifest:
    """Manifest z serwera; `client.BackendError` (także 404 przed pierwszym wydaniem) albo `ManifestError`."""
    return verify(client.get_bytes(MANIFEST_PATH))


def cached(path: Path | None = None) -> Manifest | None:
    """Zapisany manifest, z ponownym sprawdzeniem podpisu — ręczna edycja pliku nic nie daje."""
    try:
        raw = (path or update_manifest_path()).read_bytes()
    except OSError:
        return None
    try:
        return verify(raw)
    except ManifestError:
        return None


def _not_older(new: Manifest, old: Manifest) -> bool:
    return new.published >= old.published and \
        parse_version(new.min_supported) >= parse_version(old.min_supported)


def store(manifest: Manifest, path: Path | None = None) -> bool:
    """Zapis tylko nie starszego manifestu: stary, prawdziwie podpisany plik nie zniesie blokady."""
    path = path or update_manifest_path()
    old = cached(path)
    if old is not None and not _not_older(manifest, old):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(manifest.raw)
    os.replace(tmp, path)
    return True


def retired(version: str = __version__, path: Path | None = None) -> Manifest | None:
    """Manifest, który wycofuje tę wersję — tylko z pamięci, bez sieci (spec §5)."""
    manifest = cached(path)
    return manifest if state(manifest, version).retired else None
