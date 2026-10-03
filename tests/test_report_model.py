from datetime import datetime

import pytest

from admenot.engine.journal.db import Journal
from admenot.engine.phones.provider import SILHOUETTE
from admenot.engine.report.model import AppRow, Recommendation, ScanScope, build_protocol

NOW = datetime(2026, 9, 26, 14, 5)
BOOST, FORECAST, GAME = "com.clean.pro.boost", "com.wlive.forecast", "com.game"


def snapshot(image, confidence="exact", patch="2026-07-01", market_name=None):
    # Tylko pola, których używa model; pełny kształt migawki — Task 2.
    return {
        "version": 1,
        "scope": {"profiles": {"scanned": [0], "present": [0]}, "usage_window_h": 72.0,
                  "low_behavior_data": False, "collectors": {}, "apk": None},
        "device": {"serial": "R58", "brand": "samsung", "manufacturer": "samsung",
                   "model": "SM-A145R", "market_name": market_name, "android_release": "14",
                   "sdk": 34, "security_patch": patch},
        "phone": {"name": "Samsung Galaxy A14", "slug": "samsung-galaxy-a14",
                  "confidence": confidence, "image": str(image)},
        "app_count": 40,
        "apps": [
            {"package": BOOST, "label": "Cleaner", "verdict": "malicious", "score": 95,
             "incomplete": False, "gaps": [],
             "problems": {"pl": ["Ukryta aplikacja"], "en": ["Hidden app"]}},
            {"package": FORECAST, "label": "Pogoda", "verdict": "suspicious", "score": 60,
             "incomplete": False, "gaps": [],
             "problems": {"pl": ["Spam powiadomień"], "en": ["Notification spam"]}},
            {"package": GAME, "label": None, "verdict": "review", "score": 30,
             "incomplete": False, "gaps": [],
             "problems": {"pl": ["Reklamy"], "en": ["Ads"]}},
        ],
    }


DEFAULT_ACTS = ((BOOST, "remove", ("done", "done")), (FORECAST, "disable", ("done",)))


@pytest.fixture
def journal(tmp_path):
    with Journal(tmp_path / "j.db", now=lambda: NOW) as j:
        yield j


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "samsung-galaxy-a14.webp"
    path.write_bytes(b"RIFF\0\0\0\0WEBP")
    return path


def make_order(journal, snap, acts=DEFAULT_ACTS, verification=None):
    order = journal.create_order("R58", "SM-A145R", "Anna Nowak")
    for package, level, statuses in acts:
        for status in statuses:
            aid = journal.add_action(order.id, package, level,
                                     {"kind": "force_stop", "package": package, "params": {}}, "cmd")
            if status != "pending":
                journal.set_action_status(aid, status)
    if snap is not None:
        journal.save_scan(order.id, snap)
    if verification is not None:
        journal.save_verification(order.id, verification)
    return order


def test_rows_device_and_recommendations(journal, photo):
    order = make_order(journal, snapshot(photo), verification={})
    p = build_protocol(journal, order.id, "pl")
    assert (p.number, p.created_at, p.client_name, p.lang) == (order.number, NOW, "Anna Nowak", "pl")
    assert p.has_scan and p.clean_count == 37
    assert p.rows == [
        AppRow(BOOST, "Cleaner", "malicious", ["Ukryta aplikacja"], "remove", "done"),
        AppRow(FORECAST, "Pogoda", "suspicious", ["Spam powiadomień"], "disable", "done"),
        AppRow(GAME, None, "review", ["Reklamy"], None, "none"),
    ]
    d = p.device
    assert (d.name, d.model, d.android, d.serial, d.security_patch) == (
        "Samsung Galaxy A14", "SM-A145R", "14", "R58", "2026-07-01")
    assert (d.image, d.photo) == (photo, "exact")
    assert p.scope == ScanScope([], True, False, 72.0, 0) and not p.scope.limited
    assert p.recommendations == [
        Recommendation("review_left", {"apps": GAME}),
        Recommendation("removed"),
        Recommendation("disabled"),
        Recommendation("general"),
    ]


def test_many_apps_left_for_review_are_counted_not_listed(journal, photo):
    snap = snapshot(photo)
    for i in range(3):
        snap["apps"].append({"package": f"com.more{i}", "label": None, "verdict": "review",
                             "score": 20, "incomplete": False, "gaps": [],
                             "problems": {"pl": ["Reklamy"], "en": ["Ads"]}})
    p = build_protocol(journal, make_order(journal, snap).id, "pl")
    assert Recommendation("review_left_many", {"count": "4"}) in p.recommendations
    assert not any(r.key == "review_left" for r in p.recommendations)


