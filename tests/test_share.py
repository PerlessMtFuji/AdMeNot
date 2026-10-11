import base64
import hashlib
import io
import json
from datetime import datetime

import pytest
from PIL import Image

from admenot.engine import share
from admenot.engine.actions.context import PhoneContext
from admenot.engine.actions.planner import AppPlan, Blocked
from admenot.engine.device.info import DeviceInfo
from admenot.engine.facts import AppFacts
from admenot.engine.workflow import OrderPlan

AT = datetime(2026, 10, 11, 14, 32)
BASE = "https://admenot.test"


def _icon(size: int = 192, fmt: str = "PNG") -> str:
    out = io.BytesIO()
    Image.new("RGBA", (size, size), (200, 30, 30, 255)).save(out, fmt)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(out.getvalue()).decode("ascii")


def _results():
    return [AppPlan("com.clean.pro", "remove", [], ["app_data_lost"]),
            AppPlan("com.flash.light", "silence", [], []),
            Blocked("com.google.android.gms", "disable", "protected")]


def _plan(sdk: int = 34, serial: str = "R58N123", results=None, icons: bool = True) -> OrderPlan:
    device = DeviceInfo(serial, "xiaomi", "Xiaomi", "23129RAA4G", "sapphire", "Redmi Note 13", "14",
                        sdk, None, 0.0, AT)
    ctx = PhoneContext(sdk, "Xiaomi", None, None, {}, frozenset(), {})
    results = _results() if results is None else results
    facts = {r.package: AppFacts(r.package, icon=_icon() if icons else None) for r in results}
    return OrderPlan(device, ctx, facts, results)


NAMES = {"com.clean.pro": "Czyszczenie telefonu", "com.flash.light": "Latarka",
         "com.google.android.gms": "Usługi Google Play"}


def _payload(plan=None, **kw):
    return share.build_payload(plan or _plan(), lang="pl", phone="Redmi Note 13", at=AT,
                               names=NAMES, **kw)


def test_code_is_four_chars_from_the_alphabet_and_stable():
    code = share.plan_code(_plan())
    assert len(code) == 4 and set(code) <= set(share.CODE_ALPHABET)
    assert share.plan_code(_plan()) == code
    assert share.plan_code(_plan(results=list(reversed(_results())))) == code


@pytest.mark.parametrize("variant", [
    {"serial": "OTHER"},
    {"sdk": 32},
    {"results": [AppPlan("com.clean.pro", "disable", [], [])] + _results()[1:]},
    {"results": _results()[:2]},
    {"results": _results()[:2] + [AppPlan("com.google.android.gms", "disable", [], [])]},
])
def test_code_changes_with_phone_notif_level_apps_and_block(variant):
    assert share.plan_code(_plan(**variant)) != share.plan_code(_plan())


@pytest.mark.parametrize(("sdk", "notif"), [(33, 1), (34, 1), (32, 0), (31, 0), (0, 0)])
def test_notif_flag_follows_android_13(sdk, notif):
    assert _payload(_plan(sdk=sdk))["notif"] == notif


def test_payload_has_names_levels_and_no_package_names():
    p = _payload(shop="Serwis XYZ")
    assert p["v"] == 1 and p["lang"] == "pl" and p["at"] == "2026-10-11T14:32"
    assert p["shop"] == "Serwis XYZ" and p["phone"] == "Redmi Note 13"
    assert p["code"] == share.plan_code(_plan())
    assert [(a["n"], a["l"], a.get("b")) for a in p["apps"]] == [
        ("Czyszczenie telefonu", "remove", None), ("Latarka", "silence", None),
        ("Usługi Google Play", "disable", 1)]
    assert all(a["i"].startswith("data:image/webp;base64,") for a in p["apps"])
    assert "com." not in json.dumps(p)


def test_shop_is_omitted_without_name_and_icons_without_flag():
    p = _payload(icons=False)
    assert "shop" not in p and all("i" not in a for a in p["apps"])


def test_name_falls_back_to_package_when_unknown():
    p = share.build_payload(_plan(), lang="pl", phone="X", at=AT, names={})
    assert p["apps"][0]["n"] == "com.clean.pro"


