from admenot.engine.browsers.known import KnownBrowser, known_browsers


def test_samsung_internet_entry():
    entry = known_browsers()["com.sec.android.app.sbrowser"]
    assert entry == KnownBrowser(
        package="com.sec.android.app.sbrowser",
        name="Samsung Internet",
        shared_channel="SBROWSER_WEBSITES_NOTIFICATION_CHANNEL",
        origin_from="tag",
        block_action=True,
    )
    assert entry.rdp_socket is None


def test_firefox_entry_has_rdp_socket():
    entry = known_browsers()["org.mozilla.firefox"]
    assert entry.name == "Firefox"
    assert entry.shared_channel == "mozac.feature.webnotifications.generic.channel"
    assert entry.origin_from == "subtext"
    assert entry.rdp_socket == "org.mozilla.firefox/firefox-debugger-socket"
    assert entry.block_action is False  # powiadomienie Firefoksa nie ma akcji „Blokuj”


def test_table_is_cached_and_keyed_by_package():
    table = known_browsers()
    assert known_browsers() is table
    assert set(table) == {"com.sec.android.app.sbrowser", "org.mozilla.firefox"}
    assert all(key == entry.package for key, entry in table.items())
