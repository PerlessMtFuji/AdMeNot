from datetime import date

import pytest
import yaml

from admenot.engine.apk.iocs import load_default_iocs, parse_iocs
from admenot.engine.facts import AppFacts
from admenot.engine.rules import python_rules
from admenot.engine.scoring import score_app

H = "ab" * 32
S = "cd" * 32
YAML = f"""
version: 3
entries:
  - {{kind: sha256, value: {H}, family: Test.Adware, source: https://example.org/r/1, added: 2026-09-27}}
  - {{kind: signer, value: {S}, family: Test.Signer, source: https://example.org/r/2, added: 2026-09-27}}
"""


def test_parse_and_match():
    iocs = parse_iocs(YAML)
    assert iocs.version == 3 and iocs.entries[0].added == date(2026, 9, 27)
    assert [i.family for i in iocs.match(AppFacts("com.x", apk_sha256=(H,)))] == ["Test.Adware"]
    assert [i.family for i in iocs.match(AppFacts("com.x", cert_sha256=(S,)))] == ["Test.Signer"]
    assert iocs.match(AppFacts("com.x")) == []


@pytest.mark.parametrize("entry", [
    f"{{kind: package, value: {H}, family: F, source: https://x, added: 2026-09-27}}",
    "{kind: sha256, value: XYZ, family: F, source: https://x, added: 2026-09-27}",
    f"{{kind: sha256, value: {H}, family: F, source: '', added: 2026-09-27}}",
    f"{{kind: sha256, value: {H}, family: F, source: https://x}}",
])
def test_entries_without_provenance_or_valid_value_are_rejected(entry):
    with pytest.raises(ValueError):
        parse_iocs(f"version: 1\nentries:\n  - {entry}\n")


def test_default_database_loads_and_is_versioned():
    assert load_default_iocs().version >= 1


def test_ioc_rule_makes_confirmed_malicious(monkeypatch):
    monkeypatch.setattr(python_rules, "load_default_iocs", lambda: parse_iocs(YAML))
    facts = AppFacts("com.x", apk_sha256=(H,))
    finding = python_rules.rule_ioc(facts)
    assert (finding.rule_id, finding.basis, finding.rule_class) == ("DM-IOC-01", "confirmed", "ioc")
    assert "Test.Adware" in finding.text("pl")
    result = score_app(facts, [finding], trusted=False, low_behavior_data=True)
    assert result.verdict == "malicious" and result.confidence == "high"


def test_ioc_finding_counts_for_trusted_apps_and_bypasses_system_cap(monkeypatch):
    """Controller ruling (Task 6 review): trusted apps still count class 'ioc' findings —
    no combo bonuses, but a confirmed IOC match must not be discarded just because the
    app is on the trusted list, and must not be squashed by the system no-behavior cap."""
    monkeypatch.setattr(python_rules, "load_default_iocs", lambda: parse_iocs(YAML))
    facts = AppFacts("com.x", is_system=True, apk_sha256=(H,))
    finding = python_rules.rule_ioc(facts)
    result = score_app(facts, [finding], trusted=True, low_behavior_data=False)
    assert result.score == 80
    assert (result.verdict, result.confidence) == ("malicious", "high")


def _iocs(entries):
    return parse_iocs(yaml.safe_dump({"version": 1, "entries": entries}))


SIGNER = {"kind": "signer", "value": "a" * 64, "family": "Fam", "source": "https://ex.org/r",
          "added": date(2026, 10, 1)}


def test_shared_signer_match_is_weaker_than_a_sample_hash(monkeypatch):
    monkeypatch.setattr(python_rules, "load_default_iocs", lambda: _iocs([SIGNER]))
    f = python_rules.rule_ioc(AppFacts("com.x", cert_sha256=("a" * 64,)))
    assert (f.rule_id, f.weight, f.basis) == ("DM-IOC-02", 30, "declared")
    assert "potwierdzon" not in f.text("pl").lower() + f.label_text("pl").lower()


def test_exclusive_signer_is_confirmed(monkeypatch):
    monkeypatch.setattr(python_rules, "load_default_iocs", lambda: _iocs([{**SIGNER, "exclusive": True}]))
    f = python_rules.rule_ioc(AppFacts("com.x", cert_sha256=("a" * 64,)))
    assert (f.rule_id, f.weight, f.basis) == ("DM-IOC-02", 60, "confirmed")


def test_exclusive_only_for_signers():
    with pytest.raises(ValueError, match="exclusive"):
        _iocs([{**SIGNER, "kind": "sha256", "exclusive": True}])


def test_shared_signer_does_not_override_the_trust_list(monkeypatch):
    # Zaufanie obala tylko potwierdzony wskaźnik; wspólny podpisujący nim nie jest.
    monkeypatch.setattr(python_rules, "load_default_iocs", lambda: _iocs([SIGNER]))
    facts = AppFacts("com.x", cert_sha256=("a" * 64,))
    result = score_app(facts, [python_rules.rule_ioc(facts)], trusted=True, low_behavior_data=False)
    assert result.score == 0
