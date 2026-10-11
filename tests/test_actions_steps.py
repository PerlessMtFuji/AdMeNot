import pytest
from fakephone import A11Y, GEARHEAD, LISTENERS, POST, FakeApp, FakePhone

from admenot.engine.actions import commands as C
from admenot.engine.actions import steps as S
from admenot.engine.actions.errors import ActionError, classify, hint_key
from admenot.engine.actions.steps import Step

AD_LISTENER = "com.ad/com.ad.notify.NotifyListenerService"


def _phone(**kw):
    apps = [
        FakeApp("com.ad", requested={POST}, granted={POST}, home_activity=".Home"),
        FakeApp("com.plain"),
        FakeApp("com.android.launcher", system=True, home_activity=".Launcher"),
    ]
    return FakePhone(apps, **kw)


def _remove_listener(components=AD_LISTENER):
    return Step("secure_list", "com.ad", {"key": LISTENERS, "op": "remove", "components": components})


def _apply_and_undo(phone, step):
    """Wykonuje krok, sprawdza cel i cofa go krokiem odwrotnym. Zwraca stan sprzed zmiany."""
    before = S.probe(phone, step)
    assert not S.is_applied(step, before)
    S.apply(phone, step)
    assert S.is_applied(step, S.probe(phone, step))
    S.apply(phone, S.inverse(step, before))
    return before


def test_step_dict_roundtrip():
    step = Step("appop", "com.ad", {"op": "SYSTEM_ALERT_WINDOW", "mode": "deny"})
    assert Step.from_dict(step.to_dict()) == step


def test_appop_deny_and_restore_default():
    phone = _phone()
    step = Step("appop", "com.ad", {"op": "SYSTEM_ALERT_WINDOW", "mode": "deny"})
    assert _apply_and_undo(phone, step) == {"mode": "default"}
    assert phone.apps["com.ad"].appops == {}


def test_appop_restores_exact_previous_mode():
    phone = _phone()
    phone.apps["com.ad"].appops["POST_NOTIFICATION"] = "allow"
    _apply_and_undo(phone, Step("appop", "com.ad", {"op": "POST_NOTIFICATION", "mode": "ignore"}))
    assert phone.apps["com.ad"].appops == {"POST_NOTIFICATION": "allow"}


def test_full_screen_intent_op_is_unsupported_before_android_14():
    step = Step("appop", "com.ad", {"op": "USE_FULL_SCREEN_INTENT", "mode": "deny"})
    with pytest.raises(ActionError) as exc:
        S.probe(_phone(sdk=31), step)
    assert exc.value.key == "unsupported"


def test_permission_revoke_and_regrant():
    phone = _phone()
    step = Step("permission", "com.ad", {"permission": POST, "granted": "0"})
    assert _apply_and_undo(phone, step) == {"granted": True}
    assert phone.apps["com.ad"].granted == {POST}


def test_permission_never_requested_counts_as_revoked():
    step = Step("permission", "com.plain", {"permission": POST, "granted": "0"})
    assert S.is_applied(step, S.probe(_phone(), step))


def test_secure_list_keeps_component_with_dollar_sign():
    phone = _phone(secure={LISTENERS: f"{GEARHEAD}:{AD_LISTENER}"})
    step = _remove_listener()
    before = _apply_and_undo(phone, step)
    assert before == {"value": f"{GEARHEAD}:{AD_LISTENER}"}
    assert phone.secure[LISTENERS] == f"{GEARHEAD}:{AD_LISTENER}"
    S.apply(phone, step)
    assert phone.secure[LISTENERS] == GEARHEAD


def test_secure_list_last_component_leaves_empty_value():
    phone = _phone(secure={LISTENERS: AD_LISTENER})
    step = _remove_listener()
    S.apply(phone, step)
    assert phone.secure[LISTENERS] == ""
    assert S.is_applied(step, S.probe(phone, step))


