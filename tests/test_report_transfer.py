from datetime import datetime, timedelta

import pytest

from admenot.engine.journal.db import Journal
from admenot.engine.report.texts import TRANSFER_TEXTS
from admenot.engine.report.transfer_model import APPS_NAMED, build_transfer_protocol
from admenot.engine.report.transfer_render import render_transfer_html
from admenot.engine.settings import ServiceInfo

NOW = datetime(2026, 11, 8, 15, 12)
COPY = "SRC/2026-11-01_100000"
SOURCE = {"manufacturer": "samsung", "model": "SM-A525F", "android": "14", "imei": "351234567890123",
          "serial": "SRCSER", "bytes": 30_000_000_000,
          "counts": {"contacts": 412, "sms": 8000, "mms": 230, "calls": 980, "files_photos": 14000,
                     "files_videos": 210, "files_downloads": 312, "files_whatsapp": 40},
          "selection_groups": ["contacts_messages", "files", "apps"]}
TARGET = {"manufacturer": "OPPO", "model": "CPH2239", "android": "13", "imei": "867654321098765",
          "market_name": "OPPO A54"}


def _files(**over):
    base = {"status": "complete", "target_serial": "T1", "files_done": 14562, "files_exists": 0,
            "apk_skipped": 0, "apk_suspicious_skipped": 0, "hashed": True,
            "groups": {"photos": {"done": 14000, "exists": 0, "skipped": 0, "failed": 0},
                       "videos": {"done": 210, "exists": 0, "skipped": 0, "failed": 0},
                       "downloads": {"done": 312, "exists": 0, "skipped": 0, "failed": 0},
                       "whatsapp": {"done": 40, "exists": 0, "skipped": 0, "failed": 0}}}
    base.update(over)
    return base


def _kind(written, **over):
    return {"written": written, "existed": 0, "skipped_synced": 0, "skipped_messenger": 0, "failed": 0,
            "manual": 0, "path": "app_process", "visible_warning": False, **over}


def _tel(**over):
    kinds = {"contacts": _kind(412), "sms": _kind(8000), "mms": _kind(230), "calls": _kind(980)}
    kinds.update(over)
    return {"kinds": kinds, "safety": {}, "manual": [], "cleanup": {"ok": True}, "synced_accounts": [],
            "seconds": 5, "stopped": False, "status": "complete"}


def _apps(rows):
    inst = sum(1 for r in rows if r["status"] == "installed")
    failed = {}
    for r in rows:
        if r["status"] == "failed":
            failed[r["reason"]] = failed.get(r["reason"], 0) + 1
    return {"selected": len(rows), "installed": inst, "exists": 0, "skipped": {}, "failed": failed,
            "codes": {}, "blocked": False, "stopped": False, "rows": rows, "play_installer": True}


def _row(label, status="installed", reason=None, package=None):
    return {"package": package or "com." + label.lower().replace(" ", ""), "label": label,
            "status": status, "reason": reason}


def _result(rows=None, status="done", **over):
    rows = [_row("Allegro"), _row("Bolt")] if rows is None else rows
    result = {"files": _files(), "tel": _tel(), "apps": _apps(rows), "status": status,
              "finished_at": "2026-11-08T14:00:00"}
    result.update(over)
    return result


@pytest.fixture
def journal(tmp_path):
    with Journal(tmp_path / "j.db") as j:
        yield j


def _order(journal, result=None, status="done", source=None, target=TARGET, whatsapp=False):
    order = journal.create_transfer_order(
        "SRCSER", "SM-A525F", "Anna K.", {"imei": "351234567890123"}, copy_id=COPY,
        source=source or SOURCE, received_at=datetime(2026, 11, 1, 10, 0),
        copy_expires=datetime(2026, 11, 15, 10, 0))
    if target is not None:
        journal.set_transfer_target(order.id, "T1", target)
    if result is not None:
        journal.save_transfer_result(order.id, result)
    journal.set_order_status(order.id, status)
    if whatsapp:
        journal.set_whatsapp_restored(order.id, True)
    return order


def _html(p):
    return render_transfer_html(p, ServiceInfo(name="Serwis GSM"), NOW)


