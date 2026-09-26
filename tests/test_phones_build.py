import sqlite3

import pytest
from phonedb import RECORDS, make_phone_assets, write_sources

from demalware.engine import paths
from demalware.engine.phones import build
from demalware.engine.phones.build import build_phone_db, read_gplay_csv


def _rows(db, sql):
    con = sqlite3.connect(db)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


@pytest.fixture
def built(tmp_path):
    images, gplay = write_sources(tmp_path / "src")
    stats = build_phone_db(RECORDS, images, gplay, tmp_path / "out")
    return stats, tmp_path / "out" / "phones.db"


def test_build_counts_and_phone_row(built):
    stats, db = built
    assert (stats.phones, stats.skipped, stats.with_image) == (10, 1, 9)
    assert (stats.codes, stats.code_conflicts, stats.names, stats.gplay_rows) == (13, 1, 11, 7)
    assert _rows(db, "SELECT * FROM phones WHERE slug = 'samsung-galaxy-a14'") == [
        ("samsung-galaxy-a14", "Samsung Galaxy A14", "Samsung", 2023, 6.6, 5000)]
    slugs = {r[0] for r in _rows(db, "SELECT slug FROM phones")}
    assert {"samsung-galaxy-s25-plus", "oppo-reno6-pro-5g-snapdragon",
            "samsung-galaxy-a57-5g"} <= slugs
    assert _rows(db, "SELECT value FROM meta WHERE key = 'schema_version'") == [("1",)]


def test_model_codes_are_normalized_and_first_record_wins(built):
    _, db = built
    codes = dict(_rows(db, "SELECT code, slug FROM model_codes"))
    assert codes["SM-A145F"] == "samsung-galaxy-a14"
    assert codes["SM-A576B"] == "samsung-galaxy-a57-5g"  # bez znaku ‎
    assert codes["SM-M315F"] == "samsung-galaxy-m31"      # M31 Prime ma ten sam kod
    assert not {"SM-A145F/DSN", "&", "1050;100"} & codes.keys()


def test_market_names_include_slug_variant(built):
    _, db = built
    names = dict(_rows(db, "SELECT norm_name, slug FROM market_names"))
    assert names["samsung galaxy a57"] == "samsung-galaxy-a57-5g"
    assert names["samsung galaxy a57 5g"] == "samsung-galaxy-a57-5g"
    assert names["samsung galaxy s25 plus"] == "samsung-galaxy-s25-plus"


@pytest.mark.parametrize("encoding", ["utf-16", "utf-8-sig", "utf-8"])
def test_read_gplay_csv_encodings(tmp_path, encoding):
    path = tmp_path / "g.csv"
    path.write_bytes(("Retail Branding,Marketing Name,Device,Model\r\n"
                      "Samsung,Galaxy A14,a14m,SM-A145R\r\n"
                      "X,,d,m\r\nshort,row\r\n").encode(encoding))
    assert read_gplay_csv(path) == [("Samsung", "a14m", "SM-A145R", "Galaxy A14")]


def test_images_are_synced_without_small_versions(tmp_path):
    images, gplay = write_sources(tmp_path / "src")
    out = tmp_path / "out"
    (out / "phones").mkdir(parents=True)
    (out / "phones" / "old-phone.webp").write_bytes(b"x")
    first = build_phone_db(RECORDS, images, gplay, out)
    assert (first.images_copied, first.images_removed) == (9, 1)
    copied = {p.name for p in (out / "phones").iterdir()}
    assert "samsung-galaxy-a14.webp" in copied and len(copied) == 9
    assert not any(name.endswith("-sm.webp") for name in copied)
    second = build_phone_db(RECORDS, images, gplay, out)
    assert (second.images_copied, second.images_removed) == (0, 0)


def test_failed_build_keeps_previous_db(tmp_path, monkeypatch):
    assets = make_phone_assets(tmp_path)
    before = (assets / "phones.db").read_bytes()

    def broken(path):
        raise ValueError("uszkodzony CSV")

    monkeypatch.setattr(build, "read_gplay_csv", broken)
    source = tmp_path / "szklodo"
    with pytest.raises(ValueError):
        build_phone_db(RECORDS, source / "public" / "assets" / "phones",
                       source / "supported_devices.csv", assets)
    assert (assets / "phones.db").read_bytes() == before
    assert not (assets / "phones.db.tmp").exists()


def test_missing_images_dir_does_not_touch_assets(tmp_path):
    assets = make_phone_assets(tmp_path)
    with pytest.raises(FileNotFoundError):
        build_phone_db(RECORDS, tmp_path / "nope", None, assets)
    assert len(list((assets / "phones").glob("*.webp"))) == 9


def test_assets_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMALWARE_ASSETS", str(tmp_path))
    assert paths.assets_dir() == tmp_path
    monkeypatch.delenv("DEMALWARE_ASSETS")
    assert paths.assets_dir() == paths.PACKAGE_ASSETS
    assert paths.PACKAGE_ASSETS.parent.name == "demalware"
