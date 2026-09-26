from conftest import SERIAL, make_synthetic_adb

from demalware.cli.main import main
from demalware.engine.adb.fake import FakeAdb
from demalware.engine.capture import anonymize
from demalware.engine.device.info import GETPROP
from demalware.engine.session import run_scan


def test_anonymize_getprop_and_notifications():
    props = anonymize(GETPROP, "[ro.serialno]: [R58T00TEST]\n[persist.sys.device_name]: [Telefon Anny]\n"
                               "[ro.product.model]: [SM-A145R]\n", "R58T00TEST")
    assert "R58T00TEST" not in props and "Telefon Anny" not in props
    assert "[ro.product.model]: [SM-A145R]" in props

    notif = anonymize("dumpsys notification",
                      "      tickerText=Anna: hej\n      android.title=Anna\n      uid=1\n", None)
    assert "Anna" not in notif and "uid=1" in notif


def test_anonymize_emails_everywhere():
    assert anonymize("dumpsys usagestats", "user anna.k@example.com x", None) == "user <email> x"


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
