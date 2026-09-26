import threading
import xml.etree.ElementTree as ET

import pytest
from phonedb import make_device, make_phone_assets

from demalware.engine.phones.provider import SILHOUETTE, PhoneImageProvider


@pytest.fixture(scope="module")
def assets(tmp_path_factory):
    return make_phone_assets(tmp_path_factory.mktemp("phones"))


@pytest.fixture
def provider(assets, tmp_path):
    return PhoneImageProvider(assets, tmp_path / "overrides.json")


def _summary(m):
    return m.confidence, m.step, m.phone.slug if m.phone else None


def test_model_code(provider, assets):
    m = provider.match(make_device("SM-A145R"))
    assert _summary(m) == ("exact", "model_code", "samsung-galaxy-a14")
    assert m.matched == "SM-A145R" and m.has_photo
    assert m.image == assets / "phones" / "samsung-galaxy-a14.webp"
    assert (m.phone.name, m.phone.year) == ("Samsung Galaxy A14", 2023)


def test_model_code_is_case_insensitive(provider):
    m = provider.match(make_device("sm-a576b"))
    assert _summary(m) == ("exact", "model_code", "samsung-galaxy-a57-5g")


def test_market_name_with_brand_alias(provider):
    m = provider.match(make_device("23129RAA4X", brand="Redmi", manufacturer="Xiaomi",
                                   market_name="Redmi Note 13"))
    assert _summary(m) == ("exact", "market_name", "xiaomi-redmi-note-13")
    assert m.matched == "xiaomi redmi note 13"


def test_gplay_marketing_name(provider):
    m = provider.match(make_device("23129RAA4G", brand="Redmi", manufacturer="Xiaomi",
                                   device="sapphire"))
    assert _summary(m) == ("exact", "gplay", "xiaomi-redmi-note-13")


def test_vendor_market_name_is_matched_exactly(provider):
    m = provider.match(make_device("CPH2247X", brand="OPPO", manufacturer="OPPO",
                                   market_name="OPPO Reno6 Pro 5G (Snapdragon)"))
    assert _summary(m) == ("exact", "market_name", "oppo-reno6-pro-5g-snapdragon")


def test_gplay_name_matches_slug_variant(provider):
    m = provider.match(make_device("SM-A576E", device="A57X"))  # wielkość liter bez znaczenia
    assert _summary(m) == ("exact", "gplay", "samsung-galaxy-a57-5g")


def test_matched_phone_without_photo_uses_silhouette(provider):
    m = provider.match(make_device("Pixel 7", brand="google", manufacturer="Google",
                                   device="panther"))
    assert _summary(m) == ("exact", "gplay", "google-pixel-7")
    assert m.image == SILHOUETTE and not m.has_photo


def test_fuzzy_prefers_closest_name(provider):
    m = provider.match(make_device("SM-A145X", device="a14lte"))
    assert _summary(m) == ("approximate", "fuzzy", "samsung-galaxy-a14")
    assert m.matched == "samsung galaxy a14 lte"


def test_fuzzy_needs_same_model_number(provider):
    m = provider.match(make_device("SM-A155F", market_name="Galaxy A15"))
    assert _summary(m) == ("none", "silhouette", None)


def test_bare_number_is_not_enough_for_fuzzy(provider):
    # „华为畅享8” → „huawei 8”; w bazie jest „Huawei nova 8”, ale to nie ten telefon
    m = provider.match(make_device("FLA-AL00", brand="HUAWEI", manufacturer="HUAWEI",
                                   device="HWFLA-H"))
    assert _summary(m) == ("none", "silhouette", None)


def test_unknown_phone_gets_silhouette(provider):
    m = provider.match(make_device("CPH2271", brand="OPPO", manufacturer="OPPO",
                                   device="OP4F97"))
    assert _summary(m) == ("none", "silhouette", None)
    assert m.image == SILHOUETTE and m.image.is_file() and not m.has_photo


def test_silhouette_is_svg_of_photo_size():
    root = ET.parse(SILHOUETTE).getroot()
    assert root.tag.endswith("svg") and root.get("viewBox") == "0 0 160 212"


def test_missing_db(tmp_path):
    provider = PhoneImageProvider(tmp_path / "none", tmp_path / "o.json")
    assert not provider.available
    m = provider.match(make_device("SM-A145R"))
    assert _summary(m) == ("none", "no_db", None) and m.image == SILHOUETTE


def test_corrupted_db(tmp_path):
    (tmp_path / "phones.db").write_bytes(b"to nie jest baza SQLite")
    m = PhoneImageProvider(tmp_path, tmp_path / "o.json").match(make_device("SM-A145R"))
    assert _summary(m) == ("none", "no_db", None)


def test_index_is_built_once_under_concurrency(provider):
    n = 8
    barrier = threading.Barrier(n)
    results: list[tuple[str, str, str | None]] = [None] * n

    def run(i):
        barrier.wait()
        results[i] = _summary(provider.match(make_device("SM-A145X", device="a14lte")))

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == [("approximate", "fuzzy", "samsung-galaxy-a14")] * n
    entries = provider._by_brand["samsung"]
    assert len(entries) == len({(tuple(tokens), slug) for tokens, _, slug in entries})


def test_to_dict(provider):
    d = provider.match(make_device("SM-A145R")).to_dict()
    assert (d["confidence"], d["step"], d["has_photo"]) == ("exact", "model_code", True)
    assert d["phone"]["slug"] == "samsung-galaxy-a14"
    assert d["image"].endswith("samsung-galaxy-a14.webp")