def test_shrink_icon_makes_small_webp():
    out = share.shrink_icon(_icon(192))
    assert out is not None and out.startswith("data:image/webp;base64,")
    with Image.open(io.BytesIO(base64.b64decode(out.split(",", 1)[1]))) as img:
        assert img.format == "WEBP" and max(img.size) <= 48


@pytest.mark.parametrize("bad", [None, "", "x", "data:image/png;base64,AAAA",
                                 "data:image/svg+xml;base64,PHN2Zy8+"])
def test_shrink_icon_rejects_garbage(bad):
    assert share.shrink_icon(bad) is None


def _size(p) -> int:
    return len(json.dumps(p, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def test_fit_drops_icons_from_the_end():
    p = _payload()
    last = len(p["apps"][-1]["i"])
    fitted = share.fit(p, _size(p) - last // 2)
    assert fitted["apps"][-1]["i"] is None and fitted["apps"][0]["i"] is not None
    assert p["apps"][-1]["i"] is not None  # wejście nietknięte


def test_fit_leaves_small_payload_alone():
    p = _payload()
    assert share.fit(p) == p


def test_encrypt_round_trip_and_fresh_key_each_time():
    p = _payload()
    blob, key = share.encrypt(p)
    assert blob[0] == 1 and len(key) == 43
    assert share.decrypt(blob, key) == p
    blob2, key2 = share.encrypt(p)
    assert key2 != key and blob2[1:13] != blob[1:13]


def test_decrypt_rejects_wrong_key_and_version():
    blob, _ = share.encrypt(_payload())
    _, other = share.encrypt(_payload())
    with pytest.raises(ValueError):
        share.decrypt(blob, other)
    with pytest.raises(ValueError):
        share.decrypt(b"\x02" + blob[1:], other)


def test_server_url_carries_key_only_in_fragment():
    url = share.server_url(BASE, "A" * 22, "k" * 43)
    assert url == f"{BASE}/plan#s.{'A' * 22}.{'k' * 43}"


def test_local_url_round_trip_truncates_names():
    long = {**NAMES, "com.clean.pro": "Bardzo długa nazwa aplikacji czyszczącej telefon z reklamami"}
    p = share.build_payload(_plan(), lang="pl", phone="X", at=AT, names=long, icons=False)
    url = share.local_url(BASE, p)
    assert url is not None and url.startswith(f"{BASE}/plan#l.")
    back = share.decode_local(url)
    assert back["apps"][0]["n"] == long["com.clean.pro"][:39] + "…"
    assert back["apps"][1:] == p["apps"][1:]


def test_local_url_is_none_when_too_long():
    results = [AppPlan(f"com.app{i}", "remove", [], []) for i in range(80)]
    # Nazwy bez powtórzeń: deflate nie może ich ścisnąć poniżej limitu.
    names = {r.package: "Aplikacja " + hashlib.sha256(str(i).encode()).hexdigest()[:30]
             for i, r in enumerate(results)}
    p = share.build_payload(_plan(results=results), lang="pl", phone="X", at=AT, names=names,
                            icons=False)
    assert share.local_url(BASE, p) is None


def test_vector_fixture_matches_python_format():
    from pathlib import Path
    vec = json.loads((Path(__file__).parent / "fixtures" / "share_vector.json").read_text("utf-8"))
    blob = base64.b64decode(vec["blob"])
    assert share.decrypt(blob, vec["key"]) == vec["payload"]
    assert share.decode_local(vec["local_fragment"]) == vec["local_payload"]


def _png_header(width: int, height: int) -> str:
    """Mały plik PNG, który deklaruje ogromny obraz (ikona z adware jest wrogim wejściem)."""
    import struct
    import zlib as z

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", z.crc32(kind + data))

    raw = z.compress(b"\x00" * (width // 8 + 1) * 4)  # ucięte dane: dekoder i tak alokuje cały obraz
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
           + chunk(b"IDAT", raw) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def test_shrink_icon_rejects_huge_declared_size():
    assert share.shrink_icon(_png_header(11000, 11000)) is None


@pytest.mark.parametrize("exc", [EOFError, SyntaxError, MemoryError, RuntimeError])
def test_shrink_icon_turns_any_decoder_failure_into_none(monkeypatch, exc):
    def boom(*_a, **_k):
        raise exc("dekoder")
    monkeypatch.setattr(share.Image, "open", boom)
    assert share.shrink_icon(_icon()) is None
