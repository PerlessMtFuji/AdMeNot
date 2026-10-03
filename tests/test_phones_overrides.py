import pytest
from phonedb import make_device, make_phone_assets

from admenot.engine.phones.provider import PhoneImageProvider


@pytest.fixture(scope="module")
def assets(tmp_path_factory):
    return make_phone_assets(tmp_path_factory.mktemp("phones"))


@pytest.fixture
def overrides(tmp_path):
    return tmp_path / "data" / "phone_overrides.json"


@pytest.fixture
def provider(assets, overrides):
    return PhoneImageProvider(assets, overrides)


def _summary(m):
    return m.confidence, m.step, m.phone.slug if m.phone else None


def test_override_wins_and_can_be_cleared(provider):
    provider.set_override("SM-A145R", "samsung-galaxy-a14-5g")
    m = provider.match(make_device("sm-a145r"))
    assert _summary(m) == ("manual", "override", "samsung-galaxy-a14-5g")
    assert m.matched == "SM-A145R"
    assert provider.clear_override("SM-A145R") is True
    assert provider.clear_override("SM-A145R") is False
    assert _summary(provider.match(make_device("SM-A145R")))[0] == "exact"


def test_override_is_per_model_code(provider):
    provider.set_override("SM-A145R", "samsung-galaxy-a14-5g")
    assert _summary(provider.match(make_device("SM-A145F"))) == (
        "exact", "model_code", "samsung-galaxy-a14")


def test_override_is_saved_to_disk(assets, overrides, provider):
    provider.set_override("SM-A145R", "huawei-nova-8")
    again = PhoneImageProvider(assets, overrides)
    assert _summary(again.match(make_device("SM-A145R"))) == ("manual", "override", "huawei-nova-8")


def test_set_override_validates_input(provider, overrides):
    with pytest.raises(KeyError):
        provider.set_override("SM-A145R", "nokia-3310")
    with pytest.raises(ValueError):
        provider.set_override("  ", "samsung-galaxy-a14")
    assert not overrides.exists()


def test_stale_override_falls_back(provider, overrides):
    overrides.parent.mkdir(parents=True)
    overrides.write_text('{"SM-A145R": "telefon-usuniety-z-bazy"}', "utf-8")
    assert _summary(provider.match(make_device("SM-A145R")))[0] == "exact"


def test_corrupted_overrides_file_is_ignored_and_replaced(provider, overrides):
    overrides.parent.mkdir(parents=True)
    overrides.write_text("{to nie json", "utf-8")
    assert _summary(provider.match(make_device("SM-A145R")))[0] == "exact"
    provider.set_override("SM-A145R", "samsung-galaxy-a14-5g")
    assert _summary(provider.match(make_device("SM-A145R")))[0] == "manual"


def test_search(provider):
    assert [r.slug for r in provider.search("galaxy a14")] == [
        "samsung-galaxy-a14", "samsung-galaxy-a14-5g"]
    assert [r.slug for r in provider.search("M31")] == [
        "samsung-galaxy-m31", "samsung-galaxy-m31-prime"]
    assert [r.slug for r in provider.search("a14", limit=1)] == ["samsung-galaxy-a14"]
    assert provider.search("   ") == []


def test_phone_lookup(provider, tmp_path):
    assert provider.phone("huawei-nova-8").name == "Huawei nova 8"
    assert provider.phone("nope") is None
    missing = PhoneImageProvider(tmp_path / "none", tmp_path / "o.json")
    assert missing.phone("huawei-nova-8") is None and missing.search("nova") == []
