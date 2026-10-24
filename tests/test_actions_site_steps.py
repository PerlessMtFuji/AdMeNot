import pytest
from fakephone import FakeApp, FakePhone

from admenot.engine.actions import commands as C
from admenot.engine.actions import steps as S
from admenot.engine.actions.errors import ActionError
from admenot.engine.actions.steps import Step, check_step, is_applied
from admenot.engine.parsers.site_notifications import parse_notification_dump

CHROME = "com.android.chrome"
SBROWSER = "com.sec.android.app.sbrowser"
FIREFOX = "org.mozilla.firefox"
SITE = "web:https://www.bennish.net;13437173097254700"
SHARED = "SBROWSER_WEBSITES_NOTIFICATION_CHANNEL"
ORIGIN = "https://www.bennish.net"


def _phone(**kw):
    return FakePhone([FakeApp(CHROME), FakeApp(SBROWSER), FakeApp(FIREFOX)], **kw)


def _channel_step(channel_id=SITE, package=CHROME):
    return Step("channel", package, {"channel_id": channel_id})


def _perm_step(capability, origin=ORIGIN):
    return Step("site_permission", FIREFOX, {"origin": origin, "permission": "desktop-notification",
                                             "capability": capability})


@pytest.mark.parametrize("cid", ["web:https://a';reboot;'.pl;1", "web:https://$(id).pl;1",
                                 "web:https://a.pl;1 ; rm", "web:https://a.pl;1\nreboot",
                                 "SBROWSER_WEBSITES_NOTIFICATION_CHANNEL", "", None, 7])
def test_check_step_rejects_bad_channel_for_chrome(cid):
    with pytest.raises(ActionError):
        check_step(_channel_step(cid))


def test_shared_channel_allowed_only_for_its_browser():
    check_step(_channel_step(SHARED, SBROWSER))
    with pytest.raises(ActionError):
        check_step(_channel_step(SHARED, CHROME))
    with pytest.raises(ActionError):  # kanał Firefoxa nie jest kanałem Samsung Internet
        check_step(_channel_step("mozac.feature.webnotifications.generic.channel", SBROWSER))


def test_check_step_accepts_site_channel():
    check_step(_channel_step())


@pytest.mark.parametrize("params", [
    {"origin": "https://a';reboot;'.com", "permission": "desktop-notification", "capability": "2"},
    {"origin": "https://$(id).com", "permission": "desktop-notification", "capability": "2"},
    {"origin": "https://a.com\n", "permission": "desktop-notification", "capability": "2"},
    {"origin": "a.com", "permission": "desktop-notification", "capability": "2"},
    {"origin": ORIGIN, "permission": "geolocation", "capability": "2"},
    {"origin": ORIGIN, "permission": "desktop-notification", "capability": "3"},
    {"origin": ORIGIN, "permission": "desktop-notification", "capability": 2},
    {"origin": ORIGIN, "permission": "desktop-notification"},
])
def test_check_step_rejects_bad_site_permission(params):
    with pytest.raises(ActionError):
        check_step(Step("site_permission", FIREFOX, params))


def test_site_permission_only_for_a_browser_with_rdp():
    with pytest.raises(ActionError):
        check_step(Step("site_permission", CHROME, _perm_step("2").params))
    check_step(_perm_step("2"))
    check_step(_perm_step("0", "https://a.pl:8443"))


def test_hostile_values_never_reach_the_phone():
    phone = _phone(firefox_debugging=True)
    for step in (_channel_step("web:https://a';reboot;'.pl;1"), _perm_step("2", "https://$(id).pl")):
        for call in (S.probe, lambda p, s: S.apply(p, s)):
            with pytest.raises(ActionError):
                call(phone, step)
    assert phone.calls == [] and phone.opened == [] and phone.forwards == {}


def test_channel_applied_when_blocked_or_gone():
    step = _channel_step()
    assert is_applied(step, {"importance": 0}) and is_applied(step, {"importance": None})
    assert not is_applied(step, {"importance": 3})


def test_channel_probe_reads_importance_and_gone():
    phone = _phone()
    phone.channels = {CHROME: {SITE: 3, "browser": 2}}
    assert S.probe(phone, _channel_step()) == {"importance": 3}
    assert S.probe(phone, _channel_step("web:https://other.pl;1")) == {"importance": None}
    assert S.probe(phone, _channel_step(SHARED, SBROWSER)) == {"importance": None}


def test_channel_probe_unrecognized_dump_is_not_gone():
    phone = _phone(static={C.NOTIFICATIONS_FULL: "Permission Denial: can't dump\n"})
    with pytest.raises(ActionError) as err:
        S.probe(phone, _channel_step())
    assert err.value.key == "unrecognized"


def test_channel_probe_unparseable_channels_are_not_applied():
    # AppSettings bez kanału w znanym formacie: brak kanału to nie „wyłączony”, krok nie jest gotowy
    dump = ("  AppSettings: com.android.chrome (10113)\n"
            f"    NotificationChannel{{id={SITE}, importance=3}}\n")
    phone = _phone(static={C.NOTIFICATIONS_FULL: dump})
    with pytest.raises(ActionError) as err:
        S.probe(phone, _channel_step())
    assert err.value.key == "unrecognized"


def test_channel_dump_is_generated_in_parsable_format():
    phone = _phone()
    phone.channels = {CHROME: {SITE: 3}}
    dump = parse_notification_dump(phone.shell(C.NOTIFICATIONS_FULL))
    assert [(c.id, c.importance) for c in dump.channels[CHROME]] == [(SITE, 3)]


