import json
from datetime import UTC, datetime

import pytest

from admenot.engine import welcome
from admenot.engine.paths import settings_path
from admenot.engine.settings import (
    INTERNAL_KEYS,
    SettingsTooNew,
    load_settings,
    save_internal,
    save_settings,
)

ID = "3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b"


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))


def test_defaults_mean_no_consent_and_no_welcome():
    s = load_settings()
    assert (s.welcome_version, s.telemetry, s.telemetry_packages, s.telemetry_id) == (None, False, False, None)
    assert welcome.welcome_needed(s)


def test_internal_keys_round_trip():
    save_internal({"telemetry": True, "telemetry_packages": True, "telemetry_id": ID,
                   "telemetry_at": "2026-10-10T12:00:00Z", "telemetry_start_day": "2026-10-10",
                   "welcome_version": 1, "welcome_at": "2026-10-10T12:00:00Z"})
    s = load_settings()
    assert s.telemetry and s.telemetry_packages and s.telemetry_id == ID
    assert s.telemetry_start_day == "2026-10-10" and not welcome.welcome_needed(s)


def test_explorer_keys_round_trip():
    assert (load_settings().explorer_dest, load_settings().explorer_recents) == (None, {})
    recents = {"R58T": ["/sdcard/DCIM/Camera", "/sdcard"], "79SS": ["/sdcard/Download"]}
    save_internal({"explorer_dest": "D:\\Klienci", "explorer_recents": recents})
    s = load_settings()
    assert (s.explorer_dest, s.explorer_recents) == ("D:\\Klienci", recents)
    assert list(s.explorer_recents) == ["R58T", "79SS"]  # kolejność telefonów zachowana


@pytest.mark.parametrize("recents", [
    {"S": ["/data/local/tmp"]}, {"S": ["/sdcard/a\nb"]}, {"S": "/sdcard/DCIM"},
    {"S": [f"/sdcard/{i}" for i in range(9)]}, {"S": [1]}, ["/sdcard/DCIM"], {"": ["/sdcard"]},
    {"a\nb": ["/sdcard"]}, {f"P{i}": [] for i in range(21)},
])
def test_explorer_recents_rejects_bad_values(recents):
    with pytest.raises(ValueError):
        save_internal({"explorer_recents": recents})


def test_old_flat_explorer_recent_is_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema": 1, "explorer_recent": ["/sdcard/Klient/Faktury"], "theme": "dark"}), "utf-8")
    s = load_settings(path)  # stary format (jedna lista dla wszystkich telefonów): bez błędu, pominięty
    assert s.explorer_recents == {} and s.theme == "dark" and not hasattr(s, "explorer_recent")
    s = save_internal({"explorer_recents": {"S1": ["/sdcard/DCIM"]}}, path)
    assert s.explorer_recents == {"S1": ["/sdcard/DCIM"]}


def test_ui_save_cannot_touch_internal_keys():
    for key in INTERNAL_KEYS:
        with pytest.raises(ValueError):
            save_settings({key: None})


@pytest.mark.parametrize("changes", [
    {"telemetry_id": "not-a-uuid"},
    {"telemetry_id": ID.upper()},
    {"telemetry": "yes"},
    {"welcome_version": 0},
    {"welcome_version": True},
    {"telemetry_start_day": "10.10.2026"},
    {"lang": "pl"},  # klucz z ekranu ustawień nie jest wewnętrzny
])
def test_save_internal_rejects_bad_values(changes):
    with pytest.raises(ValueError):
        save_internal(changes)


def test_invalid_value_in_file_falls_back_to_default(tmp_path):
    path = tmp_path / "AdMeNot" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"telemetry": "tak", "telemetry_id": "x"}', "utf-8")
    s = load_settings()
    assert s.telemetry is False and s.telemetry_id is None


def test_newer_settings_are_not_overwritten(tmp_path):
    path = tmp_path / "AdMeNot" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"schema": 99}', "utf-8")
    with pytest.raises(SettingsTooNew):
        save_internal({"telemetry": True})


def test_accept_risk_stores_version_and_time():
    s = welcome.accept_risk(datetime(2026, 10, 10, 12, 34, 56, tzinfo=UTC))
    assert s.welcome_version == welcome.WELCOME_VERSION
    assert s.welcome_at == "2026-10-10T12:34:56Z"
    assert not welcome.welcome_needed(s)


def test_older_accepted_version_shows_welcome_again(monkeypatch):
    save_internal({"welcome_version": 1})
    monkeypatch.setattr(welcome, "WELCOME_VERSION", 2)
    assert welcome.welcome_needed(load_settings())


def test_risk_lines_in_both_languages():
    assert len(welcome.RISK_LINES["pl"]) == len(welcome.RISK_LINES["en"]) >= 5


def test_donate_keys_default_and_validate():
    s = load_settings()
    assert (s.donate_count, s.donate_shown_at, s.donate_off) == (0, None, False)
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps({"donate_count": -1, "donate_shown_at": "jutro",
                                           "donate_off": "tak"}), "utf-8")
    s = load_settings()
    assert (s.donate_count, s.donate_shown_at, s.donate_off) == (0, None, False)
    save_internal({"donate_count": 3, "donate_shown_at": "2026-10-10", "donate_off": True})
    s = load_settings()
    assert (s.donate_count, s.donate_shown_at, s.donate_off) == (3, "2026-10-10", True)
    for bad in ({"donate_count": True}, {"donate_count": 1.5}, {"donate_shown_at": "10.10.2026"},
                {"donate_off": 1}):
        with pytest.raises(ValueError):
            save_internal(bad)


def test_transfer_roots_internal_only(tmp_path):
    with pytest.raises(ValueError):
        save_settings({"transfer_roots": []})
    assert save_internal({"transfer_roots": [str(tmp_path)]}).transfer_roots == [str(tmp_path)]
    with pytest.raises(ValueError):
        save_internal({"transfer_roots": ["relative/path"]})
