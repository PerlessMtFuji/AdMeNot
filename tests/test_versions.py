import re

from demalware.engine.session import report_to_dict, run_scan
from demalware.engine.versions import engine_versions


def test_versions_identify_engine_and_every_data_file():
    v = engine_versions()
    assert set(v) == {"engine", "rules", "ad_sdks", "trusted", "iocs"}
    assert all(re.fullmatch(r"[0-9a-f]{12}", v[k]) for k in ("rules", "ad_sdks", "trusted"))
    assert re.fullmatch(r"\d+-[0-9a-f]{12}", v["iocs"])


def test_scan_report_carries_versions(synthetic_adb):
    report = run_scan(synthetic_adb)
    assert report.versions == engine_versions()
    assert report_to_dict(report)["versions"] == engine_versions()
