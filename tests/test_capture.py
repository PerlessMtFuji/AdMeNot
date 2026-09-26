from conftest import NOTIFICATIONS_OUT, SERIAL, make_synthetic_adb

from demalware.cli.main import main
from demalware.engine.adb.fake import FakeAdb
from demalware.engine.capture import anonymize
from demalware.engine.device.info import GETPROP
from demalware.engine.parsers.notifications import parse_notifications
from demalware.engine.session import run_scan


def test_anonymize_getprop_whitelist():
    """getprop: keep only ro.* properties that don't match _SENSITIVE_PROP."""
    output = anonymize(
        GETPROP,
        "[ro.serialno]: [R58T00TEST]\n"
        "[persist.sys.device_name]: [Telefon Anny]\n"
        "[ro.product.model]: [SM-A145R]\n"
        "[ro.build.version.release]: [14]\n",
        "R58T00TEST",
    )
    # ro.serialno is ro.* but matches serial → redacted
    assert "[ro.serialno]: [<redacted>]" in output
    # persist.sys.device_name doesn't start with ro. → redacted
    assert "[persist.sys.device_name]: [<redacted>]" in output
    # ro.product.model is ro.* and doesn't match sensitive → kept
    assert "[ro.product.model]: [SM-A145R]" in output
    # ro.build.version.release is ro.* and doesn't match sensitive → kept
    assert "[ro.build.version.release]: [14]" in output


def test_anonymize_notification_whitelist():
    """dumpsys notification: whitelist keeps headers, record, fullscreen, uid lines; drops rest."""
    output = anonymize(
        "dumpsys notification",
        "  Notification List:\n"
        "    NotificationRecord(0x1: pkg=com.a user=0 text=secret):\n"
        "      fullscreenIntent=PendingIntent{123}\n"
        "      uid=10001\n"
        "      tickerText=hidden\n"
        "  Snoozed notifications:\n",
        None,
    )
    assert "  Notification List:" in output
    assert "NotificationRecord(0x1: pkg=com.a)" in output
    assert "text=secret" not in output
    assert "fullscreenIntent=PendingIntent{<redacted>}" in output
    assert "uid=10001" in output
    assert "tickerText" not in output
    assert "  Snoozed notifications:" in output


def test_anonymize_notification_header_rule_fails_closed():
    """Whitelist-only headers prevent all leakage (indent, tabs, formatting controlled by attacker)."""
    output = anonymize(
        "dumpsys notification",
        "  Notification List:\n"
        "    NotificationRecord(0x1: pkg=com.a):\n"
        "      Anna:\n"
        "    NotificationRecord(0x2: pkg=com.b):\n"
        "        Hey Anna, see you at 5:\n"
        "    NotificationRecord(0x3: pkg=com.c):\n"
        "Anna:\n"
        "    NotificationRecord(0x4: pkg=com.d):\n"
        "  Anna Kowalski:\n"
        "    NotificationRecord(0x5: pkg=com.e):\n"
        "\t\tAnna:\n",
        None,
    )
    # All leak inputs should be dropped
    assert "Anna" not in output
    assert "Kowalski" not in output
    # Valid header should be kept
    assert "  Notification List:" in output


def test_anonymize_notification_record_drops_injected_name():
    """Injected text mimicking NotificationRecord with a non-hex id must be dropped entirely."""
    output = anonymize(
        "dumpsys notification",
        "  Notification List:\n"
        "    NotificationRecord(0x1: pkg=com.a):\n"
        "      NotificationRecord(Anna Kowalski: pkg=com.a)\n",
        None,
    )
    assert "Kowalski" not in output
    assert "Anna" not in output
    assert "NotificationRecord(0x1: pkg=com.a)" in output


def test_anonymize_notification_record_known_packages():
    """With known_packages, only ids matching 0x... and pkg in the whitelist survive."""
    output = anonymize(
        "dumpsys notification",
        "  Notification List:\n"
        "    NotificationRecord(0x2: pkg=Kowalski.evil user=0):\n"
        "    NotificationRecord(0x1: pkg=com.legit.app user=0):\n",
        None,
        known_packages=frozenset({"com.legit.app"}),
    )
    assert "Kowalski" not in output
    assert "NotificationRecord(0x1: pkg=com.legit.app)" in output
    assert "NotificationRecord(0x2:" not in output


