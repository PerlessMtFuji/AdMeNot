from demalware.engine.apk.callgraph import CodePath
from demalware.engine.apk.components import A11yConfig, Component
from demalware.engine.evidence import ladders
from demalware.engine.facts import AppFacts
from demalware.engine.parsers.appops import AppOpState


def _by_cap(facts):
    return {ld.capability: ld.levels for ld in ladders(facts)}


def test_overlay_ladder_separates_request_grant_and_use():
    facts = AppFacts("com.x", requested_permissions={"android.permission.SYSTEM_ALERT_WINDOW"},
                     appops={"SYSTEM_ALERT_WINDOW": AppOpState(mode="allow", last_access_s=60.0)})
    assert _by_cap(facts)["overlay"] == {"declared": True, "code": None, "granted": True, "observed": True}


def test_unknown_stays_unknown():
    facts = AppFacts("com.x", requested_permissions={"android.permission.SYSTEM_ALERT_WINDOW"})
    levels = _by_cap(facts)["overlay"]
    assert levels["granted"] is None and levels["observed"] is None  # brak appops ≠ „nie przyznano”


def test_accessibility_from_manifest_component():
    comp = Component("service", "com.x.A11y", False, "android.permission.BIND_ACCESSIBILITY_SERVICE",
                     (), A11yConfig(True, True, None))
    facts = AppFacts("com.x", apk_components=(comp,), accessibility_enabled=False)
    assert _by_cap(facts)["accessibility"]["declared"] is True
    assert _by_cap(facts)["accessibility"]["granted"] is False


def test_accessibility_declared_by_bind_permission_without_config():
    # a11y=None bywa „to nie usługa dostępności” albo „XML konfiguracji nieczytelny” — samo uprawnienie wystarcza
    comp = Component("service", "com.x.A11y", False, "android.permission.BIND_ACCESSIBILITY_SERVICE", ())
    facts = AppFacts("com.x", apk_components=(comp,))
    assert _by_cap(facts)["accessibility"]["declared"] is True


def test_accessibility_declared_unknown_without_components():
    facts = AppFacts("com.x", accessibility_enabled=True)
    assert _by_cap(facts)["accessibility"]["declared"] is None


def test_quiet_app_has_no_ladders():
    assert ladders(AppFacts("com.x")) == []


def test_code_level_comes_from_code_paths():
    path = CodePath("hide_icon", "com.x.Main", None, ("com.x.Main.onCreate",), "app")
    facts = AppFacts("com.x", code_paths=(path,), has_launcher_icon=False)
    assert _by_cap(facts)["hide_icon"] == {"declared": None, "code": True, "granted": None, "observed": True}
