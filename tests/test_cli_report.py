from datetime import datetime

import pytest
from fakephone import make_cli_phone
from phonedb import make_phone_assets

from admenot.cli.main import main
from admenot.engine.adb.fake import FakeAdb
from admenot.engine.journal.db import Journal
from admenot.engine.paths import journal_path
from admenot.engine.report.pdf import PdfError
from admenot.engine.settings import ServiceInfo, load_service


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ADMENOT_ASSETS", str(make_phone_assets(tmp_path / "phones")))
    return tmp_path


def no_phone() -> FakeAdb:
    return FakeAdb({}, host={})  # każde polecenie ADB kończy się błędem


def test_service_shows_hint_when_empty(capsys):
    assert main(["service"], host=no_phone()) == 0
    assert "admenot service --name" in capsys.readouterr().out


def test_service_sets_fields_and_logo(capsys, data_dir):
    logo = data_dir / "logo.png"
    logo.write_bytes(b"\x89PNG....")
    assert main(["service", "--name", "Serwis Ząb", "--phone", "600 000 000",
                 "--logo", str(logo)], host=no_phone()) == 0
    out = capsys.readouterr().out
    assert "Serwis: Serwis Ząb" in out and "Telefon: 600 000 000" in out and "Adres: —" in out
    assert load_service() == ServiceInfo("Serwis Ząb", None, "600 000 000", logo.resolve())

    assert main(["--lang", "en", "service", "--address", "Main St 1", "--phone", "",
                 "--clear-logo"], host=no_phone()) == 0
    assert "Address: Main St 1" in capsys.readouterr().out
    assert load_service() == ServiceInfo("Serwis Ząb", "Main St 1", None, None)


def test_service_rejects_bad_logo(capsys, data_dir):
    assert main(["service", "--logo", str(data_dir / "nie-ma.png")], host=no_phone()) == 2
    assert "Nie ma pliku" in capsys.readouterr().err
    assert load_service() == ServiceInfo()


class FakeEdge:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def __call__(self, html, pdf):
        self.calls.append((html, pdf))
        if self.error:
            raise PdfError(self.error)
        pdf.write_bytes(b"%PDF-1.4 fake")


@pytest.fixture
def edge(monkeypatch):
    fake = FakeEdge()
    monkeypatch.setattr("admenot.engine.report.files.html_to_pdf", fake)
    return fake


def fixed_order(capsys) -> str:
    phone = make_cli_phone()
    assert main(["fix", "--app", "com.wlive.forecast=disable", "--yes", "--client",
                 "Anna Nowak"], host=phone) == 0
    capsys.readouterr()
    with Journal(journal_path()) as j:
        (order,) = j.orders_for("R58T00TEST")
    return order.number


def test_report_after_fix_without_a_phone(capsys, edge, data_dir):
    number = fixed_order(capsys)
    phone = no_phone()
    assert main(["report", "--order", number], host=phone) == 0
    pdf = data_dir / "AdMeNot" / "reports" / f"{number.replace('/', '-')}.pdf"
    assert str(pdf) in capsys.readouterr().out
    assert pdf.read_bytes().startswith(b"%PDF") and edge.calls == [(pdf.with_suffix(".html"), pdf)]
    html = pdf.with_suffix(".html").read_text("utf-8")
    for text in (number, "Anna Nowak", "Galaxy A14", "com.<wbr>wlive.<wbr>forecast", "Wyłączono",
                 "com.<wbr>clean.<wbr>pro.<wbr>boost", "Szkodliwa", "Bez zmian",
                 "data:image/webp;base64,", "Podpis serwisanta"):
        assert text in html, text
    assert "Zakres skanu" not in html  # telefon z atrapy: pełny zakres (profil 0, dość danych)
    assert phone.calls == []


def test_report_html_only(capsys, edge, data_dir):
    number = fixed_order(capsys)
    assert main(["report", "--order", number, "--html"], host=no_phone()) == 0
    html = data_dir / "AdMeNot" / "reports" / f"{number.replace('/', '-')}.html"
    assert str(html) in capsys.readouterr().out and html.is_file()
    assert edge.calls == [] and not html.with_suffix(".pdf").exists()


def test_report_custom_path_in_english(capsys, edge, data_dir):
    number = fixed_order(capsys)
    out = data_dir / "nowy katalog" / "protokol.pdf"
    assert main(["--lang", "en", "report", "--order", number, "--out", str(out)],
                host=no_phone()) == 0
    assert out.is_file() and "Service report" in out.with_suffix(".html").read_text("utf-8")
    assert "Report saved" in capsys.readouterr().out


def test_report_includes_service_details(capsys, edge, data_dir):
    number = fixed_order(capsys)
    main(["service", "--name", "Serwis Ząb & Syn"], host=no_phone())
    main(["report", "--order", number], host=no_phone())
    html = next((data_dir / "AdMeNot" / "reports").glob("*.html")).read_text("utf-8")
    assert "Serwis Ząb &amp; Syn" in html


def test_report_unknown_order(capsys, edge):
    assert main(["report", "--order", "ZS/2000/0101/01"], host=no_phone()) == 2
    assert "Nie znaleziono zlecenia ZS/2000/0101/01" in capsys.readouterr().err
    assert edge.calls == []


@pytest.mark.parametrize(("key", "text"), [
    ("no_browser", "Microsoft Edge"),
    ("timeout", "zbyt długo"),
    ("failed", "Nie udało się utworzyć PDF"),
    ("locked", "otwarty w innym programie"),
])
def test_report_pdf_failure_keeps_html(capsys, monkeypatch, data_dir, key, text):
    number = fixed_order(capsys)
    monkeypatch.setattr("admenot.engine.report.files.html_to_pdf", FakeEdge(error=key))
    assert main(["report", "--order", number], host=no_phone()) == 6
    err = capsys.readouterr().err
    html = data_dir / "AdMeNot" / "reports" / f"{number.replace('/', '-')}.html"
    assert text in err and str(html) in err and html.is_file()


def test_report_for_order_from_before_plan_6(capsys, edge, data_dir):
    with Journal(journal_path(), now=lambda: datetime(2026, 9, 1, 10, 0)) as j:
        order = j.create_order("R58T00TEST", "SM-A145R", None)
        aid = j.add_action(order.id, "com.x", "remove",
                           {"kind": "force_stop", "package": "com.x", "params": {}}, "cmd")
        j.set_action_status(aid, "done")
    assert main(["report", "--order", order.number], host=no_phone()) == 0
    html = next((data_dir / "AdMeNot" / "reports").glob("*.html")).read_text("utf-8")
    assert "Brak zapisu skanu" in html and "Usunięto" in html and "<td>—</td>" in html
    assert "data:image/svg+xml;base64," in html
