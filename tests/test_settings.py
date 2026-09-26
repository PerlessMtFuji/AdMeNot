import json

import pytest

from demalware.engine import settings as S
from demalware.engine.paths import backups_dir, settings_path


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


@pytest.mark.parametrize(("locale_name", "lang"), [
    (("Polish_Poland", "1250"), "pl"), (("pl_PL", "UTF-8"), "pl"),
    (("en_US", "UTF-8"), "en"), ((None, None), "en"),
])
def test_system_lang(monkeypatch, locale_name, lang):
    monkeypatch.setattr(S.locale, "getlocale", lambda *a: locale_name)
    assert S.system_lang() == lang
    assert S.effective_lang(S.Settings()) == lang
    assert S.effective_lang(S.Settings(lang="pl")) == "pl"