def test_green_protocol_all_ok(journal):
    order = _order(journal, _result())
    p = build_transfer_protocol(journal, order.id, "pl", NOW)
    assert p.tone == "ok"
    assert [t.key for t in p.tiles] == ["contacts", "sms", "calls", "photos", "downloads", "whatsapp"]
    assert len(p.tiles) == 6 and all(t.tone == "ok" and "✓" in t.state for t in p.tiles)
    assert p.apps_installed == p.apps_total == 2
    assert p.copy_until.isoformat() == "2026-11-15"
    assert "Serwis GSM" in _html(p) and "Anna K." in _html(p)


def test_warn_when_apps_failed(journal):
    rows = [_row("Allegro"), _row("Gra XYZ", "failed", "too_old"), _row("Pilot TV", "failed", "failed"),
            _row("Bolt")]
    order = _order(journal, _result(rows))
    p = build_transfer_protocol(journal, order.id, "pl", NOW)
    assert p.tone == "warn" and "2" in p.headline
    assert p.apps_problems == [("Gra XYZ", "za stara dla tego Androida"),
                               ("Pilot TV", "telefon odrzucił instalację")]
    assert (p.apps_installed, p.apps_total) == (2, 4)


def test_unknown_error_code_falls_back(journal):
    rows = [_row("Dziwna", "failed", "cosmic_ray")]
    p = build_transfer_protocol(journal, _order(journal, _result(rows)).id, "pl", NOW)
    assert p.apps_problems == [("Dziwna", "błąd instalacji (cosmic_ray)")]


def test_copy_deleted_protocol_still_builds(journal):
    order = _order(journal, _result())
    journal.mark_copy_deleted(COPY, datetime(2026, 11, 10, 9, 0))
    p = build_transfer_protocol(journal, order.id, "pl", NOW)
    assert p.copy_deleted.isoformat() == "2026-11-10" and p.copy_until is None
    assert "została usunięta" in _html(p)


def test_failed_restore_is_bad_and_marks_missing(journal):
    result = {"files": _files(), "tel": None, "apps": None, "status": "failed", "finished_at": None}
    order = _order(journal, result, status="failed")
    p = build_transfer_protocol(journal, order.id, "pl", NOW)
    assert p.tone == "bad"
    sms = next(t for t in p.tiles if t.key == "sms")
    assert sms.state == "nie wgrano" and sms.tone == "bad"
    assert next(t for t in p.tiles if t.key == "photos").tone == "ok"


def test_no_result_at_all_is_bad(journal):
    order = _order(journal, None, status="expired", target=None)
    p = build_transfer_protocol(journal, order.id, "pl", NOW)
    assert p.tone == "bad" and p.target is None
    assert all(t.state == "nie wgrano" for t in p.tiles)
    assert "nie wgrano" in _html(p)


def test_partial_category_is_warn(journal):
    result = _result()
    result["files"]["groups"]["downloads"] = {"done": 311, "exists": 0, "skipped": 0, "failed": 0}
    result["files"]["apk_skipped"] = 1
    p = build_transfer_protocol(journal, _order(journal, result).id, "pl", NOW)
    tile = next(t for t in p.tiles if t.key == "downloads")
    assert tile.tone == "warn" and tile.count == "311 z 312"
    assert "szkodliwe" in tile.state and p.tone == "warn"
    assert "usunięto" not in _html(p)


def test_whatsapp_restored_drops_client_hint(journal):
    pending = build_transfer_protocol(journal, _order(journal, _result()).id, "pl", NOW)
    assert pending.whatsapp == "on_phone" and "Przywróć" in _html(pending)
    done = build_transfer_protocol(journal, _order(journal, _result(), whatsapp=True).id, "pl", NOW)
    assert done.whatsapp == "restored"
    html = _html(done)
    assert "Przywróć" not in html and "Czaty przywrócone" in html
    assert "Sklepu Play" in html and "zaloguj" in html.lower()


def test_many_apps_named_limit_and_escaping(journal):
    rows = [_row("<b>&x 🙂" if i == 0 else f"App{i:03d}", package=f"com.p{i}") for i in range(120)]
    p = build_transfer_protocol(journal, _order(journal, _result(rows)).id, "pl", NOW)
    assert len(p.apps_named) == APPS_NAMED == 8 and p.apps_more == 112
    html = _html(p)
    assert "&lt;b&gt;&amp;x" in html and "<b>&x" not in html


def test_no_client_duty_section(journal):
    html = _html(build_transfer_protocol(journal, _order(journal, _result()).id, "pl", NOW))
    assert "Do zrobienia z klientem" not in html and "usunięto" not in html.lower()
    assert "<svg" in html and "@page" in html


