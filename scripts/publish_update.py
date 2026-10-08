"""Publikacja manifestu aktualizacji (spec aktualizacji §3): keygen | release | retire.

Klucz prywatny: %USERPROFILE%\\.admenot\\update-signing-key.pem (ADMENOT_SIGNING_KEY nadpisuje),
PEM PKCS#8 zaszyfrowany hasłem — nigdy w repo. Wynik: server/public/updates/v1/manifest.json;
commit i `wrangler deploy` ręcznie (docs/release.md).
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import sys
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from admenot.net import client, update

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "server" / "public" / "updates" / "v1" / "manifest.json"
DIST = ROOT / "dist" / "release"
KEY_ENV = "ADMENOT_SIGNING_KEY"


class PublishError(Exception):
    pass


def key_path() -> Path:
    override = os.environ.get(KEY_ENV)
    return Path(override) if override else Path.home() / ".admenot" / "update-signing-key.pem"


def public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def keygen(path: Path, password: bytes) -> str:
    if path.exists():
        raise PublishError(f"{path} już istnieje — nie nadpisuję klucza")
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8,
                                       BestAvailableEncryption(password)))
    return public_b64(key)


def load_key(path: Path, password: bytes) -> Ed25519PrivateKey:
    key = load_pem_private_key(path.read_bytes(), password)  # złe hasło → ValueError
    if not isinstance(key, Ed25519PrivateKey):
        raise PublishError(f"{path}: to nie klucz Ed25519")
    return key


def sign(payload: dict[str, Any], key: Ed25519PrivateKey) -> bytes:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sig = base64.b64encode(key.sign(text.encode("utf-8"))).decode("ascii")
    outer = json.dumps({"payload": text, "sig": sig}, ensure_ascii=False, indent=2)
    return (outer + "\n").encode("utf-8")


def fetch_digest(url: str) -> tuple[str, int]:
    """SHA-256 i rozmiar pliku spod `url`, strumieniowo (przekierowania GitHuba obsługuje urllib)."""
    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(url, headers={"User-Agent": client.user_agent()})
    with urllib.request.urlopen(request, timeout=60) as response:
        while chunk := response.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _old_payload(out: Path) -> dict[str, Any] | None:
    if not out.exists():
        return None
    return json.loads(json.loads(out.read_bytes())["payload"])


def _write(out: Path, raw: bytes, keys: Sequence[str] | None) -> None:
    try:
        update.verify(raw, keys)  # ten sam kod co program
    except update.ManifestError as exc:
        raise PublishError(f"{exc} — czy klucz publiczny w src/admenot/net/update_key.py "
                           "pasuje do klucza prywatnego?") from None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)


def release(version: str, notes: dict[str, str], *, key: Ed25519PrivateKey, today: date,
            fetch: Callable[[str], tuple[str, int]] = fetch_digest, dist: Path = DIST,
            out: Path = MANIFEST, keys: Sequence[str] | None = None,
            min_supported: str | None = None, min_reason: dict[str, str] | None = None,
            download_base: str | None = None) -> bytes:
    update.parse_version(version)
    name = f"AdMeNot-{version}-setup.exe"
    sha_file = dist / f"{name}.sha256"
    if not sha_file.is_file():
        raise PublishError(f"brak {sha_file} — najpierw scripts/build_release.py")
    expected = sha_file.read_text("utf-8").split()[0].lower()
    url = f"{download_base or update.URL_PREFIX + f'v{version}/'}{name}"
    digest, size = fetch(url)
    if digest != expected:
        raise PublishError(f"SHA-256 pliku pod {url} ({digest}) ≠ lokalny build ({expected})")
    old = _old_payload(out)
    minimum = min_supported or (old["min_supported"] if old else version)
    if old:
        # zainstalowane programy nigdy nie cofają manifestu (store), więc obniżka zablokowałaby je na stałe
        if update.parse_version(minimum) < update.parse_version(old["min_supported"]):
            raise PublishError(f"min_supported {minimum} < obecne {old['min_supported']} "
                               "— release nie obniża minimum")
        if update.parse_version(version) < update.parse_version(old["latest"]):
            raise PublishError(f"wersja {version} < obecna {old['latest']} — release nie cofa wersji")
    payload: dict[str, Any] = {
        "format": update.FORMAT, "latest": version, "published": today.isoformat(),
        "min_supported": minimum, "url": url, "sha256": digest, "size": size, "notes": notes,
    }
    if min_reason:
        payload["min_reason"] = min_reason
    elif old and old.get("min_reason") and old["min_supported"] == minimum:
        payload["min_reason"] = old["min_reason"]
    raw = sign(payload, key)
    _write(out, raw, keys)
    return raw


def retire(minimum: str, reason: dict[str, str], *, key: Ed25519PrivateKey, today: date,
           out: Path = MANIFEST, keys: Sequence[str] | None = None) -> bytes:
    old = _old_payload(out)
    if old is None:
        raise PublishError(f"brak {out} — najpierw release")
    if update.parse_version(minimum) <= update.parse_version(old["min_supported"]):
        raise PublishError(f"min_supported to już {old['min_supported']} — retire tylko podnosi")
    payload = {**old, "min_supported": minimum, "min_reason": reason, "published": today.isoformat()}
    raw = sign(payload, key)
    _write(out, raw, keys)
    return raw


def _password(prompt: str = "Hasło klucza: ") -> bytes:
    return getpass.getpass(prompt).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manifest aktualizacji AdMeNot")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("keygen")
    rel = sub.add_parser("release")
    rel.add_argument("version")
    rel.add_argument("--notes-pl", type=Path, required=True)
    rel.add_argument("--notes-en", type=Path, required=True)
    rel.add_argument("--min")
    rel.add_argument("--reason-pl")
    rel.add_argument("--reason-en")
    rel.add_argument("--download-base")  # tylko próba ręczna z lokalnym serwerem (docs/release.md)
    ret = sub.add_parser("retire")
    ret.add_argument("--min", required=True)
    ret.add_argument("--reason-pl", required=True)
    ret.add_argument("--reason-en", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "keygen":
            password = _password()
            if not password or password != _password("Powtórz hasło: "):
                raise PublishError("hasła są puste albo się różnią")
            public = keygen(key_path(), password)
            print(f"Klucz prywatny: {key_path()} — zrób kopię zapasową (docs/release.md).")
            print(f"Dopisz do PUBLIC_KEYS w src/admenot/net/update_key.py:\n    {public!r},")
            return 0
        if args.command == "release" and bool(args.reason_pl) != bool(args.reason_en):
            raise PublishError("--reason-pl i --reason-en podaje się razem")
        key = load_key(key_path(), _password())
        if args.command == "release":
            notes = {"pl": args.notes_pl.read_text("utf-8").strip(),
                     "en": args.notes_en.read_text("utf-8").strip()}
            reason = {"pl": args.reason_pl, "en": args.reason_en} if args.reason_pl else None
            release(args.version, notes, key=key, today=date.today(), min_supported=args.min,
                    min_reason=reason, download_base=args.download_base)
        else:
            retire(args.min, {"pl": args.reason_pl, "en": args.reason_en}, key=key,
                   today=date.today())
    except (PublishError, OSError, ValueError) as exc:  # ValueError: złe hasło, zła wersja
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1
    print(f"Zapisano {MANIFEST.relative_to(ROOT)} — commit i wrangler deploy (docs/release.md).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