def test_anonymize_notification_record_no_known_packages_requires_dotted_pkg():
    """Without known_packages, pkg must fully match the dotted-name pattern."""
    output = anonymize(
        "dumpsys notification",
        "  Notification List:\n    NotificationRecord(0x3: pkg=Kowalski user=0):\n",
        None,
    )
    assert "Kowalski" not in output
    assert "NotificationRecord(0x3:" not in output


def test_anonymize_notification_enqueued_section():
    """Unknown section headers at indent ≤ 2 become <section> boundary marker."""
    output = anonymize(
        "dumpsys notification",
        "  Notification List:\n"
        "    NotificationRecord(0x1: pkg=com.a):\n"
        "      uid=1\n"
        "  Enqueued Notification List:\n"
        "    NotificationRecord(0x2: pkg=com.b):\n"
        "      uid=2\n",
        None,
    )
    # "Enqueued Notification List:" is not in whitelist, so becomes <section>
    assert "<section>" in output
    # Original packages should parse identically
    original = parse_notifications(
        "  Notification List:\n"
        "    NotificationRecord(0x1: pkg=com.a):\n"
        "      uid=1\n"
        "  Enqueued Notification List:\n"
        "    NotificationRecord(0x2: pkg=com.b):\n"
        "      uid=2\n"
    )
    anonymized = parse_notifications(output)
    assert original == anonymized


def test_anonymize_notification_preserves_parsing():
    """Anonymized notification output parses to same result as original."""
    anon = anonymize("dumpsys notification", NOTIFICATIONS_OUT, None)
    original = parse_notifications(NOTIFICATIONS_OUT)
    anonymized = parse_notifications(anon)
    assert original == anonymized


def test_anonymize_emails_everywhere():
    assert anonymize("dumpsys usagestats", "user anna.k@example.com x", None) == "user <email> x"


def test_anonymize_serial_as_token():
    """Serial replacement only for whole tokens, and only if len >= 6."""
    # 6+ chars, replaced as token
    output = anonymize("getprop", "sn R58T00TEST x", "R58T00TEST")
    assert output == "sn SERIAL x"
    # 6+ chars, not replaced when adjacent to alphanumeric
    output = anonymize("getprop", "sn R58T00TESTX x", "R58T00TEST")
    assert "R58T00TEST" in output
    # < 6 chars, never replaced
    output = anonymize("getprop", "sn AB12 x", "AB12")
    assert output == "sn AB12 x"


def test_capture_roundtrip(tmp_path, capsys):
    out_dir = tmp_path / "a14"
    assert main(["capture", "--out", str(out_dir)], host=make_synthetic_adb()) == 0

    files = list(out_dir.glob("*.txt"))
    assert (out_dir / "manifest.json").exists() and files
    for f in files:
        text = f.read_text("utf-8")
        assert SERIAL not in text
        assert "hej, jutro" not in text and "anna.k@example.com" not in text

    replay = FakeAdb.from_capture(out_dir)
    report = run_scan(replay)
    verdicts = {r.facts.package: r.verdict for r in report.results}
    assert verdicts["com.clean.pro.boost"] == "malicious"
    assert verdicts["com.wlive.forecast"] == "review"
    assert all(s.ok for s in report.collectors.values())


def test_capture_with_apk_reports_roundtrip(tmp_path, capsys, monkeypatch):
    from test_cli import _FakeDeviceProvider

    from demalware.engine.apk.providers import StoredApkProvider

    monkeypatch.setattr("demalware.cli.main.DeviceApkProvider", _FakeDeviceProvider)
    out_dir = tmp_path / "a14"
    assert main(["capture", "--apk", "--out", str(out_dir)], host=make_synthetic_adb()) == 0
    stored = out_dir / "apk" / "com.wlive.forecast.json"
    assert stored.exists()
    report = run_scan(FakeAdb.from_capture(out_dir), apk=StoredApkProvider(out_dir / "apk"))
    verdicts = {r.facts.package: r.verdict for r in report.results}
    assert verdicts["com.wlive.forecast"] == "suspicious"
