import json

import pytest

from demalware.engine import settings as S
from demalware.engine.paths import backups_dir, reports_dir, settings_path
from demalware.engine.settings import (
    MAX_LOGO_BYTES,
    LogoError,
    ServiceInfo,
    check_logo,
    load_service,
    save_service,
)


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def test_defaults_without_a_file():
    assert S.load_settings() == S.Settings()
    assert settings_path().name == "settings.json"


def test_save_and_load_keeps_unknown_keys():
    path = settings_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"service": {"name": "Serwis & Syn"}}), "utf-8")
    saved = S.save_settings({"mode": "expert", "lang": "en"})
    assert saved == S.Settings(lang="en", mode="expert")
    data = json.loads(path.read_text("utf-8"))
    assert data["service"] == {"name": "Serwis & Syn"} and data["mode"] == "expert"
    assert not list(path.parent.glob("*.tmp"))
    assert S.save_settings({"adb_path": None}).adb_path is None


def test_corrupted_file_gives_defaults_and_a_bad_copy():
    path = settings_path()
    path.parent.mkdir(parents=True)
    path.write_text("{nie json", "utf-8")
    assert S.load_settings() == S.Settings()
    assert (path.parent / "settings.json.bad").read_text("utf-8") == "{nie json"
    path.write_text("[1, 2]", "utf-8")
    assert S.load_settings() == S.Settings()


def test_bad_values_in_file_are_ignored_and_rejected_on_save():
    path = settings_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"lang": "de", "mode": "expert", "adb_path": ""}), "utf-8")
    assert S.load_settings() == S.Settings(mode="expert")
    with pytest.raises(ValueError):
        S.save_settings({"lang": "de"})
    with pytest.raises(ValueError):
        S.save_settings({"colour": "red"})


def test_backups_dir_follows_the_setting(data_dir):
    assert backups_dir() == data_dir / "DeMalware" / "backups"
    S.save_settings({"backups_dir": str(data_dir / "kopie")})
    assert backups_dir() == data_dir / "kopie"


def test_theme_default_valid_values_and_rejection():
    assert S.load_settings().theme == "system"
    assert S.save_settings({"theme": "dark"}).theme == "dark"
    with pytest.raises(ValueError):
        S.save_settings({"theme": "blue"})
    settings_path().write_text('{"theme": "neon", "mode": "expert"}', "utf-8")
    assert S.load_settings() == S.Settings(mode="expert")


@pytest.mark.parametrize(("locale_name", "lang"), [
    (("Polish_Poland", "1250"), "pl"), (("pl_PL", "UTF-8"), "pl"),
    (("en_US", "UTF-8"), "en"), ((None, None), "en"),
])
def test_system_lang(monkeypatch, locale_name, lang):
    monkeypatch.setattr(S.locale, "getlocale", lambda *a: locale_name)
    assert S.system_lang() == lang
    assert S.effective_lang(S.Settings()) == lang
    assert S.effective_lang(S.Settings(lang="pl")) == "pl"


def test_reports_dir(data_dir):
    assert reports_dir() == data_dir / "DeMalware" / "reports"


def test_service_round_trip_keeps_other_settings(data_dir):
    S.save_settings({"lang": "en", "mode": "expert"})
    info = ServiceInfo("Serwis „Ząb” & Syn", "ul. Długa 1, Łódź", "+48 600 000 000",
                       data_dir / "logo.png")
    save_service(info)
    assert load_service() == info
    assert S.load_settings() == S.Settings(lang="en", mode="expert")
    data = json.loads(settings_path().read_text("utf-8"))
    assert data["service"]["logo"] == str(data_dir / "logo.png")
    assert not list(settings_path().parent.glob("*.tmp"))
    S.save_settings({"mode": "simple"})
    assert load_service() == info  # zapis ustawień nie rusza sekcji service


@pytest.mark.parametrize("content", ["", "{zepsuty", "[]", '{"service": "x"}',
                                     '{"service": {"name": 5, "phone": "  "}}'])
def test_missing_or_broken_settings_give_empty_service(content):
    assert load_service() == ServiceInfo()
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(content, "utf-8")
    assert load_service() == ServiceInfo()


def test_save_service_over_broken_file():
    settings_path().parent.mkdir(parents=True)
    settings_path().write_text("{zepsuty", "utf-8")
    save_service(ServiceInfo(name="X"))
    assert load_service() == ServiceInfo(name="X")


def test_check_logo(data_dir):
    png = data_dir / "logo.PNG"
    png.write_bytes(b"\x89PNG....")
    assert check_logo(png) == png.resolve()
    for path, content, key in [
        (data_dir / "nie-ma.png", None, "missing"),
        (data_dir / "logo.gif", b"GIF89a", "type"),
        (data_dir / "big.png", b"0" * (MAX_LOGO_BYTES + 1), "size"),
    ]:
        if content is not None:
            path.write_bytes(content)
        with pytest.raises(LogoError) as exc:
            check_logo(path)
        assert exc.value.key == key
