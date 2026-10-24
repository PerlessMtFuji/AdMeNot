from pathlib import Path

import pytest

from admenot.engine.parsers.common import UnrecognizedOutput
from admenot.engine.parsers.site_notifications import (
    parse_notification_dump,
    site_origin,
    tag_origin,
)

DATA = Path(__file__).parent / "data" / "site_notifications"


def read(name: str) -> str:
    return (DATA / name).read_text(encoding="utf-8")


def test_samsung_dump_has_chrome_site_channel_and_shared_channels():
    dump = parse_notification_dump(read("samsung_sbrowser.txt"))
    chrome = {c.id: c for c in dump.channels["com.android.chrome"]}
    web = [c for c in chrome.values() if c.id.startswith("web:")]
    assert [(site_origin(c.id), c.name) for c in web] == [("https://www.bennish.net", "www.bennish.net")]
    sb = {c.id for c in dump.channels["com.sec.android.app.sbrowser"]}
    assert "SBROWSER_WEBSITES_NOTIFICATION_CHANNEL" in sb


def test_chrome_channel_groups_include_sites():
    dump = parse_notification_dump(read("oppo_chrome.txt"))
    assert {"general", "sites"} <= dump.groups["com.android.chrome"]


def test_sbrowser_active_notification_carries_origin_in_tag_and_subtext():
    [n] = [a for a in parse_notification_dump(read("samsung_sbrowser.txt")).active
           if a.package == "com.sec.android.app.sbrowser"]
    assert n.channel == "SBROWSER_WEBSITES_NOTIFICATION_CHANNEL"
    assert tag_origin(n.tag) == "https://web-push-book.gauntface.com"
    assert n.sub_text == "web-push-book.gauntface.com"


def test_firefox_active_notification_has_subtext_only():
    [n] = [a for a in parse_notification_dump(read("samsung_firefox.txt")).active
           if a.package == "org.mozilla.firefox"]
    assert n.channel == "mozac.feature.webnotifications.generic.channel"
    assert tag_origin(n.tag) is None and n.sub_text == "web-push-book.gauntface.com"


def test_oppo_site_channel_is_allowed_and_ordinary_channels_are_kept():
    dump = parse_notification_dump(read("oppo_chrome.txt"))
    chrome = {c.id: c for c in dump.channels["com.android.chrome"]}
    [web] = [c for c in chrome.values() if c.id.startswith("web:")]
    assert (site_origin(web.id), web.name, web.importance) == ("https://www.bennish.net", "www.bennish.net", 3)
    assert {"incognito", "media", "browser", "downloads"} <= set(chrome)
    assert dump.active == []


def test_blocked_site_channel_importance_zero():
    text = read("oppo_chrome.txt").replace("mImportance=3", "mImportance=0", 1)
    dump = parse_notification_dump(text)
    [web] = [c for c in dump.channels["com.android.chrome"] if c.id.startswith("web:")]
    assert web.importance == 0
    # the replacement hit only the site channel, the others keep their importance
    others = {c.id: c.importance for c in dump.channels["com.android.chrome"] if c.id != web.id}
    assert set(others.values()) == {2}


def test_samsung_recording_already_shows_blocked_site_channel():
    dump = parse_notification_dump(read("samsung_sbrowser.txt"))
    [web] = [c for c in dump.channels["com.android.chrome"] if c.id.startswith("web:")]
    assert web.importance == 0


def test_unrecognized_without_sections():
    with pytest.raises(UnrecognizedOutput):
        parse_notification_dump("garbage\n")


@pytest.mark.parametrize("old, new", [
    ("mImportance=", "importance="),  # kanały są, ale w formacie, którego wzorzec nie zna
    ("NotificationChannel{", "Channel["),  # sekcje AppSettings bez żadnego kanału
])
def test_unrecognized_when_no_channel_parses(old, new):
    # pusta lista kanałów wyglądałaby jak „brak witryn” (fałszywe OK)
    with pytest.raises(UnrecognizedOutput):
        parse_notification_dump(read("oppo_chrome.txt").replace(old, new))


@pytest.mark.parametrize("cid", ["web:https://a.pl", "web:javascript:x;1", "web:https://a.pl;x", "media"])
def test_site_origin_rejects_malformed(cid):
    assert site_origin(cid) is None


def test_site_origin_keeps_port():
    assert site_origin("web:https://a.pl:8443;123") == "https://a.pl:8443"


@pytest.mark.parametrize("tag", ["2025616763", "p#javascript:x/#1", "p#https://a.pl", ""])
def test_tag_origin_rejects_non_site_tags(tag):
    assert tag_origin(tag) is None