def test_secure_list_inverse_adds_back_only_components_that_were_present():
    step = _remove_listener(f"{AD_LISTENER}:com.ad/.Other")
    inverse = S.inverse(step, {"value": f"{GEARHEAD}:{AD_LISTENER}"})
    assert inverse == Step("secure_list", "com.ad",
                           {"key": LISTENERS, "op": "add", "components": AD_LISTENER})


def test_secure_list_refuses_value_with_quote():
    service = "com.ad/.A11y"
    phone = _phone(secure={A11Y: f"com.x/.A'B:{service}"})
    step = Step("secure_list", "com.ad", {"key": A11Y, "op": "remove", "components": service})
    with pytest.raises(ActionError) as exc:
        S.apply(phone, step)
    assert exc.value.key == "unrecognized"
    assert phone.secure[A11Y] == f"com.x/.A'B:{service}"



def test_listener_access_is_revoked_in_notification_manager_not_only_in_setting():
    # `settings put` zmienia tylko kopię: NotificationManager nadal ją zatwierdza i przy najbliższej
    # synchronizacji wpis wraca (OPPO CPH2271, 2026-10-07).
    phone = _phone(secure={LISTENERS: f"{GEARHEAD}:{AD_LISTENER}"})
    step = _remove_listener()
    S.apply(phone, step)
    assert phone.listeners_allowed == [GEARHEAD]
    assert phone.secure[LISTENERS] == GEARHEAD
    assert f"cmd notification disallow_listener '{AD_LISTENER}' 0" in phone.calls
    assert not any(c.startswith("settings put") for c in phone.calls)


def test_listener_state_is_read_from_notification_manager_not_the_setting():
    # Kopia w ustawieniu rozjechana (np. stare `settings put`): aplikacja nadal ma dostęp.
    phone = _phone(secure={LISTENERS: f"{GEARHEAD}:{AD_LISTENER}"})
    phone.secure[LISTENERS] = GEARHEAD
    step = _remove_listener()
    before = S.probe(phone, step)
    assert before == {"value": f"{GEARHEAD}:{AD_LISTENER}"}
    assert not S.is_applied(step, before)
    S.apply(phone, step)
    assert phone.listeners_allowed == [GEARHEAD]
    assert S.is_applied(step, S.probe(phone, step))


def test_listener_state_falls_back_to_setting_when_notification_manager_format_is_unknown():
    # Nieznany format linii nie może dać pustej listy: krok uznałby dostęp za już odebrany.
    phone = _phone(secure={LISTENERS: f"{GEARHEAD}:{AD_LISTENER}"})
    phone._notification_manager = lambda: ("  Notification listeners:\n    Allowed notification listeners:\n"
                                           f"      {GEARHEAD}:{AD_LISTENER} [user 0, primary]\n")
    step = _remove_listener()
    assert S.probe(phone, step) == {"value": f"{GEARHEAD}:{AD_LISTENER}"}
    assert not S.is_applied(step, S.probe(phone, step))
    S.apply(phone, step)
    assert phone.listeners_allowed == [GEARHEAD]


def test_listener_access_undo_allows_it_again():
    phone = _phone(secure={LISTENERS: f"{GEARHEAD}:{AD_LISTENER}"})
    _apply_and_undo(phone, _remove_listener())
    assert set(phone.listeners_allowed) == {GEARHEAD, AD_LISTENER}
    assert set(phone.secure[LISTENERS].split(":")) == {GEARHEAD, AD_LISTENER}


def test_listener_access_falls_back_to_setting_without_cmd_notification():
    phone = _phone(secure={LISTENERS: f"{GEARHEAD}:{AD_LISTENER}"}, listener_cmd=False)
    step = _remove_listener()
    before = _apply_and_undo(phone, step)
    assert phone.secure[LISTENERS] == before["value"]
    S.apply(phone, step)
    assert phone.secure[LISTENERS] == GEARHEAD


def test_home_switch_and_back():
    phone = _phone(home="com.ad/.Home")
    step = Step("home", "com.ad", {"component": "com.android.launcher/.Launcher"})
    assert _apply_and_undo(phone, step) == {"component": "com.ad/.Home"}
    assert phone.home == "com.ad/.Home"


