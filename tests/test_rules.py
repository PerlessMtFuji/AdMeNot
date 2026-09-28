import pytest

from demalware.engine.facts import AppFacts
from demalware.engine.parsers.appops import AppOpState
from demalware.engine.rules.conditions import check
from demalware.engine.rules.engine import load_default_ruleset, load_yaml_rules, parse_rules
from demalware.engine.rules.model import BASES, Finding
from demalware.engine.rules.python_rules import rule_name_mimic, rule_random_name
from demalware.engine.scoring import COMBOS


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
        "id": "T-1", "class": "behavior", "weight": 10, "category": "notif", "basis": "declared",
        "label": {"pl": "Dużo powiadomień", "en": "Many notifications"},
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


def test_parse_rules_requires_category_and_label():
    with pytest.raises(ValueError, match="category"):
        parse_rules([_rule(category="nope")])
    with pytest.raises(ValueError, match="category"):
        parse_rules([_rule(category="combo")])
    with pytest.raises(ValueError, match="label"):
        parse_rules([_rule(label={"pl": "Tylko PL"})])
    [rule] = parse_rules([_rule()])
    finding = rule.evaluate(AppFacts("com.a", notif_interruptions_24h=240))
    assert finding.category == "notif"
    assert finding.label_text("en") == "Many notifications"
    assert finding.label_text("de") == "Dużo powiadomień"


EXPECTED_CATEGORIES = {
    "DM-NOTIF-01": "notif", "DM-NOTIF-02": "notif", "DM-NOTIF-03": "notif",
    "DM-OVERLAY-01": "ads", "DM-FSI-01": "ads", "DM-BGACT-01": "ads", "DM-FSIPERM-01": "ads",
    "DM-ADSDK-01": "ads", "DM-ADSDK-02": "ads",
    "DM-ALARM-01": "background", "DM-PERM-01": "background", "DM-DYNDEX-01": "background",
    "DM-ADMIN-01": "removal", "DM-HOME-01": "removal", "DM-HOME-02": "removal",
    "DM-HIDDEN-01": "removal",
    "DM-A11Y-01": "data", "DM-NLS-01": "data", "DM-SMS-01": "data", "DM-BROWSER-01": "data",
    "DM-SRC-01": "origin", "DM-FRESH-01": "origin",
    "DM-LABEL-01": "disguise",
}


def test_default_rules_have_categories_and_labels():
    ruleset = load_default_ruleset()
    assert {r.id: r.category for r in ruleset.yaml_rules} == EXPECTED_CATEGORIES
    for r in ruleset.yaml_rules:
        assert r.label["pl"] and r.label["en"], r.id
    facts = AppFacts("com.systemupdate.xkqzvbnm", installer="com.android.chrome")
    found = [rule_name_mimic(facts), rule_random_name(facts)]
    assert [f.rule_id for f in found] == ["DM-NAME-01", "DM-NAME-02"]
    for f in found:
        assert f.category == "disguise" and f.label["pl"] and f.label["en"]


@pytest.mark.parametrize("bad", [
    {"class": "magic"},
    {"weight": -1},
    {"when": {"no_such_field": True}},
    {"evidence": ["no_such_field"]},
    {"text": {"simple": {"pl": "x"}, "expert": {"pl": "x", "en": "x"}}},
    {"basis": "guessed"},
])
def test_parse_rules_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_rules([_rule(**bad)])


def test_every_default_rule_has_a_basis():
    for rule in load_default_ruleset().yaml_rules:
        assert rule.basis in BASES, rule.id


def test_rule_without_basis_is_rejected():
    with pytest.raises(ValueError, match="basis"):
        load_yaml_rules("- id: X\n  class: context\n  weight: 1\n  category: origin\n"
                        "  label: {pl: a, en: a}\n  when: {is_system: true}\n"
                        "  text: {simple: {pl: a, en: a}, expert: {pl: a, en: a}}\n")


def test_fresh_install_is_information_not_points():
    facts = AppFacts("com.x", installer="com.android.vending", installed_days=2.0)
    finding = next(f for f in load_default_ruleset().evaluate(facts) if f.rule_id == "DM-FRESH-01")
    assert finding.weight == 0


def test_zero_weight_rule_is_allowed():
    rules = load_yaml_rules("- id: X\n  class: context\n  weight: 0\n  basis: declared\n"
                            "  category: origin\n  label: {pl: a, en: a}\n  when: {is_system: true}\n"
                            "  text: {simple: {pl: a, en: a}, expert: {pl: a, en: a}}\n")
    assert rules[0].weight == 0


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


def test_rule_name_mimic_ignores_play_store_apps():
    assert rule_name_mimic(AppFacts("com.avast.android.mobilesecurity", installer="com.android.vending")) is None


def test_rule_name_mimic_hits_sideloaded_system_like():
    assert rule_name_mimic(AppFacts("com.android.systemupdate", installer="com.android.chrome")) is not None


@pytest.mark.parametrize(("package", "hit"), [
    ("com.xkcdqwrtz.plmnbv", True),
    ("com.a8f3k2j9x1.app", True),
    ("com.mxtech.videoplayer.ad", False),
    ("com.zhiliaoapp.musically", False),
])
def test_rule_random_name(package, hit):
    assert (rule_random_name(AppFacts(package)) is not None) == hit


def test_rule_random_name_ignores_play_store_apps():
    assert rule_random_name(AppFacts("com.nordvpn.android", installer="com.android.vending")) is None


def _ids(facts):
    return {f.rule_id for f in load_default_ruleset().evaluate(facts)}


