import pytest

from demalware.engine.facts import AppFacts
from demalware.engine.parsers.appops import AppOpState
from demalware.engine.rules.conditions import check
from demalware.engine.rules.engine import load_default_ruleset, parse_rules
from demalware.engine.rules.model import Finding
from demalware.engine.rules.python_rules import rule_name_mimic, rule_random_name


def test_check_operators():
    assert check(5, {"gte": 5, "lt": 6})
    assert not check(None, {"gte": 1})
    assert check(None, None)
    assert not check(None, False)
    assert check({"a", "b"}, {"contains": "a"})
    assert check("x", {"not_in": ["y"]})
    with pytest.raises(ValueError):
        check(1, {"between": [0, 2]})


def _rule(**over):
    rule = {
        "id": "T-1", "class": "behavior", "weight": 10,
        "when": {"notif_per_hour_24h": {"gte": 8}},
        "evidence": ["notif_per_hour_24h"],
        "text": {"simple": {"pl": "{notif_per_hour_24h:.0f}/h", "en": "{notif_per_hour_24h:.0f}/h"},
                 "expert": {"pl": "x", "en": "x"}},
    }
    rule.update(over)
    return rule


def test_parse_rules_and_evaluate():
    [rule] = parse_rules([_rule()])
    finding = rule.evaluate(AppFacts("com.a", notif_interruptions_24h=240))
    assert finding.rule_id == "T-1" and finding.weight == 10
    assert finding.text("pl") == "10/h"
    assert rule.evaluate(AppFacts("com.a", notif_interruptions_24h=24)) is None


@pytest.mark.parametrize("bad", [
    {"class": "magic"},
    {"weight": 0},
    {"when": {"no_such_field": True}},
    {"evidence": ["no_such_field"]},
    {"text": {"simple": {"pl": "x"}, "expert": {"pl": "x", "en": "x"}}},
])
def test_parse_rules_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_rules([_rule(**bad)])


def test_parse_rules_rejects_duplicate_ids():
    with pytest.raises(ValueError):
        parse_rules([_rule(), _rule()])


def test_finding_text_falls_back_to_pl_and_template_on_format_error():
    f = Finding("X", "context", 1, {}, {"pl": "brak {missing}"}, {"pl": "e"})
    assert f.text("en") == "brak {missing}"


def test_default_ruleset_flags_adware_profile():
    facts = AppFacts(
        "com.clean.pro.boost", installer="com.android.chrome", is_system=False,
        has_launcher_icon=False, is_device_admin=True, notif_fsi=True,
        appops={"SYSTEM_ALERT_WINDOW": AppOpState("allow", 250.0)},
        notif_interruptions_24h=600, installed_days=3.0, has_boot_receiver=True,
        requested_permissions={"android.permission.QUERY_ALL_PACKAGES",
                               "android.permission.USE_FULL_SCREEN_INTENT"},
    )
    ids = {f.rule_id for f in load_default_ruleset().evaluate(facts)}
    assert ids == {"DM-NOTIF-02", "DM-OVERLAY-01", "DM-FSI-01", "DM-ADMIN-01", "DM-HIDDEN-01",
                   "DM-SRC-01", "DM-FRESH-01", "DM-PERM-01", "DM-FSIPERM-01", "DM-NAME-01"}


def test_default_ruleset_quiet_for_play_app():
    facts = AppFacts("com.whatsapp", installer="com.android.vending", has_launcher_icon=True,
                     notif_interruptions_24h=30, installed_days=400.0)
    assert load_default_ruleset().evaluate(facts) == []


def test_all_default_rule_texts_format_with_real_evidence():
    facts = AppFacts("com.x", notif_interruptions_24h=500,
                     appops={"SYSTEM_ALERT_WINDOW": AppOpState("allow", 10.0)},
                     installed_days=1.0)
    for finding in load_default_ruleset().evaluate(facts):
        for lang in ("pl", "en"):
            for expert in (False, True):
                assert "{" not in finding.text(lang, expert)


@pytest.mark.parametrize(("package", "hit"), [
    ("com.systemupdate.service", True),
    ("com.fast.cleaner.booster", True),
    ("com.whatsapp", False),
])
def test_rule_name_mimic(package, hit):
    assert (rule_name_mimic(AppFacts(package)) is not None) == hit


def test_rule_name_mimic_ignores_system_apps():
    assert rule_name_mimic(AppFacts("com.android.systemupdate", is_system=True)) is None


@pytest.mark.parametrize(("package", "hit"), [
    ("com.xkcdqwrtz.plmnbv", True),
    ("com.a8f3k2j9x1.app", True),
    ("com.mxtech.videoplayer.ad", False),
    ("com.zhiliaoapp.musically", False),
])
def test_rule_random_name(package, hit):
    assert (rule_random_name(AppFacts(package)) is not None) == hit