def test_home_without_previous_default_has_no_inverse():
    step = Step("home", "com.ad", {"component": "com.android.launcher/.Launcher"})
    before = S.probe(_phone(), step)
    assert before == {"component": None}
    assert S.inverse(step, before) is None


def test_disable_and_enable():
    phone = _phone()
    step = Step("enabled", "com.ad", {"enabled": "0"})
    assert _apply_and_undo(phone, step) == {"enabled": True}
    assert phone.apps["com.ad"].enabled


def test_exit_code_zero_with_error_text_is_a_failure():
    phone = _phone()
    phone.fail[C.PM_DISABLE.format(package="com.ad")] = (
        "Error: java.lang.IllegalArgumentException: Unknown package: com.ad\n")
    with pytest.raises(ActionError) as exc:
        S.apply(phone, Step("enabled", "com.ad", {"enabled": "0"}))
    assert exc.value.key == "failed" and not exc.value.uncertain


def test_disconnect_is_uncertain():
    phone = _phone()
    phone.disconnected = True
    with pytest.raises(ActionError) as exc:
        S.probe(phone, Step("enabled", "com.ad", {"enabled": "0"}))
    assert exc.value.key == "disconnected" and exc.value.uncertain


def test_command_for_describes_step():
    assert S.command_for(Step("enabled", "com.ad", {"enabled": "0"})) == (
        "pm disable-user --user 0 com.ad")
    assert S.command_for(_remove_listener()) == f"cmd notification disallow_listener '{AD_LISTENER}' 0"
    a11y = Step("secure_list", "com.ad", {"key": A11Y, "op": "remove", "components": "com.ad/.A"})
    assert S.command_for(a11y) == f"settings put --user 0 secure {A11Y} (-com.ad/.A)"
    with pytest.raises(ValueError):
        S.command_for(Step("teleport", "com.ad"))


@pytest.mark.parametrize(("text", "kind", "key"), [
    ("Failure [DELETE_FAILED_DEVICE_POLICY_MANAGER]", "command_failed", "device_admin"),
    ("java.lang.SecurityException: Cannot disable a device admin", "command_failed", "device_admin"),
    ("java.lang.SecurityException: uid 2000 does not have android.permission.WRITE_SECURE_SETTINGS.",
     "command_failed", "security"),
    ("Error: Unknown operation string: USE_FULL_SCREEN_INTENT", "command_failed", "unsupported"),
    ("Error: something odd", "command_failed", "failed"),
    ("device 'X' not found", "no_device", "disconnected"),
    ("pm disable-user (>20.0s)", "timeout", "timeout"),
])
def test_classify(text, kind, key):
    assert classify(text, kind) == key


def test_security_hint_depends_on_manufacturer():
    assert hint_key("security", "OPPO") == "security_coloros"
    assert hint_key("security", "Xiaomi") == "security_miui"
    assert hint_key("security", "samsung") == "security"
    assert hint_key("device_admin", "OPPO") == "device_admin"


@pytest.mark.parametrize(("step", "command"), [
    (Step("appop", "com.ad", {"op": "SYSTEM_ALERT_WINDOW", "mode": "deny"}),
     "appops get --user 0 com.ad SYSTEM_ALERT_WINDOW"),
    (Step("enabled", "com.ad", {"enabled": "0"}), "pm list packages -d --user 0"),
    (Step("installed", "com.ad", {"installed": "0", "backup_dir": ""}),
     "pm list packages --user 0 com.ad"),
    (Step("permission", "com.ad", {"permission": POST, "granted": "0"}), "dumpsys package com.ad"),
])
def test_unrecognized_probe_is_an_error_not_a_state(step, command):
    """Audyt 2026-10-11, BUG-03: nierozpoznany odczyt nie może trafić do dziennika jako stan
    sprzed zmiany (np. „enabled”/„default”), bo cofnięcie przywróciłoby fałszywy stan."""
    phone = _phone()
    phone.fail[command] = "unsupported format\n"
    with pytest.raises(ActionError) as caught:
        S.probe(phone, step)
    assert caught.value.key == "unrecognized"


