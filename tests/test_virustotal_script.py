import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "virustotal.py"


def _module():
    spec = importlib.util.spec_from_file_location("virustotal", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["virustotal"] = module
    spec.loader.exec_module(module)
    return module


def _fake_api(statuses):
    calls = []
    analyses = iter(statuses)

    def request(method, url, headers, body):
        calls.append((method, url, headers, body))
        if url.endswith("/files/upload_url"):
            return {"data": "https://upload.example/abc"}
        if url == "https://upload.example/abc":
            return {"data": {"id": "an-1"}}
        status = next(analyses)
        return {"data": {"attributes": {
            "status": status,
            "stats": {"malicious": 1, "suspicious": 1, "undetected": 60, "harmless": 0},
            "results": {"Zeta": {"category": "malicious"}, "Alpha": {"category": "suspicious"},
                        "Clean": {"category": "undetected"}},
        }}}

    return calls, request


def test_scan_uploads_via_upload_url_and_waits_for_the_analysis(tmp_path):
    m = _module()
    setup = tmp_path / "AdMeNot-0.9.0-setup.exe"
    setup.write_bytes(b"MZ setup")
    calls, request = _fake_api(["queued", "in-progress", "completed"])
    result = m.scan(setup, "KEY", request=request, sleep=lambda s: None, clock=lambda: 0.0)
    assert result.detections == 2 and result.engines == 62
    assert result.flagged == ("Alpha", "Zeta")
    assert result.link == f"https://www.virustotal.com/gui/file/{hashlib.sha256(b'MZ setup').hexdigest()}"
    method, url, headers, body = calls[1]
    assert method == "POST" and url == "https://upload.example/abc"
    assert headers["x-apikey"] == "KEY" and b'filename="AdMeNot-0.9.0-setup.exe"' in body
    assert headers["content-type"].startswith("multipart/form-data; boundary=")
    assert len(calls) == 5  # upload_url, upload, 3 odczyty analizy


def test_scan_gives_up_after_the_timeout(tmp_path):
    m = _module()
    setup = tmp_path / "s.exe"
    setup.write_bytes(b"x")
    _, request = _fake_api(["queued"] * 1000)
    times = iter(range(0, 100_000, 60))
    with pytest.raises(m.VtError, match="nie skończyła"):
        m.scan(setup, "KEY", request=request, sleep=lambda s: None, clock=lambda: next(times))


def test_unexpected_response_is_a_vt_error(tmp_path):
    m = _module()
    setup = tmp_path / "s.exe"
    setup.write_bytes(b"x")
    with pytest.raises(m.VtError):
        m.scan(setup, "KEY", request=lambda *a: {"error": "quota"}, sleep=lambda s: None)
