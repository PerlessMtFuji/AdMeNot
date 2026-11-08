from pathlib import Path

import pytest
from apphelpers import SlowApk, make_api
from conftest import SERIAL
from fakephone import make_cli_phone

from admenot.engine.journal.db import Journal
from admenot.engine.report.pdf import PdfError
from admenot.engine.settings import ServiceInfo, load_service

WLIVE = {"com.wlive.forecast": "disable"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))


@pytest.fixture
def edge(monkeypatch):
    calls = []

    def fake(html, pdf):
        calls.append((html, pdf))
        pdf.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr("admenot.engine.report.files.html_to_pdf", fake)
    return calls


def _executed(**kw):
    opened = []
    api, rec = make_api(make_cli_phone(), open_file=opened.append, **kw)
    api.start_scan(SERIAL, "Anna")
    api.execute(WLIVE, [])
    return api, rec, rec.of("exec:order")[0]["order"], opened


def test_report_writes_pdf_and_opens_it(edge, tmp_path):
    api, _, number, opened = _executed()
    r = api.report(number)
    reports = tmp_path / "data" / "AdMeNot" / "reports"
    stem = number.replace("/", "-")
    assert r == {"order": number, "html": str(reports / f"{stem}.html"),
                 "pdf": str(reports / f"{stem}.pdf"), "pdf_target": str(reports / f"{stem}.pdf"),
                 "error": None, "opened": str(reports / f"{stem}.pdf"), "open_skipped": False}
    assert opened == [reports / f"{stem}.pdf"] and len(edge) == 1
    assert "Anna" in (reports / f"{stem}.html").read_text("utf-8")


def test_pdf_goes_to_the_chosen_folder_and_survives_order_deletion(edge, tmp_path):
    api, _, number, opened = _executed()
    archive = tmp_path / "archiwum" / "protokoly"
    api.save_settings({"report_pdf_dir": str(archive)})
    stem = number.replace("/", "-")
    r = api.report(number)
    reports = tmp_path / "data" / "AdMeNot" / "reports"
    assert r["pdf"] == r["pdf_target"] == str(archive / f"{stem}.pdf")
    assert r["html"] == str(reports / f"{stem}.html")  # HTML roboczy zostaje w danych programu
    assert opened == [archive / f"{stem}.pdf"]
    assert api.delete_order(number) == {"deleted": number}
    assert (archive / f"{stem}.pdf").is_file()  # archiwum serwisu: program go nie sprząta
    assert not (reports / f"{stem}.html").exists()


def test_pdf_folder_setting_is_checked_before_saving(tmp_path):
    api, _ = make_api(make_cli_phone())
    reports = tmp_path / "data" / "AdMeNot" / "reports"
    for bad in ("protokoly", str(reports)):
        r = api.save_settings({"report_pdf_dir": bad})
        assert r["error"]["key"] == "bad_request" and r["error"]["message"] == "report_pdf_dir"
    assert api.get_settings()["report_pdf_dir"] is None


def test_unreachable_pdf_folder_falls_back_to_html(edge, tmp_path):
    api, _, number, opened = _executed()
    blocker = tmp_path / "plik"
    blocker.write_text("x", "utf-8")  # folder pod plikiem: mkdir zawsze się nie uda
    api.save_settings({"report_pdf_dir": str(blocker / "pdf")})
    r = api.report(number)
    assert r["pdf"] is None and r["error"] == "folder" and r["opened"] == r["html"]
    assert [str(p) for p in opened] == [r["html"]]
    assert r["pdf_target"] == str(blocker / "pdf" / f"{number.replace('/', '-')}.pdf")
    assert edge == []


def test_pdf_failure_opens_the_html(monkeypatch):
    def broken(html, pdf):
        raise PdfError("locked")

    monkeypatch.setattr("admenot.engine.report.files.html_to_pdf", broken)
    api, _, number, opened = _executed()
    r = api.report(number)
    assert r["pdf"] is None and r["error"] == "locked" and r["opened"] == r["html"]
    assert [str(p) for p in opened] == [r["html"]]


def test_report_is_saved_even_when_windows_cannot_open_it(edge, tmp_path):
    def no_viewer(path):
        raise OSError("No application is associated with the specified file")

    api, rec = make_api(make_cli_phone(), open_file=no_viewer)
    api.start_scan(SERIAL, "Anna")
    api.execute(WLIVE, [])
    r = api.report(rec.of("exec:order")[0]["order"])
    assert r["opened"] is None and r["error"] is None and r["open_skipped"] is False
    assert r["pdf"] and Path(r["pdf"]).is_file()


def test_report_errors(edge):
    api, _, number, _ = _executed()
    assert api.report("")["error"]["key"] == "bad_request"
    assert api.report("ZS/2000/0101/01")["error"]["key"] == "unknown_order"
    api._report_lock.acquire()
    try:
        assert api.report(number)["error"]["key"] == "busy"
    finally:
        api._report_lock.release()