def test_known_empty_answers_stay_valid_states():
    phone = _phone()
    assert S.probe(phone, Step("enabled", "com.ad", {"enabled": "0"})) == {"enabled": True}
    assert S.probe(phone, Step("appop", "com.ad", {"op": "SYSTEM_ALERT_WINDOW", "mode": "deny"})) == {
        "mode": "default"}
    gone = Step("installed", "com.gone", {"installed": "0", "backup_dir": ""})
    assert S.probe(phone, gone) == {"installed": False}


@pytest.mark.parametrize("bad", ["com.ad/.L'; echo audit_probe; #", "com.ad/.L$(id)", "com.ad/.L`id`",
                                 "com.ad/.L\necho x", "com.ad/.Ł"])
def test_listener_component_from_the_phone_is_validated_and_quoted(bad):
    """Audyt 2026-10-11, SEC-01: niezaufany komponent nie dokleja polecenia w powłoce telefonu."""
    phone = _phone()
    step = _remove_listener(bad)
    with pytest.raises(ActionError) as exc:
        S.apply(phone, step)
    assert exc.value.key == "unrecognized"
    assert not [c for c in phone.calls if c.startswith("cmd notification")]
    # Pokazane (i zapisane w dzienniku) polecenie to jedno słowo-argument, nie doklejona komenda.
    import shlex

    assert shlex.split(S.command_for(step)) == ["cmd", "notification", "disallow_listener", bad, "0"]


def test_valid_component_with_dollar_still_works():
    phone = _phone(secure={LISTENERS: "com.ad/.Outer$Listener"})
    _apply_and_undo(phone, _remove_listener("com.ad/.Outer$Listener"))


@pytest.mark.parametrize("step", [
    Step("appop", "com.ad; reboot", {"op": "SYSTEM_ALERT_WINDOW", "mode": "deny"}),
    Step("appop", "com.ad", {"op": "SYSTEM_ALERT_WINDOW; reboot", "mode": "deny"}),
    Step("appop", "com.ad", {"op": "SYSTEM_ALERT_WINDOW", "mode": "deny && reboot"}),
    Step("permission", "com.ad", {"permission": "x;reboot", "granted": "0"}),
    Step("secure_list", "com.ad", {"key": "enabled_accessibility_services;reboot", "op": "remove",
                                   "components": AD_LISTENER}),
    Step("secure_list", "com.ad", {"key": LISTENERS, "op": "remove",
                                   "components": "com.ad/x';reboot;'"}),
    Step("home", "com.ad", {"component": "com.ad/.Home' ; reboot"}),
    Step("enabled", "com.ad", {"enabled": "0 ; reboot"}),
    Step("installed", "com.ad", {"installed": "1", "backup_dir": 7}),
    Step("installed", "com.ad; reboot", {"installed": "1", "backup_dir": ""}),
])
def test_tampered_step_never_reaches_the_phone(step):
    """Kroki czytane z dziennika (SQLite na dysku) nie mogą wstrzyknąć polecenia do powłoki."""
    phone = _phone()
    with pytest.raises(ActionError) as caught:
        S.probe(phone, step)
    assert caught.value.key == "unrecognized"
    with pytest.raises(ActionError):
        S.apply(phone, step)
    assert phone.calls == []


def test_valid_steps_from_the_planner_still_pass():
    for step in (
        Step("appop", "com.ad", {"op": "USE_FULL_SCREEN_INTENT", "mode": "deny"}),
        Step("permission", "com.ad", {"permission": POST, "granted": "0"}),
        _remove_listener(GEARHEAD.split("/")[0] + "/" + GEARHEAD.split("/")[1]),
        Step("home", "com.ad", {"component": "com.android.launcher/.Launcher"}),
        Step("installed", "com.ad", {"installed": "1", "backup_dir": ""}),
        Step("backup", "com.ad", {"dir": "C:/b/com.ad/7", "version_code": "7"}),
        Step("backup", "com.ad", {"dir": "C:/b/com.ad/unknown", "version_code": ""}),
    ):
        S.check_step(step)
