import pytest

from admenot.engine.phones.names import (
    canonical_brand,
    key_tokens,
    model_key,
    name_tokens,
    norm_name,
    parse_battery_mah,
    parse_display_in,
    parse_year,
    record_slugs,
    slug_from_name,
    slug_from_url,
    split_codes,
    with_brand,
)

GSM = "https://www.gsmarena.com/"


@pytest.mark.parametrize(("url", "slug"), [
    (GSM + "samsung_galaxy_a14-12151.php", "samsung-galaxy-a14"),
    (GSM + "samsung_galaxy_s25+-13609.php", "samsung-galaxy-s25-plus"),
    (GSM + "oppo_reno6_pro_5g_(snapdragon)-11093.php", None),  # nawias: Szklodo bierze nazwę
    (None, None),
])
def test_slug_from_url(url, slug):
    assert slug_from_url(url) == slug


def test_slug_from_name():
    assert slug_from_name("Oppo Reno6 Pro 5G (Snapdragon)") == "oppo-reno6-pro-5g-snapdragon"


def test_record_slugs_skip_placeholders_and_number_duplicates():
    records = [
        {"name": "Nokia X", "url": GSM + "nokia_x-1.php"},
        {"name": "  ", "url": GSM + "nokia_y-5.php"},
        {"name": "Nokia X", "url": GSM + "nokia_x-2.php"},
        {"name": "Nokia X"},
    ]
    assert record_slugs(records) == ["nokia-x", None, "nokia-x-2", "nokia-x-3"]


@pytest.mark.parametrize(("raw", "key"), [
    ("SM-A145F/DSN", "SM-A145F"),
    (" sm-a145r ", "SM-A145R"),
    ("\u200eELN2-W29", "ELN2-W29"),
    ("Pixel  7", "PIXEL 7"),
    ("", None),
    ("   ", None),
    (None, None),
])
def test_model_key(raw, key):
    assert model_key(raw) == key


def test_split_codes_drops_garbage_and_duplicates():
    models = "SM-A576B, SM-A576B/DS, &, 1050;100, \u200eXQES54EUKCB.GC, LS450"
    assert split_codes(models) == ["SM-A576B", "XQES54EUKCB.GC", "LS450"]
    assert split_codes(None) == []


def test_name_tokens():
    assert name_tokens("Redmi Note 12 Pro+5G") == ["redmi", "note", "12", "pro", "plus", "5g"]
    assert name_tokens("Lenovo Lenovo Tab M10 (HD)") == ["lenovo", "tab", "m10", "hd"]
    assert norm_name("Samsung Galaxy S25+") == "samsung galaxy s25 plus"
    assert norm_name("samsung-galaxy-a57-5g") == "samsung galaxy a57 5g"


def test_key_tokens_ignore_network_suffixes():
    assert key_tokens(["samsung", "galaxy", "a14", "5g"]) == {"a14"}
    assert key_tokens(["huawei", "nova"]) == frozenset()


def test_brands():
    assert canonical_brand("Redmi") == "xiaomi"
    assert canonical_brand("LGE") == "lg"
    assert canonical_brand("TCT (Alcatel)") == "alcatel"
    assert canonical_brand("OPPO") == "oppo"
    assert canonical_brand("") == ""
    assert with_brand("xiaomi", "Redmi Note 13") == "xiaomi redmi note 13"
    assert with_brand("samsung", "Samsung Galaxy A14") == "samsung galaxy a14"
    assert with_brand("", "Galaxy A14") == "galaxy a14"
    assert with_brand("huawei", "华为畅享") == ""  # z nazwy nic nie zostało


def test_parsers():
    assert parse_year("2023, February 28") == 2023
    assert parse_year("Cancelled") is None
    assert parse_display_in("6.6 inches, 104.9 cm2 (~83.9% screen-to-body ratio)") == 6.6
    assert parse_display_in(None) is None
    assert parse_battery_mah("Li-Po 5000 mAh, non-removable") == 5000
    assert parse_battery_mah(None) is None