def test_problems_follow_the_language(journal, photo):
    order = make_order(journal, snapshot(photo))
    rows = build_protocol(journal, order.id, "en").rows
    assert [r.problems for r in rows] == [["Hidden app"], ["Notification spam"], ["Ads"]]


def test_verification_marks_app_still_active(journal, photo):
    order = make_order(journal, snapshot(photo), verification={FORECAST: ["enabled"]})
    p = build_protocol(journal, order.id, "pl")
    assert p.rows[1].outcome == "still_active"
    assert Recommendation("unfinished", {"apps": "Pogoda"}) in p.recommendations
    assert Recommendation("disabled") not in p.recommendations


def test_outcomes_from_action_statuses(journal, photo):
    acts = (
        ("com.failed", "silence", ("done", "failed")),
        ("com.pending", "disable", ("done", "pending")),
        ("com.undone", "remove", ("undone", "undone", "failed")),
        ("com.partial", "disable", ("undone", "done")),
    )
    order = make_order(journal, snapshot(photo), acts,
                       verification={"com.undone": ["installed"], "com.partial": ["enabled"]})
    p = build_protocol(journal, order.id, "pl")
    outcomes = {r.package: r.outcome for r in p.rows}
    assert outcomes == {"com.failed": "failed", "com.pending": "interrupted",
                        "com.undone": "undone", "com.partial": "partially_undone",
                        BOOST: "none", FORECAST: "none", GAME: "none"}
    assert p.recommendations[0] == Recommendation("unfinished",
                                                  {"apps": "com.failed, com.pending"})
    assert Recommendation("removed") not in p.recommendations


def test_order_without_snapshot(journal):
    order = make_order(journal, None)
    p = build_protocol(journal, order.id, "pl")
    assert not p.has_scan and p.clean_count is None and p.scope is None
    assert p.rows == [AppRow(BOOST, None, None, [], "remove", "done"),
                      AppRow(FORECAST, None, None, [], "disable", "done")]
    assert (p.device.name, p.device.model, p.device.android, p.device.serial) == (
        "SM-A145R", "SM-A145R", None, "R58")
    assert (p.device.image, p.device.photo) == (SILHOUETTE, "none")
    assert p.recommendations == [Recommendation("removed"), Recommendation("disabled"),
                                 Recommendation("general")]


def test_photo_missing_after_rebuild_and_approximate_match(journal, tmp_path, photo):
    gone = build_protocol(journal, make_order(journal, snapshot(tmp_path / "gone.webp")).id, "pl")
    assert (gone.device.image, gone.device.photo, gone.device.name) == (
        SILHOUETTE, "none", "Samsung Galaxy A14")

    approx = build_protocol(journal, make_order(
        journal, snapshot(photo, confidence="approximate")).id, "pl")
    assert (approx.device.photo, approx.device.name) == ("approximate", "Samsung SM-A145R")

    named = build_protocol(journal, make_order(
        journal, snapshot(photo, confidence="approximate", market_name="Galaxy A14")).id, "pl")
    assert named.device.name == "Galaxy A14"


@pytest.mark.parametrize(("patch", "old"), [
    ("2025-09-25", True), ("2025-09-26", False), ("2026-07-01", False), ("", False),
    ("nieznana", False), (None, False),
])
def test_old_security_patch(journal, photo, patch, old):
    order = make_order(journal, snapshot(photo, patch=patch))
    recs = build_protocol(journal, order.id, "pl").recommendations
    assert (Recommendation("old_patch", {"date": patch}) in recs) is old


def test_incomplete_scan_is_never_a_plain_all_clear(journal, photo):
    snap = snapshot(photo)
    snap["scope"] |= {"profiles": {"scanned": [0], "present": [0, 10]}, "usage_window_h": 3.0,
                      "low_behavior_data": True}
    snap["apps"][2] |= {"incomplete": True, "gaps": ["usagestats"]}
    snap["apps"].append({"package": "com.safe.gap", "label": "Safe", "verdict": "safe",
                         "score": 0, "incomplete": True, "gaps": ["appops"],
                         "problems": {"pl": [], "en": []}})
    order = make_order(journal, snap, verification={})
    p = build_protocol(journal, order.id, "pl")
    assert "com.safe.gap" not in {r.package for r in p.rows}  # safe: liczba w zakresie, nie wiersz
    assert p.rows[2] == AppRow(GAME, None, "review", ["Reklamy"], None, "none",
                               True, ["usagestats"])
    assert p.scope == ScanScope([10], True, True, 3.0, 1) and p.scope.limited
    assert p.clean_count == 36  # 40 − 3 wiersze − 1 z oceną niepełną
    assert p.recommendations.index(Recommendation("incomplete_scan")) == 1  # po review_left