def test_imei_shown_serial_only_without_imei(journal):
    p = build_transfer_protocol(journal, _order(journal, _result()).id, "pl", NOW)
    html = _html(p)
    assert "351234567890123" in html and "SRCSER" not in html
    src = {**SOURCE, "imei": None}
    p2 = build_transfer_protocol(journal, _order(journal, _result(), source=src).id, "pl", NOW)
    assert "SRCSER" in _html(p2)


def test_english_protocol(journal):
    p = build_transfer_protocol(journal, _order(journal, _result()).id, "en", NOW)
    html = _html(p)
    assert "Data transfer report" in html and "Contacts" in html and "of 412" in html


def test_texts_keys_match():
    def shape(x):
        return {k: shape(v) for k, v in x.items()} if isinstance(x, dict) else None
    assert shape(TRANSFER_TEXTS["pl"]) == shape(TRANSFER_TEXTS["en"])


def test_issued_date_is_now(journal):
    order = _order(journal, _result())
    p = build_transfer_protocol(journal, order.id, "pl", NOW + timedelta(days=1))
    assert p.issued == NOW + timedelta(days=1) and p.received == datetime(2026, 11, 1, 10, 0)


def test_malicious_apps_line_shown_only_when_counted(journal):
    src = {**SOURCE, "counts": {**SOURCE["counts"], "apps_malicious": 3}}
    p = build_transfer_protocol(journal, _order(journal, _result(), source=src).id, "pl", NOW)
    assert p.apps_malicious_skipped == 3
    html = _html(p)
    assert "Pominięto 3 aplikacji ocenionych jako szkodliwe" in html and "usunięto" not in html.lower()
    zero = build_transfer_protocol(journal, _order(journal, _result()).id, "pl", NOW)
    assert zero.apps_malicious_skipped == 0 and "szkodliwe" not in _html(zero)


def test_suspicious_skips_are_not_called_harmful(journal):
    result = _result()
    result["files"]["groups"]["downloads"]["done"] = 311
    result["files"]["apk_suspicious_skipped"] = 1
    tile = next(t for t in build_transfer_protocol(journal, _order(journal, result).id, "pl", NOW).tiles
                if t.key == "downloads")
    assert "podejrzane" in tile.state and "szkodliwe" not in tile.state


def test_malicious_wording_not_used_when_files_failed(journal):
    result = _result()
    result["files"]["groups"]["downloads"] = {"done": 310, "exists": 0, "skipped": 0, "failed": 1}
    result["files"]["apk_skipped"] = 1
    tile = next(t for t in build_transfer_protocol(journal, _order(journal, result).id, "pl", NOW).tiles
                if t.key == "downloads")
    assert "szkodliwe" not in tile.state


def test_ok_headline_makes_no_overclaim(journal):
    p = build_transfer_protocol(journal, _order(journal, _result()).id, "pl", NOW)
    assert p.headline == "Dane przeniesione."


def test_done_order_with_missing_stage_is_bad(journal):
    result = _result(tel=None)
    p = build_transfer_protocol(journal, _order(journal, result).id, "pl", NOW)
    assert p.tone == "bad" and p.headline.startswith("Wgrywanie przerwane")


@pytest.mark.parametrize("field", ["tel_error", "apps_error"])
def test_stage_error_is_bad(journal, field):
    result = _result(status="failed", **{field: "restore_failed"})
    p = build_transfer_protocol(journal, _order(journal, result, status="failed").id, "pl", NOW)
    assert p.tone == "bad"
    done = _order(journal, _result(**{field: "x"}))  # nawet zapisany jako done: błąd etapu = bad
    assert build_transfer_protocol(journal, done.id, "pl", NOW).tone == "bad"


def test_unselected_category_has_no_tile(journal):
    src = {**SOURCE, "selection_groups": ["contacts_messages"]}
    p = build_transfer_protocol(journal, _order(journal, _result(), source=src).id, "pl", NOW)
    assert [t.key for t in p.tiles] == ["contacts", "sms", "calls"]
    src2 = {**SOURCE, "counts": {k: v for k, v in SOURCE["counts"].items() if k != "calls"}}
    p2 = build_transfer_protocol(journal, _order(journal, _result(), source=src2).id, "pl", NOW)
    assert "calls" not in [t.key for t in p2.tiles]