def test_report_during_apk_analysis_does_not_stop_it(edge):
    slow = SlowApk()
    api, rec = make_api(make_cli_phone(), sync=False, apk=slow)
    api.start_scan(SERIAL, None)
    rec.wait_for("apk:progress")
    # zlecenie z poprzedniej sesji w dzienniku: protokół nie potrzebuje telefonu
    other, _, number, _ = _executed()
    assert other.report(number)["error"] is None
    assert api._jobs.current() is not None and api._jobs.current().kind == "apk"
    slow.release.set()
    rec.wait_for("apk:done")


def test_service_round_trip_and_logo(tmp_path):
    api, _ = make_api(make_cli_phone())
    empty = dict.fromkeys(("name", "address", "phone", "logo", "email", "nip", "website",
                           "technician", "footer"))
    assert api.service() == empty
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG....")
    r = api.save_service({"name": " Serwis Ząb ", "phone": "600 000 000", "logo": str(logo)})
    assert r == {**empty, "name": "Serwis Ząb", "phone": "600 000 000", "logo": str(logo.resolve())}
    assert load_service() == ServiceInfo("Serwis Ząb", None, "600 000 000", logo.resolve())
    assert api.save_service({"logo": None, "phone": ""})["logo"] is None
    assert load_service() == ServiceInfo("Serwis Ząb")
    assert api.save_service({"logo": str(tmp_path / "x.gif")})["error"]["key"] == "logo_missing"
    (tmp_path / "x.gif").write_bytes(b"GIF89a")
    assert api.save_service({"logo": str(tmp_path / "x.gif")})["error"]["key"] == "logo_type"
    assert api.save_service({"colour": "red"})["error"]["key"] == "bad_request"
    assert load_service() == ServiceInfo("Serwis Ząb")


def test_save_service_new_fields():
    api, _ = make_api(make_cli_phone())
    r = api.save_service({"email": " a@b.pl ", "nip": " 123 ", "website": "b.pl",
                          "technician": "Jan", "footer": " Linia 1\nLinia 2 \n"})
    assert (r["email"], r["nip"], r["website"], r["technician"], r["footer"]) == (
        "a@b.pl", "123", "b.pl", "Jan", "Linia 1\nLinia 2")
    assert api.save_service({"nip": ""})["nip"] is None  # pojedyncza zmiana zostawia resztę
    assert load_service().email == "a@b.pl" and load_service().footer == "Linia 1\nLinia 2"
    err = api.save_service({"footer": "x" * 501})["error"]
    assert err["key"] == "bad_request" and err["message"] == "footer"
    assert load_service().footer == "Linia 1\nLinia 2"


def test_report_not_opened_when_disabled(edge):
    api, _, number, opened = _executed()
    api.save_settings({"report_open": False})
    r = api.report(number)
    assert r["opened"] is None and opened == [] and r["pdf"]
    assert r["open_skipped"] is True  # UI: zwykła ścieżka, nie „nie udało się otworzyć”


def test_logo_that_disappeared_does_not_block_other_changes(tmp_path):
    api, _ = make_api(make_cli_phone())
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG....")
    stored = api.save_service({"name": "Serwis", "logo": str(logo)})["logo"]
    logo.unlink()
    # okno odsyła zapisaną ścieżkę razem ze zmianą telefonu
    r = api.save_service({"name": "Serwis", "phone": "600 000 000", "logo": stored})
    assert r["phone"] == "600 000 000" and r["logo"] == stored
    # nowo wybrany brakujący plik nadal jest błędem
    assert api.save_service({"logo": str(tmp_path / "inne.png")})["error"]["key"] == "logo_missing"


def test_pick_logo_without_a_window():
    api, _ = make_api(make_cli_phone())
    assert api.pick_logo() == {"path": None}
    api._attach(pick_folder=lambda: None, close=lambda: None, pick_file=lambda: "C:\\logo.png")
    assert api.pick_logo() == {"path": "C:\\logo.png"}


def test_report_for_transfer_order(edge, tmp_path):
    from datetime import datetime

    from admenot.engine.paths import journal_path

    api, _ = make_api(make_cli_phone())
    with Journal(journal_path()) as j:
        order = j.create_transfer_order(
            "SRC", "SM-A525F", "Marta", None, copy_id="SRC/c1",
            source={"manufacturer": "samsung", "model": "SM-A525F", "counts": {"contacts": 3},
                    "selection_groups": ["contacts_messages"]},
            received_at=datetime(2026, 11, 1, 10, 0), copy_expires=datetime(2026, 11, 15, 10, 0))
    r = api.report(order.number)
    reports = tmp_path / "data" / "AdMeNot" / "reports"
    stem = order.number.replace("/", "-")
    assert r["pdf"] == str(reports / f"{stem}.pdf") and r["error"] is None and len(edge) == 1
    html = (reports / f"{stem}.html").read_text("utf-8")
    assert "Protokół przeniesienia danych" in html and "Marta" in html