@pytest.mark.parametrize(("profiles", "gaps", "limited"), [
    ({"scanned": [0], "present": [0]}, [], False),
    ({"scanned": [0], "present": None}, [], True),  # listy profili nie udało się odczytać
    ({"scanned": [0], "present": [0, 10]}, [], True),
    ({"scanned": [0], "present": [0]}, ["apk"], True),  # luka przy aplikacji ze zlecenia
])
def test_incomplete_scan_recommendation(journal, photo, profiles, gaps, limited):
    snap = snapshot(photo)
    snap["scope"]["profiles"] = profiles
    snap["apps"][0] |= {"incomplete": bool(gaps), "gaps": gaps}
    recs = build_protocol(journal, make_order(journal, snap).id, "pl").recommendations
    assert (Recommendation("incomplete_scan") in recs) is limited


@pytest.mark.parametrize(("statuses", "outcome"), [
    (("undone",), "undone"),
    (("done", "undone"), "partially_undone"),
])
def test_undone_flagged_app_still_gets_review_left(journal, photo, statuses, outcome):
    snap = snapshot(photo)
    snap["apps"] = [snap["apps"][0]]  # tylko BOOST (malicious) — zostaje na telefonie po cofnięciu
    order = make_order(journal, snap, ((BOOST, "remove", statuses),))
    p = build_protocol(journal, order.id, "pl")
    boost = next(r for r in p.rows if r.package == BOOST)
    assert boost.outcome == outcome
    assert Recommendation("review_left", {"apps": "Cleaner"}) in p.recommendations


def test_photo_relocated_after_app_moved(journal, tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    (assets / "phones").mkdir(parents=True)
    relocated = assets / "phones" / "samsung-galaxy-a14.webp"
    relocated.write_bytes(b"RIFF\0\0\0\0WEBP")
    monkeypatch.setenv("ADMENOT_ASSETS", str(assets))
    old_path = tmp_path / "old-install" / "samsung-galaxy-a14.webp"  # katalog już nie istnieje
    order = make_order(journal, snapshot(old_path))
    p = build_protocol(journal, order.id, "pl")
    assert p.device.image == relocated
    assert p.device.photo == "exact"


def test_safe_app_chosen_by_the_technician_is_a_row(journal, photo):
    snap = snapshot(photo)
    snap["apps"].append({"package": "com.chosen", "label": "Latarka", "verdict": "safe",
                         "score": 0, "incomplete": False, "gaps": [],
                         "problems": {"pl": [], "en": []}, "icon": "data:image/png;base64,AA=="})
    acts = DEFAULT_ACTS + (("com.chosen", "silence", ("done",)),)
    p = build_protocol(journal, make_order(journal, snap, acts).id, "pl")
    assert AppRow("com.chosen", "Latarka", "safe", [], "silence", "done",
                  icon="data:image/png;base64,AA==") in p.rows
    assert p.clean_count == 36 and p.scope.incomplete_apps == 0


def test_protocol_takes_the_eight_newest_chosen_shots_with_a_jpeg(monkeypatch, tmp_path):
    from admenot.engine import paths
    from admenot.engine.journal.db import Journal
    from admenot.engine.report.model import build_protocol

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    context = {"foreground": None, "overlays": [], "black": False}
    with Journal(":memory:", now=lambda: datetime(2026, 9, 29, 10, 0)) as journal:
        order = journal.create_order("S1", "SM-A145R")
        ids = [journal.add_screenshot("S1", context).id for _ in range(10)]
        journal.attach_screenshots(ids, order.id)  # zaznaczone: 8 najnowszych (ids[2:])
        for shot_id in ids:
            _png, jpg = paths.screenshot_files(shot_id)
            jpg.parent.mkdir(parents=True, exist_ok=True)
            if shot_id != ids[5]:  # jeden bez kopii JPG
                jpg.write_bytes(b"\xff\xd8jpeg")
        protocol = build_protocol(journal, order.id, "pl")
    assert [s.image.name for s in protocol.screenshots] == [
        f"{i}.jpg" for i in ids[2:] if i != ids[5]]
    assert protocol.screenshots[0].context == context
