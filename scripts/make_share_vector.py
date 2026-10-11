"""Wektor testowy planu dla klienta: ten sam plik czyta pytest (test_share) i vitest (server/test/plan-page).

Uruchom po zmianie formatu w engine/share.py: .venv\\Scripts\\python scripts\\make_share_vector.py
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from admenot.engine import share

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "share_vector.json"
PAYLOAD = {
    "v": 1, "lang": "pl", "at": "2026-10-11T14:32", "phone": "Redmi Note 13", "code": "7F3K",
    "notif": 0, "shop": "Serwis XYZ",
    "apps": [
        {"n": "Czyszczenie telefonu", "l": "remove", "i": None},
        {"n": "Latarka 🔦", "l": "silence", "i": None},
        {"n": "<img src=x onerror=alert(1)>", "l": "disable", "i": None},
        {"n": "Usługi Google Play", "l": "disable", "b": 1, "i": None},
    ],
}


def main() -> None:
    key = bytes(range(32))
    nonce = bytes(range(100, 112))
    blob, key_text = share.encrypt(PAYLOAD, key=key, nonce=nonce)
    local = share.local_url("https://x", PAYLOAD)
    assert local is not None
    vector = {
        "key": key_text,
        "blob": base64.b64encode(blob).decode("ascii"),
        "payload": PAYLOAD,
        "local_fragment": local.split("#", 1)[1],
        "local_payload": share.decode_local(local),
        "local_limit": share.LOCAL_LIMIT,  # UI sprawdza, że kod tej długości da się zeskanować
    }
    OUT.write_text(json.dumps(vector, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"zapisano {OUT}")


if __name__ == "__main__":
    main()
