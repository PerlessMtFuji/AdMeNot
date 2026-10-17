"""Zamrożone scenariusze legalnych funkcji i adware (ocena 2026-10-16): fakty syntetyczne, reguły,
punktacja i wybór domyślnego działania prawdziwe.

Wiersz tabeli zmienia się tylko razem ze świadomą zmianą arytmetyki werdyktu, żeby każda różnica
była widoczna w diffie (plan: docs/superpowers/notes/2026-10-16-apk-analysis-plan.md).
"""

from __future__ import annotations

import pytest

from admenot.engine.actions.planner import default_level
from admenot.engine.allowlist.trust import load_default_trust_list
from admenot.engine.facts import AppFacts
from admenot.engine.parsers.appops import AppOpState
from admenot.engine.rules.engine import load_default_ruleset
from admenot.engine.scoring import score_app

RULES = load_default_ruleset()
TRUST = load_default_trust_list()
SDK5 = {"admob", "applovin", "ironsource", "mintegral", "pangle"}


def _overlay() -> dict[str, AppOpState]:
    return {"SYSTEM_ALERT_WINDOW": AppOpState("allow", 600.0)}


def _app(package: str, **kw) -> AppFacts:
    facts = AppFacts(package, installer="com.android.vending", has_launcher_icon=True,
                     notif_interruptions_24h=0, unlock_launches_24h=0, notif_peak_1h=0,
                     alarm_wakeups=0, alarm_window_h=24.0, installed_days=200.0)
    for key, value in kw.items():
        setattr(facts, key, value)
    return facts


SCENARIOS = {
    "A komunikator z Play w trakcie połączenia":
        lambda: _app("com.whatsapp", notif_interruptions_24h=24 * 21, appops=_overlay(),
                     notif_fsi=True),
    "A2 komunikator bez połączenia":
        lambda: _app("com.whatsapp", notif_interruptions_24h=24 * 21, appops=_overlay()),
    "B aplikacja pogodowa: 6 SDK, 10 powiadomień/h, widżet nad aplikacjami":
        lambda: _app("com.example.weather", notif_interruptions_24h=24 * 10, appops=_overlay(),
                     ad_sdks=SDK5 | {"unity"}, dynamic_code=True, obfuscation_ratio=0.3),
    "C gra: 5 SDK i tylko wybudzenia":
        lambda: _app("com.example.game", alarm_wakeups=24 * 7, ad_sdks=set(SDK5),
                     dynamic_code=True),
    "D Tasker: administrator, dostępność, powiadomienia, okna, start z telefonem":
        lambda: _app("net.dinglisch.android.taskerm", is_device_admin=True,
                     accessibility_enabled=True, notification_listener=True, appops=_overlay(),
                     has_boot_receiver=True,
                     requested_permissions={"android.permission.QUERY_ALL_PACKAGES"}),
    "E adware z Play: reklama z tła, 2 starty po odblokowaniu":
        lambda: _app("com.example.cleaner", ad_sdks={"admob", "applovin", "pangle"},
                     dynamic_code=True, unlock_launches_24h=2),
    "F to samo, 3 starty po odblokowaniu":
        lambda: _app("com.example.cleaner", ad_sdks={"admob", "applovin", "pangle"},
                     dynamic_code=True, unlock_launches_24h=3),
    "G aplikacja producenta z 5 SDK, bez zachowania":
        lambda: _app("com.oem.preinstall", is_system=True, installer=None, ad_sdks=set(SDK5)),
    "H launcher spoza Play: ekran główny, okna, 5 SDK":
        lambda: _app("com.example.launcher", installer="com.huawei.appmarket",
                     is_home_holder=True, is_home_candidate=True, appops=_overlay(),
                     ad_sdks=set(SDK5)),
    "I komunikator z 5 SDK":
        lambda: _app("com.example.chat", notif_interruptions_24h=24 * 21, appops=_overlay(),
                     ad_sdks=set(SDK5)),
    "J automatyka spoza Play: administrator, dostępność, okna, 7 wybudzeń/h":
        lambda: _app("com.example.macro", installer="com.android.packageinstaller",
                     is_device_admin=True, accessibility_enabled=True, appops=_overlay(),
                     alarm_wakeups=24 * 7),
}

# (wynik, werdykt, pewność, domyślne działanie)
EXPECTED: dict[str, tuple[int, str, str, str | None]] = {
    "A komunikator z Play w trakcie połączenia": (45, "review", "high", None),
    "A2 komunikator bez połączenia": (45, "review", "high", None),
    "B aplikacja pogodowa: 6 SDK, 10 powiadomień/h, widżet nad aplikacjami":
        (65, "suspicious", "high", "disable"),
    "C gra: 5 SDK i tylko wybudzenia": (38, "review", "medium", None),
    "D Tasker: administrator, dostępność, powiadomienia, okna, start z telefonem":
        (64, "suspicious", "medium", "disable"),
    "E adware z Play: reklama z tła, 2 starty po odblokowaniu": (6, "safe", "low", None),
    "F to samo, 3 starty po odblokowaniu": (18, "safe", "medium", None),
    "G aplikacja producenta z 5 SDK, bez zachowania": (0, "safe", "low", None),
    "H launcher spoza Play: ekran główny, okna, 5 SDK": (66, "suspicious", "medium", "disable"),
    "I komunikator z 5 SDK": (75, "malicious", "high", "disable"),
    "J automatyka spoza Play: administrator, dostępność, okna, 7 wybudzeń/h":
        (93, "suspicious", "medium", "disable"),
}


def _score(name: str):
    facts = SCENARIOS[name]()
    return score_app(facts, RULES.evaluate(facts), TRUST.is_trusted(facts), low_behavior_data=False)


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenario(name):
    r = _score(name)
    assert (r.score, r.verdict, r.confidence, default_level(r)) == EXPECTED[name]


@pytest.mark.xfail(strict=True, reason="Etap 1: reklama z tła nie trafia jeszcze do oceny")
def test_background_ad_reaches_review():
    assert _score("F to samo, 3 starty po odblokowaniu").verdict != "safe"
