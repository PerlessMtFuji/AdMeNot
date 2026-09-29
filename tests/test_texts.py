from demalware.engine.texts import (
    SHOT_TEXTS,
    TEXTS,
    VERDICT_LABELS,
    confidence_label,
    error_text,
    gap_label,
    level_label,
    order_status_label,
    reason_text,
    step_label,
    verdict_label,
    warning_text,
)


def _keys(d: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for k, v in d.items():
        out |= _keys(v, f"{prefix}{k}.") if isinstance(v, dict) else {prefix + k}
    return out


def test_pl_and_en_have_the_same_keys():
    assert _keys(TEXTS["pl"]) == _keys(TEXTS["en"])
    assert set(TEXTS["pl"]) == {"levels", "steps", "reasons", "warnings", "errors",
                                "order_status", "action_status"}
    assert VERDICT_LABELS["pl"].keys() == VERDICT_LABELS["en"].keys()
    assert SHOT_TEXTS["pl"].keys() == SHOT_TEXTS["en"].keys()


def test_step_labels_pick_specific_then_generic_template():
    disable = {"kind": "enabled", "package": "x", "params": {"enabled": "0"}}
    assert step_label(disable, "pl") == "wyłączenie aplikacji"
    assert step_label(disable, "en") == "disable the app"
    notif = {"kind": "appop", "package": "x", "params": {"op": "POST_NOTIFICATION", "mode": "ignore"}}
    assert step_label(notif, "en") == "block notifications"
    other = {"kind": "appop", "package": "x", "params": {"op": "RUN_IN_BACKGROUND", "mode": "ignore"}}
    assert step_label(other, "pl") == "appops RUN_IN_BACKGROUND → ignore"
    home = {"kind": "home", "package": "x", "params": {"component": "a/.B"}}
    assert step_label(home, "pl") == "zmiana ekranu głównego na a/.B"


def test_error_text_uses_oem_hints_and_falls_back_to_key():
    assert "ustawienia zabezpieczeń" in error_text("security", "pl", "Xiaomi")
    assert error_text("security", "en", "OnePlus") == error_text("security_coloros", "en")
    assert error_text("security", "pl") == "telefon odmówił dostępu (SecurityException)"
    assert error_text("no_such_key", "pl") == "no_such_key"


def test_labels():
    assert level_label("remove", "en") == "REMOVE"
    assert level_label("weird", "pl") == "weird"
    assert verdict_label("review", "pl") == "Do sprawdzenia"
    assert reason_text("protected", "pl", "com.x").endswith("--unlock com.x)")
    assert warning_text("home_not_switched", "en").startswith("home screen")


def test_order_status_label_looks_up_section_and_falls_back_to_status():
    assert order_status_label("running", "pl") == "w toku"
    assert order_status_label("done", "en") == "done"
    assert order_status_label("weird", "pl") == "weird"


def test_every_gap_source_has_labels():
    for key in ("components", "appops", "notifications", "usagestats", "alarm", "device_policy",
                "roles", "secure_settings", "packages", "apk"):
        for lang in ("pl", "en"):
            assert gap_label(key, lang) != key


def test_confidence_label_falls_back_to_level():
    assert confidence_label("low", "pl").startswith("niska")
    assert confidence_label("weird", "en") == "weird"