def test_ad_sdk_rules_thresholds():
    few = AppFacts("com.x", installer="com.android.vending", ad_sdks={"admob", "meta"})
    many = AppFacts("com.x", installer="com.android.vending",
                    ad_sdks={"admob", "meta", "applovin", "mintegral", "pangle"})
    four = AppFacts("com.x", installer="com.android.vending",
                    ad_sdks={"admob", "meta", "applovin", "mintegral"})
    assert "DM-ADSDK-01" in _ids(few) and "DM-ADSDK-02" not in _ids(few)
    assert "DM-ADSDK-01" in _ids(four) and "DM-ADSDK-02" not in _ids(four)
    assert "DM-ADSDK-02" in _ids(many) and "DM-ADSDK-01" not in _ids(many)


def test_apk_rules_do_not_fire_without_analysis():
    ids = _ids(AppFacts("com.x", installer="com.android.vending"))
    assert not ids & {"DM-ADSDK-01", "DM-ADSDK-02", "DM-DYNDEX-01", "DM-LABEL-01"}


def test_apk_rules_skip_system_apps():
    f = AppFacts("com.x", is_system=True, ad_sdks={"a", "b", "c", "d", "e"},
                 dynamic_code=True, label_padded=True, label="X")
    assert not _ids(f) & {"DM-ADSDK-02", "DM-DYNDEX-01", "DM-LABEL-01"}


def test_label_rule_evidence():
    f = AppFacts("com.x", installer="com.android.vending", label="IntelliClean", label_padded=True)
    finding = next(x for x in load_default_ruleset().evaluate(f) if x.rule_id == "DM-LABEL-01")
    assert "IntelliClean" in finding.text("pl")


def test_alarm_rule_uses_rate_per_hour():
    noisy = AppFacts("com.x", alarm_wakeups=600, alarm_window_h=77.8)
    quiet = AppFacts("com.x", alarm_wakeups=20, alarm_window_h=77.8)
    assert noisy.alarm_wakeups_per_hour > 6 and "DM-ALARM-01" in _ids(noisy)
    assert "DM-ALARM-01" not in _ids(quiet)
    assert AppFacts("com.x").alarm_wakeups_per_hour is None


def test_unlock_rule_needs_three_events_and_skips_home():
    twice = AppFacts("com.x", unlock_launches_24h=2)
    three = AppFacts("com.x", unlock_launches_24h=3)
    home = AppFacts("com.x", unlock_launches_24h=5, is_home_holder=True)
    assert "DM-BGACT-01" not in _ids(twice)
    assert "DM-BGACT-01" in _ids(three)
    assert "DM-BGACT-01" not in _ids(home)
    finding = next(f for f in load_default_ruleset().evaluate(three) if f.rule_id == "DM-BGACT-01")
    assert finding.weight == 12 and "sama" not in finding.text("pl").lower()


def test_role_rules():
    assert "DM-SMS-01" in _ids(AppFacts("com.x", is_sms_holder=True))
    assert "DM-BROWSER-01" in _ids(AppFacts("com.x", is_browser_holder=True))
    assert not _ids(AppFacts("com.x", is_system=True, is_sms_holder=True,
                             is_browser_holder=True)) & {"DM-SMS-01", "DM-BROWSER-01"}


def test_plan4_rule_texts_format_with_real_evidence():
    samples = [
        AppFacts("com.x", ad_sdks={"admob", "meta"}, dynamic_code=True, label="X",
                 label_padded=True, alarm_wakeups=600, alarm_window_h=10.0,
                 unlock_launches_24h=3, is_sms_holder=True, is_browser_holder=True),
        AppFacts("com.y", ad_sdks={"admob", "meta", "applovin", "mintegral", "pangle"}),
    ]
    fired = set()
    for facts in samples:
        for finding in load_default_ruleset().evaluate(facts):
            fired.add(finding.rule_id)
            for lang in ("pl", "en"):
                for expert in (False, True):
                    assert "{" not in finding.text(lang, expert), finding.rule_id
    assert {"DM-ADSDK-01", "DM-ADSDK-02", "DM-DYNDEX-01", "DM-LABEL-01", "DM-ALARM-01",
            "DM-BGACT-01", "DM-SMS-01", "DM-BROWSER-01"} <= fired


NEUTRAL_FORBIDDEN = ("żeby", "ukrywa", "blokuje", "nachaln", "typowe", "aplikacji-śmieci",
                     "to hide", "to make", "blocks", "aggressive", "typical")


def test_simple_texts_describe_facts_not_intent():
    texts = [(r.id, t) for r in load_default_ruleset().yaml_rules
             for t in (*r.text_simple.values(), *r.label.values())]
    for combo in COMBOS:
        texts += [(combo.rule_id, t) for t in (*combo.text_simple.values(), *combo.label.values())]
    for facts in (AppFacts("com.clean.booster.xq7zkr"),):
        for finding in load_default_ruleset().evaluate(facts):
            texts += [(finding.rule_id, finding.text(lang)) for lang in ("pl", "en")]
    for rule_id, text in texts:
        assert not any(word in text.lower() for word in NEUTRAL_FORBIDDEN), (rule_id, text)


def test_notification_burst_rule():
    burst = AppFacts("com.x", notif_interruptions_24h=40, notif_peak_1h=40)
    flood = AppFacts("com.x", notif_interruptions_24h=600, notif_peak_1h=60)
    assert "DM-NOTIF-03" in _ids(burst)
    assert "DM-NOTIF-03" not in _ids(flood) and "DM-NOTIF-02" in _ids(flood)


def test_roles_are_context_signals():
    rules = {r.id: r for r in load_default_ruleset().yaml_rules}
    assert {rules[i].rule_class for i in ("DM-HOME-01", "DM-HOME-02", "DM-SMS-01",
                                         "DM-BROWSER-01")} == {"context"}
