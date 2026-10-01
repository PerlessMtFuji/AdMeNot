from demalware.engine.adb.fake import FakeAdb
from demalware.engine.collectors.behavior import NOTIFICATIONS
from demalware.engine.foreground import ACTIVITIES, WINDOWS
from demalware.engine.incident import Sample, Timeline, attribute, incident_facts, record


def _s(t, resumed="com.android.launcher", overlays=(), notif=None):
    return Sample(t, resumed, list(overlays) if overlays is not None else None, notif, [])


def test_overlay_at_the_mark_is_attributed_with_what_it_covered():
    tl = Timeline([_s(0.0), _s(2.0, resumed="com.game", overlays=["com.ads.cleaner"])], marks=[2.5])
    (a,) = [a for a in attribute(tl) if a.kind == "overlay"]
    assert (a.package, a.kind, a.over) == ("com.ads.cleaner", "overlay", "com.game")


def test_unknown_overlays_never_mean_none():
    tl = Timeline([_s(0.0, overlays=None)], marks=[0.5])
    assert all(a.kind != "overlay" for a in attribute(tl))


def test_new_notification_near_the_mark():
    tl = Timeline([_s(0.0, notif={"com.spam": 1}), _s(2.0, notif={"com.spam": 3})], marks=[2.0])
    assert ("com.spam", "new_notification") in {(a.package, a.kind) for a in attribute(tl)}


def test_samples_outside_the_window_are_ignored():
    tl = Timeline([_s(0.0, overlays=["com.ads"]), _s(20.0)], marks=[20.0])
    assert "com.ads" not in {a.package for a in attribute(tl)}


def test_incident_facts_count_marks_per_package():
    tl = Timeline([_s(0.0, resumed="com.game", overlays=["com.ads"]),
                   _s(10.0, resumed="com.game", overlays=["com.ads"])], marks=[0.0, 10.0])
    assert incident_facts(attribute(tl))["com.ads"] == (2, "com.game")


def test_record_samples_until_duration_and_keeps_marks():
    now = [0.0]
    adb = FakeAdb({ACTIVITIES: "", WINDOWS: "", NOTIFICATIONS: ""})
    marks = iter([False, True, False])
    tl = record(adb, 3.0, 1.0, clock=lambda: now[0],
                sleep=lambda s: now.__setitem__(0, now[0] + s), poll_mark=lambda: next(marks, False))
    assert len(tl.samples) == 3 and tl.marks == [1.0]
    assert all(s.notif_active is None for s in tl.samples)  # nierozpoznany odczyt = nie odczytano


def test_saved_incident_feeds_the_next_scan_only_while_fresh(tmp_path):
    from datetime import datetime, timedelta

    from demalware.engine.incident import load_incident, save_incident

    tl = Timeline([_s(0.0, resumed="com.game", overlays=["com.ads"])], marks=[0.0])
    path = tmp_path / "incidents" / "SERIAL.json"
    at = datetime(2026, 10, 1, 12, 0)
    save_incident(path, tl, at)
    assert load_incident(path, at + timedelta(hours=1)) == {"com.ads": (1, "com.game")}
    assert load_incident(path, at + timedelta(hours=25)) is None  # stare nagranie nie opisuje telefonu
    assert load_incident(tmp_path / "missing.json", at) is None
    path.write_text("{broken", "utf-8")
    assert load_incident(path, at) is None


def test_scan_with_an_incident_sets_hits_and_fires_the_rule():
    from conftest import make_synthetic_adb

    from demalware.engine.session import run_scan

    report = run_scan(make_synthetic_adb(), incidents={"com.clean.pro.boost": (1, "com.game")})
    by_pkg = {r.facts.package: r for r in report.results}
    hit = by_pkg["com.clean.pro.boost"]
    assert hit.facts.incident_hits == 1 and hit.facts.incident_over == "com.game"
    assert "DM-INCIDENT-01" in {f.rule_id for f in hit.findings}
    assert by_pkg["com.whatsapp"].facts.incident_hits == 0  # nagranie było: brak trafień to 0, nie „nie wiadomo”
    assert run_scan(make_synthetic_adb()).results[0].facts.incident_hits is None
