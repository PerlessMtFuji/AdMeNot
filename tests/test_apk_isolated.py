import os
import time

from demalware.engine.apk.analyze import ApkReport
from demalware.engine.apk.isolated import IsolatedAnalyzer


def _analyze(package, paths):
    if package == "com.slow":
        time.sleep(60)
    if package == "com.crash":
        os._exit(3)
    if package == "com.raise":
        raise RuntimeError("boom")
    return ApkReport(package, class_count=len(paths) + 1)


def test_hung_analysis_is_killed_and_next_app_still_works():
    analyzer = IsolatedAnalyzer(timeout_s=5, analyze=_analyze)
    try:
        slow = analyzer.analyze("com.slow", [])
        fast = analyzer.analyze("com.fast", [])
    finally:
        analyzer.close()
    assert slow.error.startswith("timeout")
    assert fast.error is None and fast.class_count == 1


def test_crashed_process_becomes_an_error_report():
    analyzer = IsolatedAnalyzer(timeout_s=10, analyze=_analyze)
    try:
        crash = analyzer.analyze("com.crash", [])
        after = analyzer.analyze("com.ok", [])
    finally:
        analyzer.close()
    assert crash.error.startswith("analysis process died")
    assert after.error is None


def test_exception_in_analysis_is_returned_as_report_error():
    analyzer = IsolatedAnalyzer(timeout_s=10, analyze=_analyze)
    try:
        report = analyzer.analyze("com.raise", [])
    finally:
        analyzer.close()
    assert report.error == "RuntimeError: boom"
