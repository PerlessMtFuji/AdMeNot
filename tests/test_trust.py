import pytest

from demalware.engine.allowlist.trust import (
    load_default_trust_list,
    load_protected_list,
    parse_trust_list,
)
from demalware.engine.facts import AppFacts

GOOD = "a1" * 32
OLD = "b2" * 32
EVIL = "ee" * 32
PLAY = "com.android.vending"
YAML = f"""
trusted:
  - package: com.whatsapp
    signers: [{GOOD}, {OLD}]
  - package: com.google.android.*
    signers: [{GOOD}]
  - package: com.oem.only
    signers: []
"""


def test_user_app_needs_matching_signer_not_just_name_and_installer():
    trust = parse_trust_list(YAML)
    assert trust.is_trusted(AppFacts("com.whatsapp", installer=PLAY, cert_sha256=(GOOD,)))
    assert trust.is_trusted(AppFacts("com.whatsapp", installer="x", cert_sha256=(OLD,)))  # rotacja
    assert not trust.is_trusted(AppFacts("com.whatsapp", installer=PLAY, cert_sha256=(EVIL,)))
    assert not trust.is_trusted(AppFacts("com.whatsapp", installer=PLAY))  # brak analizy APK
    assert not trust.is_trusted(AppFacts("com.oem.only", installer=PLAY, cert_sha256=(GOOD,)))


def test_failed_or_unverified_apk_analysis_never_grants_trust():
    trust = parse_trust_list(YAML)
    facts = AppFacts("com.whatsapp", installer=PLAY, cert_sha256=(GOOD,), gaps={"apk"})
    assert not trust.is_trusted(facts)


def test_system_apps_are_trusted_by_name():
    trust = parse_trust_list(YAML)
    assert trust.is_trusted(AppFacts("com.oem.only", is_system=True))
    assert trust.is_trusted(AppFacts("com.google.android.gms", is_system=True))
    assert not trust.is_trusted(AppFacts("com.google.androidx.evil", is_system=True))


def test_exact_entry_wins_over_prefix():
    trust = parse_trust_list(YAML + f"  - package: com.google.android.apps.x\n    signers: [{OLD}]\n")
    assert trust.entry_for("com.google.android.apps.x").signers == frozenset({OLD})


@pytest.mark.parametrize("bad", [
    "trusted:\n  - com.whatsapp\n",
    "trusted:\n  - package: com.whatsapp\n    signers: [XYZ]\n",
    "trusted:\n  - package: com.whatsapp\n",
])
def test_invalid_entries_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_trust_list(bad)


def test_default_lists_load():
    assert load_default_trust_list().matches("com.whatsapp")
    assert load_protected_list().matches("com.android.systemui")
