import pytest
from apphelpers import SlowApk, make_api
from conftest import SERIAL
from fakephone import make_cli_phone

from demalware.engine.report.pdf import PdfError
from demalware.engine.settings import ServiceInfo, load_service

WLIVE = {"com.wlive.forecast": "disable"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("DEMALWARE_ASSETS", str(tmp_path / "no-assets"))


@pytest.fixture
def edge(monkeypatch):
    calls = []

    def fake(html, pdf):
        calls.append((html, pdf))
        pdf.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr("demalware.engine.report.files.html_to_pdf", fake)
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
    reports = tmp_path / "data" / "DeMalware" / "reports"
    stem = number.replace("/", "-")
    assert r == {"order": number, "html": str(reports / f"{stem}.html"),
                 "pdf": str(reports / f"{stem}.pdf"), "error": None,
                 "opened": str(reports / f"{stem}.pdf")}
    assert opened == [reports / f"{stem}.pdf"] and len(edge) == 1
    assert "Anna" in (reports / f"{stem}.html").read_text("utf-8")


def test_pdf_failure_opens_the_html(monkeypatch):
    def broken(html, pdf):
        raise PdfError("locked")

    monkeypatch.setattr("demalware.engine.report.files.html_to_pdf", broken)
    api, _, number, opened = _executed()
    r = api.report(number)
    assert r["pdf"] is None and r["error"] == "locked" and r["opened"] == r["html"]
    assert [str(p) for p in opened] == [r["html"]]


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
    assert api.service() == {"name": None, "address": None, "phone": None, "logo": None}
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG....")
    r = api.save_service({"name": " Serwis Ząb ", "phone": "600 000 000", "logo": str(logo)})
    assert r == {"name": "Serwis Ząb", "address": None, "phone": "600 000 000",
                 "logo": str(logo.resolve())}
    assert load_service() == ServiceInfo("Serwis Ząb", None, "600 000 000", logo.resolve())
    assert api.save_service({"logo": None, "phone": ""})["logo"] is None
    assert load_service() == ServiceInfo("Serwis Ząb")
    assert api.save_service({"logo": str(tmp_path / "x.gif")})["error"]["key"] == "logo_missing"
    (tmp_path / "x.gif").write_bytes(b"GIF89a")
    assert api.save_service({"logo": str(tmp_path / "x.gif")})["error"]["key"] == "logo_type"
    assert api.save_service({"colour": "red"})["error"]["key"] == "bad_request"
    assert load_service() == ServiceInfo("Serwis Ząb")


def test_pick_logo_without_a_window():
    api, _ = make_api(make_cli_phone())
    assert api.pick_logo() == {"path": None}
    api._attach(pick_folder=lambda: None, close=lambda: None, pick_file=lambda: "C:\\logo.png")
    assert api.pick_logo() == {"path": "C:\\logo.png"}
