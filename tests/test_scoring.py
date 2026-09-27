import pytest

from demalware.engine.allowlist.trust import load_default_trust_list, parse_trust_list
from demalware.engine.facts import AppFacts
from demalware.engine.rules.model import Finding
from demalware.engine.scoring import score_app, verdict_for


def F(rule_id, cls, weight):
    return Finding(rule_id, cls, weight, {}, {"pl": rule_id, "en": rule_id}, {"pl": "", "en": ""})


@pytest.mark.parametrize(("score", "verdict"), [
    (0, "safe"), (24, "safe"), (25, "review"), (49, "review"),
    (50, "suspicious"), (74, "suspicious"), (75, "malicious"), (100, "malicious"),
])
def test_verdict_thresholds(score, verdict):
    assert verdict_for(score) == verdict


def test_class_caps_limit_weak_signals():
    findings = [F(f"C{i}", "context", 8) for i in range(10)]
    result = score_app(AppFacts("com.x"), findings, trusted=False, low_behavior_data=False)
    assert result.score == 20
    assert result.verdict == "safe"


def test_combos_add_bonus_findings():
    findings = [F("DM-HIDDEN-01", "position", 15), F("DM-OVERLAY-01", "behavior", 25),
                F("DM-SRC-01", "context", 8), F("DM-ADMIN-01", "position", 25)]
    result = score_app(AppFacts("com.x"), findings, trusted=False, low_behavior_data=False)
    ids = [f.rule_id for f in result.findings]
    assert "DM-COMBO-01" in ids and "DM-COMBO-02" in ids
    # behavior 25 + position min(40, 40) + context 8 + combo 20 + 15 = 108 → 100
    assert result.score == 100
    assert result.verdict == "malicious"


def test_trusted_lowers_score():
    result = score_app(AppFacts("com.x"), [F("DM-NLS-01", "position", 10)],
                       trusted=True, low_behavior_data=True)
    assert (result.score, result.verdict, result.incomplete) == (0, "safe", False)


def test_system_app_without_behavior_is_capped_safe():
    result = score_app(AppFacts("com.sys", is_system=True),
                       [F("DM-HOME-01", "position", 20), F("DM-A11Y-01", "position", 20)],
                       trusted=False, low_behavior_data=False)
    assert result.score == 24 and result.verdict == "safe"


def test_low_behavior_data_marks_untrusted_incomplete():
    result = score_app(AppFacts("com.x"), [], trusted=False, low_behavior_data=True)
    assert result.incomplete is True


def test_trust_list_prefixes_and_source_requirement():
    trust = parse_trust_list("trusted:\n  - com.whatsapp\n  - com.google.android.*\n")
    play = "com.android.vending"
    assert trust.is_trusted(AppFacts("com.whatsapp", installer=play))
    assert trust.is_trusted(AppFacts("com.google.android.gm", is_system=True))
    # sideloadowana aplikacja podszywająca się pod zaufaną nazwę — bez zaufania
    assert not trust.is_trusted(AppFacts("com.whatsapp", installer="com.android.chrome"))
    assert not trust.is_trusted(AppFacts("com.google.androidx.evil", installer=play))


def test_default_trust_list_loads():
    trust = load_default_trust_list()
    assert trust.matches("com.whatsapp") and trust.matches("com.google.android.youtube")


def test_trusted_app_never_malicious():
    findings = [F("DM-ADMIN-01", "position", 25), F("DM-A11Y-01", "position", 20),
                F("DM-OVERLAY-01", "behavior", 25), F("DM-NOTIF-02", "behavior", 25),
                F("DM-FSI-01", "behavior", 15)]
    result = score_app(AppFacts("com.x"), findings, trusted=True, low_behavior_data=False)
    assert result.score == 60 and result.verdict == "suspicious"


def test_combo_findings_carry_category_and_label():
    from demalware.engine.scoring import COMBOS, _combo_findings

    def make(rule_id, cls, weight):
        return Finding(rule_id, cls, weight, {}, {"pl": rule_id, "en": rule_id}, {"pl": "", "en": ""})

    (combo,) = _combo_findings([make("DM-ADMIN-01", "position", 25),
                                make("DM-OVERLAY-01", "behavior", 25)])
    assert combo.rule_id == "DM-COMBO-02" and combo.category == "combo"
    assert combo.label_text("pl") == "Blokuje usunięcie i nachalnie wyświetla treści"
    assert all(c.label["pl"] and c.label["en"] for c in COMBOS)


def test_combo_03_many_ad_networks_plus_behavior():
    facts = AppFacts("com.x", installer="com.android.vending")
    alone = score_app(facts, [F("DM-ADSDK-02", "apk", 20)], trusted=False,
                      low_behavior_data=False)
    assert alone.score == 20 and "DM-COMBO-03" not in {f.rule_id for f in alone.findings}
    both = score_app(facts, [F("DM-ADSDK-02", "apk", 20), F("DM-NOTIF-01", "behavior", 15)],
                     trusted=False, low_behavior_data=False)
    assert both.score == 50 and "DM-COMBO-03" in {f.rule_id for f in both.findings}