def test_channel_apply_opens_quoted_screen_and_user_toggle_counts():
    phone = _phone()
    phone.channels = {CHROME: {SITE: 3}}
    toggled = []

    def user_taps(ph, package, channel_id):
        toggled.append((package, channel_id))
        ph.channels[package][channel_id] = 0

    phone.on_channel_screen = user_taps
    step = _channel_step()
    S.apply(phone, step)
    assert phone.opened == [C.CHANNEL_SETTINGS.format(package=CHROME, channel=SITE)]
    assert toggled == [(CHROME, SITE)]
    assert is_applied(step, S.probe(phone, step))
    assert S.inverse(step, {"importance": 3}) == Step("channel", CHROME, {"channel_id": SITE, "enabled": "1"})


def test_enable_channel_applied_only_when_on():
    step = Step("channel", CHROME, {"channel_id": SITE, "enabled": "1"})
    assert is_applied(step, {"importance": 3})
    assert not is_applied(step, {"importance": 0}) and not is_applied(step, {"importance": None})


def test_channel_inverse_turns_it_back_on():
    assert S.inverse(_channel_step(), {"importance": 3}) == Step(
        "channel", CHROME, {"channel_id": SITE, "enabled": "1"})


@pytest.mark.parametrize("value", ["2", "", 1, "yes"])
def test_check_step_rejects_bad_enabled(value):
    with pytest.raises(ActionError):
        check_step(Step("channel", CHROME, {"channel_id": SITE, "enabled": value}))


def test_site_url_cuts_origin_at_last_semicolon():
    assert S.site_url(_channel_step("web:https://push.foo;1343")) == "https://push.foo"
    assert S.site_url(_channel_step("web:http://a.pl:8080;1")) == "http://a.pl:8080"


@pytest.mark.parametrize("step", [
    Step("channel", SBROWSER, {"channel_id": SHARED}),
    Step("channel", CHROME, {"channel_id": "web:javascript:x;1"}),
    Step("appop", CHROME, {"op": "POST_NOTIFICATION", "mode": "ignore"}),
])
def test_site_url_none_when_no_site(step):
    assert S.site_url(step) is None


def test_open_site_sends_quoted_url_and_package():
    phone = _phone()
    command = f"am start -a android.intent.action.VIEW -d 'https://push.foo' -p {CHROME}"
    phone.static[command] = "Starting: Intent { act=android.intent.action.VIEW }"
    assert S.open_site(phone, _channel_step("web:https://push.foo;1343")) is True
    assert phone.calls == [command]
    phone.calls.clear()
    assert S.open_site(phone, Step("channel", SBROWSER, {"channel_id": SHARED})) is False
    assert phone.calls == []


def test_open_site_rejects_a_malformed_package_without_sending_anything():
    phone = _phone()
    step = Step("channel", "com.android.chrome; reboot", {"channel_id": "web:https://push.foo;1343"})
    with pytest.raises(ActionError):
        S.open_site(phone, step)
    assert phone.calls == []


def test_each_channel_screen_starts_fresh_instead_of_reusing_the_open_settings_task():
    # Bez czyszczenia zadania Samsung zostawiał na ekranie poprzedni, już wyłączony kanał.
    assert C.CHANNEL_SETTINGS.startswith("am start --activity-clear-task ")


def test_browser_wide_switch_does_not_count():
    phone = _phone()
    phone.channels = {CHROME: {SITE: 3, "browser": 2}}
    step = _channel_step()
    S.apply(phone, step)  # użytkownik wyłącza całą przeglądarkę zamiast witryny
    phone.channels[CHROME]["browser"] = 0
    assert not is_applied(step, S.probe(phone, step))


def test_shared_channel_screen_is_opened_for_samsung_internet():
    phone = _phone()
    phone.channels = {SBROWSER: {SHARED: 3}}
    S.apply(phone, _channel_step(SHARED, SBROWSER))
    assert phone.opened == [C.CHANNEL_SETTINGS.format(package=SBROWSER, channel=SHARED)]


def test_site_permission_probe_apply_inverse_roundtrip():
    phone = _phone(firefox_debugging=True)
    phone.firefox_perms[ORIGIN] = 1
    step = _perm_step("2")
    before = S.probe(phone, step)
    assert before == {"capability": 1} and not is_applied(step, before)
    S.apply(phone, step)
    assert phone.firefox_perms[ORIGIN] == 2
    after = S.probe(phone, step)
    assert is_applied(step, after)
    undo = S.inverse(step, before)
    assert undo == _perm_step("1")
    S.apply(phone, undo)
    assert phone.firefox_perms[ORIGIN] == 1
    assert phone.forwards == {}


def test_site_permission_missing_entry_is_zero_and_inverse_removes():
    phone = _phone(firefox_debugging=True)
    step = _perm_step("2")
    before = S.probe(phone, step)
    assert before == {"capability": 0}
    S.apply(phone, step)
    S.apply(phone, S.inverse(step, before))
    assert ORIGIN not in phone.firefox_perms
    assert is_applied(_perm_step("0"), S.probe(phone, step))


def test_site_permission_rdp_gone_is_not_uncertain():
    phone = _phone(firefox_debugging=False)
    for call in (S.probe, lambda p, s: S.apply(p, s)):
        with pytest.raises(ActionError) as err:
            call(phone, _perm_step("2"))
        assert err.value.key == "rdp_unavailable" and not err.value.uncertain


def test_user_wait_kinds():
    assert S.USER_WAIT_KINDS == frozenset({"admin", "channel"})
