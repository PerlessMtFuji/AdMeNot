import pytest

from demalware.engine.facts import AppFacts
from demalware.engine.parsers.appops import AppOpState
from demalware.engine.rules.engine import load_default_ruleset
from demalware.engine.rules.model import Finding
from demalware.engine.scoring import confidence_for, score_app, verdict_for


def F(rule_id, cls, weight):
    return Finding(rule_id, cls, weight, {}, {"pl": rule_id, "en": rule_id}, {"pl": "", "en": ""})


def FB(rule_id, cls, weight, basis, category="ads"):
    return Finding(rule_id, cls, weight, {}, {"pl": rule_id, "en": rule_id}, {"pl": "", "en": ""},
                   category=category, basis=basis)


@pytest.mark.parametrize(("score", "verdict"), [
    (0, "safe"), (24, "safe"), (25, "review"), (49, "review"),
    (50, "suspicious"), (74, "suspicious"), (75, "malicious"), (100, "malicious"),
])
def test_verdict_thresholds(score, verdict):
    assert verdict_for(score) == verdict


def test_confidence_levels():
    declared = [FB("A", "context", 8, "declared")]
    one_obs = declared + [FB("B", "behavior", 25, "observed", "ads")]
    two_obs = one_obs + [FB("C", "behavior", 10, "observed", "background")]
    assert confidence_for(declared, incomplete=False) == "low"
    assert confidence_for(one_obs, incomplete=False) == "medium"
    assert confidence_for(two_obs, incomplete=False) == "high"
    assert confidence_for(two_obs, incomplete=True) == "medium"
    assert confidence_for([FB("I", "ioc", 80, "confirmed", "origin")], incomplete=True) == "high"


def test_high_score_without_strong_evidence_is_only_suspicious():
    findings = [FB("DM-ADMIN-01", "position", 25, "granted", "removal"),
                FB("DM-A11Y-01", "position", 20, "granted", "data"),
                FB("DM-SRC-01", "context", 20, "declared", "origin"),
                FB("DM-ADSDK-02", "apk", 30, "declared", "ads")]
    result = score_app(AppFacts("com.x"), findings, trusted=False, low_behavior_data=False)
    assert result.score >= 75
    assert (result.verdict, result.confidence) == ("suspicious", "low")


def test_verdict_thresholds_with_confidence():
    assert verdict_for(80, "high") == "malicious"
    assert verdict_for(80, "medium") == "suspicious"
    assert verdict_for(30, "low") == "review"


def test_class_caps_limit_weak_signals():
    findings = [F(f"C{i}", "context", 8) for i in range(10)]
    result = score_app(AppFacts("com.x"), findings, trusted=False, low_behavior_data=False)
    assert result.score == 20
    assert result.verdict == "safe"


def test_only_the_strongest_combo_counts():
    findings = [FB("DM-HIDDEN-01", "position", 10, "declared", "removal"),
                FB("DM-OVERLAY-01", "behavior", 20, "observed", "ads"),
                FB("DM-SRC-01", "context", 8, "declared", "origin"),
                FB("DM-ADMIN-01", "position", 25, "granted", "removal")]
    result = score_app(AppFacts("com.x"), findings, trusted=False, low_behavior_data=False)
    combos = [f.rule_id for f in result.findings if f.rule_class == "combo"]
    assert combos == ["DM-COMBO-01"]
    assert result.score == 20 + 35 + 8 + 20


def test_play_admin_with_overlay_is_review_not_suspicious():
    """Audyt: administrator + overlay dawały 65 pkt nawet przy Play i widocznej ikonie."""
    facts = AppFacts("com.x.remote", installer="com.android.vending", has_launcher_icon=True,
                     is_device_admin=True, appops={"SYSTEM_ALERT_WINDOW": AppOpState("allow", 60.0)},
                     installed_days=200.0)
    result = score_app(facts, load_default_ruleset().evaluate(facts), trusted=False,
                       low_behavior_data=False)
    assert (result.score, result.verdict) == (45, "review")


def test_trusted_lowers_score():
    result = score_app(AppFacts("com.x"), [F("DM-NLS-01", "position", 10)],
                       trusted=True, low_behavior_data=True)
    assert (result.score, result.verdict, result.incomplete) == (0, "safe", True)


