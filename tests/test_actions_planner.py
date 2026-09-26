from dataclasses import replace
from pathlib import Path

from fakephone import A11Y, GEARHEAD, LISTENERS, FakeApp, FakePhone

from demalware.engine.actions.context import PhoneContext, read_phone_context
from demalware.engine.actions.planner import AppPlan, Blocked, default_level, plan_app
from demalware.engine.allowlist.trust import load_protected_list, parse_package_patterns
from demalware.engine.facts import AppFacts

AD = "com.intelli.clean"
AD_HOME = f"{AD}/com.star.james.ui.activity.launcher.LauncherActivity"
AD_LISTENER = f"{AD}/com.star.james.notify.NotifyListenerService"
LAUNCHER = "com.android.launcher/.Launcher"
IME = "com.ikeyboard.theme.neon"
ROOT = Path("backups") / "SERIAL"
SAW = "android.permission.SYSTEM_ALERT_WINDOW"
PROTECTED = parse_package_patterns(
    "protected:\n  - com.android.settings\n  - com.android.providers.*\n", "protected")

# Stan jak na OPPO CPH2271 z korpusu: adware jest launcherem i nasłuchuje powiadomień.
CTX = PhoneContext(
    sdk=31,
    manufacturer="OPPO",
    ime_package=IME,
    home_component=AD_HOME,
    home_candidates={"com.android.launcher": LAUNCHER, AD: AD_HOME},
    system_packages=frozenset({"com.android.launcher", "com.android.settings"}),
    secure_lists={A11Y: "", LISTENERS: f"{GEARHEAD}:{AD_LISTENER}"},
)


def _plan(package, level, ctx=CTX, version_code=25, unlocked=frozenset(), requested=(SAW,)):
    facts = AppFacts(package, version_code=version_code, requested_permissions=set(requested))
    return plan_app(package, level, facts, ctx, PROTECTED, ROOT, unlocked)


def test_silence_launcher_hijacker_on_android_12():
    plan = _plan(AD, "silence")
    assert isinstance(plan, AppPlan) and plan.warnings == []
    assert [s.kind for s in plan.steps] == ["home", "secure_list", "appop", "appop", "force_stop"]
    home, listener, notif, overlay, _ = plan.steps
    assert home.params == {"component": LAUNCHER}
    assert listener.params == {"key": LISTENERS, "op": "remove", "components": AD_LISTENER}
    assert notif.params == {"op": "POST_NOTIFICATION", "mode": "ignore"}
    assert overlay.params == {"op": "SYSTEM_ALERT_WINDOW", "mode": "deny"}


def test_android_14_revokes_permission_and_blocks_full_screen_intents():
    plan = _plan("com.other", "silence", ctx=replace(CTX, sdk=34))
    assert [(s.kind, s.params.get("op") or s.params.get("permission")) for s in plan.steps] == [
        ("permission", "android.permission.POST_NOTIFICATIONS"),
        ("appop", "SYSTEM_ALERT_WINDOW"),
        ("appop", "USE_FULL_SCREEN_INTENT"),
        ("force_stop", None),
    ]


def test_disable_and_remove_extend_silence():
    disable = _plan("com.other", "disable")
    assert disable.steps[-1].kind == "enabled" and disable.steps[-1].params == {"enabled": "0"}
    remove = _plan("com.other", "remove")
    backup, uninstall = remove.steps[-2:]
    expected = str(ROOT / "com.other" / "25")
    assert (backup.kind, backup.params) == ("backup", {"dir": expected, "version_code": "25"})
    assert (uninstall.kind, uninstall.params) == (
        "installed", {"installed": "0", "backup_dir": expected})
    assert [s.kind for s in remove.steps[:-2]] == [s.kind for s in _plan("com.other", "silence").steps]


def test_remove_without_version_code_uses_unknown_dir():
    backup = _plan("com.other", "remove", version_code=None).steps[-2]
    assert backup.params == {"dir": str(ROOT / "com.other" / "unknown"), "version_code": ""}


def test_protected_packages_and_system_launchers_need_unlock():
    for package in ("com.android.settings", "com.android.providers.media", "com.android.launcher"):
        assert _plan(package, "silence") == Blocked(package, "silence", "protected")
    unlocked = _plan("com.android.providers.media", "disable",
                     unlocked=frozenset({"com.android.providers.media"}))
    assert isinstance(unlocked, AppPlan)


def test_active_keyboard_can_be_silenced_but_not_disabled():
    assert isinstance(_plan(IME, "silence"), AppPlan)
    for level in ("disable", "remove"):
        assert _plan(IME, level, unlocked=frozenset({IME})) == Blocked(IME, level, "active_ime")


def test_only_launcher_cannot_be_disabled_but_can_be_silenced():
    ctx = replace(CTX, system_packages=frozenset())  # brak launchera systemowego
    assert _plan(AD, "disable", ctx=ctx) == Blocked(AD, "disable", "home_no_alternative")
    plan = _plan(AD, "silence", ctx=ctx)
    assert plan.warnings == ["home_not_switched"]
    assert "home" not in [s.kind for s in plan.steps]


def test_missing_app_and_unknown_level():
    assert plan_app("com.gone", "disable", None, CTX, PROTECTED, ROOT) == (
        Blocked("com.gone", "disable", "not_installed"))
    assert _plan("com.other", "nuke") == Blocked("com.other", "nuke", "unknown_level")


def test_default_level_by_verdict():
    verdicts = ("malicious", "suspicious", "review", "safe")
    assert [default_level(v) for v in verdicts] == ["remove", "disable", None, None]


def test_bundled_protected_list_covers_core_system_apps():
    protected = load_protected_list()
    for package in ("com.android.systemui", "com.android.settings", "com.google.android.gms",
                    "com.android.vending", "com.android.providers.telephony"):
        assert protected.matches(package), package
    assert not protected.matches(AD)


def test_read_phone_context_from_phone():
    apps = [
        FakeApp(AD, home_activity=".Launcher"),
        FakeApp("com.android.launcher", system=True, home_activity=".Launcher"),
        FakeApp("com.android.settings", system=True, home_activity=".FallbackHome"),
    ]
    phone = FakePhone(apps, sdk=31, home=f"{AD}/.Launcher", secure={
        "default_input_method": f"{IME}/com.android.inputmethod.latin.LatinIME",
        LISTENERS: AD_LISTENER,
    })
    ctx = read_phone_context(phone, "OPPO")
    assert (ctx.sdk, ctx.manufacturer, ctx.ime_package) == (31, "OPPO", IME)
    assert ctx.home_component == f"{AD}/.Launcher" and ctx.home_package == AD
    assert ctx.home_candidates == {AD: f"{AD}/.Launcher", "com.android.launcher": LAUNCHER}
    assert ctx.system_launchers == frozenset({"com.android.launcher"})
    assert ctx.secure_lists == {A11Y: "", LISTENERS: AD_LISTENER}


def test_overlay_step_only_when_app_can_draw_over_others():
    # Na Androidzie 12 (OPPO) `appops set … SYSTEM_ALERT_WINDOW deny` dla aplikacji bez tego
    # uprawnienia kończy się kodem 0, ale tryb zostaje „default” — weryfikacja pokazałaby „nadal aktywna”.
    plan = _plan(AD, "silence", requested=())
    assert "SYSTEM_ALERT_WINDOW" not in [s.params.get("op") for s in plan.steps]
    assert [s.kind for s in plan.steps] == ["home", "secure_list", "appop", "force_stop"]
