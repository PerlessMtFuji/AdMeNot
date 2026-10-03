import pytest
from apphelpers import make_api
from conftest import SERIAL
from fakephone import make_cli_phone

from admenot.engine.incident import Sample, Timeline
from admenot.engine.paths import incident_path


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))


def _recording(api, overlays=("com.clean.pro.boost",)):
    """Nagranie, w którym użytkownik klika „reklama jest teraz” przy drugiej próbce."""
    calls = {}

    def record(adb, duration_s, interval_s, *, poll_mark, **kw):
        calls.update(duration=duration_s, interval=interval_s)
        tl = Timeline()
        for t in (0.0, 2.0):
            tl.samples.append(Sample(t, "com.game", list(overlays), None, []))
            if t == 2.0:
                assert api.mark_incident() == {"ok": True}
            if poll_mark():
                tl.marks.append(t)
        return tl

    return record, calls


def test_incident_recording_attributes_the_mark_and_feeds_the_next_scan():
    api, rec = make_api(make_cli_phone())
    api.start_scan(SERIAL)
    record, calls = _recording(api)
    api._incident_record = record
    assert api.start_incident(60) == {"ok": True}
    assert calls == {"duration": 60.0, "interval": 2.0}
    (done,) = rec.of("incident:done")
    assert done["marks"] == 1
    assert {"package": "com.clean.pro.boost", "kind": "overlay", "over": "com.game"}.items() <= done["hits"][0].items()
    assert incident_path(SERIAL).exists()
    api.start_scan(SERIAL)
    app = next(a for a in rec.of("scan:done")[-1]["scan"]["apps"] if a["package"] == "com.clean.pro.boost")
    assert any(f["rule_id"] == "DM-INCIDENT-01" for f in app["findings"])


def test_incident_needs_a_phone_and_a_sane_duration():
    api, _ = make_api(make_cli_phone())
    assert api.start_incident(60)["error"]["key"] == "no_device"
    api.start_scan(SERIAL)
    assert api.start_incident(0)["error"]["key"] == "bad_request"
    assert api.start_incident(10_000)["error"]["key"] == "bad_request"
    assert api.mark_incident()["error"]["key"] == "bad_request"  # nic nie nagrywa