def test_gaps_make_result_incomplete_even_when_trusted():
    facts = AppFacts("com.x", gaps={"appops"})
    assert score_app(facts, [], trusted=True, low_behavior_data=False).incomplete is True
    assert score_app(AppFacts("com.y"), [], trusted=True, low_behavior_data=False).incomplete is False


def test_system_app_without_behavior_is_capped_safe():
    result = score_app(AppFacts("com.sys", is_system=True),
                       [F("DM-HOME-01", "position", 20), F("DM-A11Y-01", "position", 20)],
                       trusted=False, low_behavior_data=False)
    assert result.score == 24 and result.verdict == "safe"


def test_confirmed_indicator_is_not_capped_for_system_apps():
    ioc = FB("DM-IOC-01", "ioc", 80, "confirmed", "origin")
    result = score_app(AppFacts("com.sys", is_system=True), [ioc], trusted=False,
                       low_behavior_data=False)
    assert result.score == 80 and result.verdict == "malicious"


def test_low_behavior_data_marks_untrusted_incomplete():
    result = score_app(AppFacts("com.x"), [], trusted=False, low_behavior_data=True)
    assert result.incomplete is True


def test_trusted_app_is_scored_on_behavior_only():
    findings = [F("DM-ADMIN-01", "position", 25), F("DM-A11Y-01", "position", 20),
                F("DM-SRC-01", "context", 8), F("DM-NOTIF-02", "behavior", 25),
                F("DM-OVERLAY-01", "behavior", 25), F("DM-FSI-01", "behavior", 15)]
    result = score_app(AppFacts("com.x"), findings, trusted=True, low_behavior_data=False)
    assert result.score == 60  # zachowanie liczy się w pełni (limit klasy 60), tożsamość nie
    assert {f.rule_id for f in result.findings} >= {"DM-ADMIN-01", "DM-SRC-01"}  # nadal widoczne


def test_trusted_app_with_only_identity_signals_is_safe():
    findings = [F("DM-NLS-01", "position", 10), F("DM-SRC-01", "context", 8)]
    result = score_app(AppFacts("com.x"), findings, trusted=True, low_behavior_data=False)
    assert (result.score, result.verdict) == (0, "safe")


def test_combo_findings_carry_category_and_label():
    from demalware.engine.scoring import COMBOS, _combo_findings

    def make(rule_id, cls, weight):
        return Finding(rule_id, cls, weight, {}, {"pl": rule_id, "en": rule_id}, {"pl": "", "en": ""})

    (combo,) = _combo_findings([make("DM-ADMIN-01", "position", 25),
                                make("DM-SRC-01", "context", 8),
                                make("DM-OVERLAY-01", "behavior", 25)])
    assert combo.rule_id == "DM-COMBO-02" and combo.category == "combo"
    assert combo.label_text("pl") == "Administrator spoza Play + wyświetlanie treści"
    assert all(c.label["pl"] and c.label["en"] for c in COMBOS)


def test_ad_sdks_and_unlock_appearances_are_review_not_suspicious():
    """Audyt: 5 SDK + 2 otwarcia po odblokowaniu dawały 60 pkt i domyślne „Wyłącz”."""
    facts = AppFacts("com.x", installer="com.android.vending", has_launcher_icon=True,
                     installed_days=100.0, unlock_launches_24h=3,
                     ad_sdks={"admob", "meta", "applovin", "mintegral", "pangle"})
    result = score_app(facts, load_default_ruleset().evaluate(facts), trusted=False,
                       low_behavior_data=False)
    assert result.verdict == "review" and result.score == 37


def test_combo_03_many_ad_networks_plus_behavior():
    facts = AppFacts("com.x", installer="com.android.vending")
    alone = score_app(facts, [F("DM-ADSDK-02", "apk", 20)], trusted=False,
                      low_behavior_data=False)
    assert alone.score == 20 and "DM-COMBO-03" not in {f.rule_id for f in alone.findings}
    both = score_app(facts, [F("DM-ADSDK-02", "apk", 20), F("DM-NOTIF-01", "behavior", 15)],
                     trusted=False, low_behavior_data=False)
    assert both.score == 50 and "DM-COMBO-03" in {f.rule_id for f in both.findings}


def test_static_code_path_is_not_an_observation():
    static = Finding("DM-CODE-BOOTUI-01", "apk", 5, {}, {}, {}, category="background", basis="static")
    assert confidence_for([static], incomplete=False) == "low"
