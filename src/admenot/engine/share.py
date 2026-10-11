"""Plan naprawy dla klienta (spec 2026-10-11-plan-qr §3): kod kontrolny, treść, szyfrowanie.

Treść nie zawiera nazw pakietów ani kroków technicznych. Klucz trafia tylko do fragmentu adresu
(po `#`), którego przeglądarka nie wysyła na serwer.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import io
import json
import os
import warnings
import zlib
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image

from admenot.engine.actions.planner import NOTIF_PERMISSION_MIN_SDK, Blocked
from admenot.engine.apk.analyze import safe_icon
from admenot.engine.workflow import OrderPlan

CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # bez 0/O i 1/I
FORMAT = 1
BLOB_VERSION = 1
AAD = b"admenot-plan-v1"
PAYLOAD_LIMIT = 96 * 1024  # bajty JSON-a przed kompresją
LOCAL_LIMIT = 1500  # znaki fragmentu adresu w trybie bez serwera
LOCAL_NAME_MAX = 40
ICON_PX = 48
ICON_SRC_MAX = 1024  # ikony launchera mają do 512 px; większa deklaracja to wrogi plik z APK
PAGE_PATH = "/plan"


def notif_blocked(plan: OrderPlan) -> bool:
    """„Wycisz” odbiera uprawnienie do powiadomień tylko od Androida 13 (planner._silence_steps)."""
    return plan.ctx.sdk >= NOTIF_PERMISSION_MIN_SDK


def plan_code(plan: OrderPlan) -> str:
    apps = sorted([r.package, r.level, isinstance(r, Blocked)] for r in plan.results)
    canon = json.dumps({"serial": plan.device.serial, "notif": notif_blocked(plan), "apps": apps},
                       sort_keys=True, separators=(",", ":"))
    bits = int.from_bytes(hashlib.sha256(canon.encode("utf-8")).digest()[:3], "big") >> 4
    return "".join(CODE_ALPHABET[(bits >> shift) & 31] for shift in (15, 10, 5, 0))


def shrink_icon(uri: str | None) -> str | None:
    checked = safe_icon(uri)
    if checked is None:
        return None
    try:
        data = base64.b64decode(checked.split(",", 1)[1])
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
        with img:
            if max(img.size) > ICON_SRC_MAX:  # przed dekodowaniem: rozmiar pochodzi z nagłówka
                return None
            img = img.convert("RGBA")
            img.thumbnail((ICON_PX, ICON_PX))
            out = io.BytesIO()
            img.save(out, "WEBP", quality=80)
    except Exception:  # noqa: BLE001 — ikona z obcego APK: każdy błąd dekodera = inicjał na stronie
        return None
    return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def build_payload(plan: OrderPlan, *, lang: str, phone: str, at: datetime,
                  names: dict[str, str], shop: str | None = None,
                  icons: bool = True) -> dict[str, Any]:
    apps: list[dict[str, Any]] = []
    for r in plan.results:
        app: dict[str, Any] = {"n": names.get(r.package) or r.package, "l": r.level}
        if isinstance(r, Blocked):
            app["b"] = 1
        if icons:
            facts = plan.facts.get(r.package)
            app["i"] = shrink_icon(facts.icon if facts else None)
        apps.append(app)
    payload: dict[str, Any] = {"v": FORMAT, "lang": lang, "at": at.strftime("%Y-%m-%dT%H:%M"),
                               "phone": phone, "code": plan_code(plan),
                               "notif": 1 if notif_blocked(plan) else 0, "apps": apps}
    if shop:
        payload["shop"] = shop
    return payload


def _dump(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def fit(payload: dict[str, Any], limit: int = PAYLOAD_LIMIT) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    for app in reversed(out["apps"]):
        if len(_dump(out)) <= limit:
            break
        if app.get("i"):
            app["i"] = None
    return out


def _deflate(data: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -15)  # deflate-raw: DecompressionStream("deflate-raw")
    return c.compress(data) + c.flush()


def _inflate(data: bytes) -> bytes:
    return zlib.decompress(data, -15)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def encrypt(payload: dict[str, Any], *, key: bytes | None = None,
            nonce: bytes | None = None) -> tuple[bytes, str]:
    """`key`/`nonce` tylko dla wektora testowego (scripts/make_share_vector.py)."""
    key = key or AESGCM.generate_key(bit_length=256)
    nonce = nonce or os.urandom(12)
    sealed = AESGCM(key).encrypt(nonce, _deflate(_dump(payload)), AAD)
    return bytes([BLOB_VERSION]) + nonce + sealed, _b64url(key)


def decrypt(blob: bytes, key: str) -> dict[str, Any]:
    if len(blob) < 1 + 12 + 16 or blob[0] != BLOB_VERSION:
        raise ValueError("share blob format")
    try:
        plain = AESGCM(_unb64url(key)).decrypt(blob[1:13], blob[13:], AAD)
    except (InvalidTag, ValueError, binascii.Error) as exc:
        raise ValueError("share blob key") from exc
    return json.loads(_inflate(plain))


def server_url(base: str, share_id: str, key: str) -> str:
    return f"{base}{PAGE_PATH}#s.{share_id}.{key}"


def _short(name: str) -> str:
    return name if len(name) <= LOCAL_NAME_MAX else name[:LOCAL_NAME_MAX - 1] + "…"


def local_url(base: str, payload: dict[str, Any]) -> str | None:
    """Plan bez serwera: cała treść (bez ikon) w adresie; None = kod byłby nieczytelny."""
    slim = copy.deepcopy(payload)
    for app in slim["apps"]:
        app.pop("i", None)
        app["n"] = _short(app["n"])
    fragment = "l." + _b64url(_deflate(_dump(slim)))
    return None if len(fragment) > LOCAL_LIMIT else f"{base}{PAGE_PATH}#{fragment}"


def decode_local(url_or_fragment: str) -> dict[str, Any]:
    fragment = url_or_fragment.split("#", 1)[-1]
    if not fragment.startswith("l."):
        raise ValueError("not a local plan")
    return json.loads(_inflate(_unb64url(fragment[2:])))
