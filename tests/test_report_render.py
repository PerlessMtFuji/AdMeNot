from datetime import datetime

import pytest

from demalware.engine.phones.provider import SILHOUETTE
from demalware.engine.report.model import (
    AppRow,
    DeviceBlock,
    Protocol,
    Recommendation,
    ScanScope,
)
from demalware.engine.report.render import action_text, data_uri, render_html, scope_lines
from demalware.engine.report.texts import TEXTS
from demalware.engine.settings import ServiceInfo

GENERATED = datetime(2026, 9, 26, 14, 30)
FULL_SCOPE = ScanScope([], True, False, 72.0, 0)


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "samsung-galaxy-a14.webp"
    path.write_bytes(b"RIFF\0\0\0\0WEBP")
    return path


def make_protocol(photo, **changes) -> Protocol:
    fields = {
        "number": "ZS/2026/0926/01",
        "created_at": datetime(2026, 9, 26, 14, 5),
        "client_name": "Anna <b>Nowak</b> & Syn",
        "device": DeviceBlock("Samsung Galaxy A14", "SM-A145R", "14", "R58T00TEST",
                              "2026-07-01", photo, "exact"),
        "rows": [
            AppRow("com.clean.pro.boost", "<script>alert(1)</script>", "malicious",
                   ["Ukryta aplikacja spoza Sklepu Play"], "remove", "done"),
            AppRow("com.game", None, "review", ["Reklamy"], None, "none"),
            AppRow("com.old", None, None, [], "disable", "failed"),
        ],
        "clean_count": 37,
        "recommendations": [Recommendation("review_left", {"apps": "com.game"}),
                            Recommendation("general")],
        "has_scan": True,
        "lang": "pl",
        "scope": FULL_SCOPE,
    }
    fields.update(changes)
    return Protocol(**fields)


def test_polish_protocol_has_every_section(photo):
    html = render_html(make_protocol(photo), ServiceInfo(), GENERATED)
    for text in ("Protokół serwisowy", "ZS/2026/0926/01", "Przedmiot zlecenia",
                 "Samsung Galaxy A14", "SM-A145R", "R58T00TEST", "Klient", "26.09.2026",
                 "Aplikacja", "Problem", "Działanie", "Szkodliwa", "Usunięto", "Bez zmian",
                 "Wyłączenie: nie powiodło się", "Ukryta aplikacja spoza Sklepu Play",
                 "✓ Aplikacje bez uwag: 37", "Zalecenia", "com.game",
                 "Instaluj aplikacje tylko ze Sklepu Play", "Podpis serwisanta",
                 "Podpis klienta", "Klient potwierdza ustąpienie objawów", "nie sprawdzono",
                 "26.09.2026 14:30"):
        assert text in html, text
    assert '<html lang="pl">' in html and "size: A4" in html
    assert "data:image/webp;base64," in html
    assert "<td>—</td>" in html  # com.old bez migawki problemów
    for absent in ("Brak zapisu skanu", "Zakres skanu", "ocena niepełna",
                   "Nie wykryto oznak zagrożenia"):
        assert absent not in html, absent


def test_user_and_phone_text_is_escaped(photo):
    html = render_html(make_protocol(photo),
                       ServiceInfo(name="Kowalski & <i>Syn</i>"), GENERATED)
    assert "Anna &lt;b&gt;Nowak&lt;/b&gt; &amp; Syn" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>" not in html
    assert "Kowalski &amp; &lt;i&gt;Syn&lt;/i&gt;" in html


def test_english_protocol(photo):
    html = render_html(make_protocol(photo, lang="en"), ServiceInfo(), GENERATED)
    for text in ("Service report", "Subject of the order", "Client", "2026-09-26",
                 "Application", "Action", "Malicious", "Removed", "No change",
                 "Disable: failed", "Recommendations", "Technician signature",
                 "Client signature", "Client confirms the symptoms are gone", "not checked"):
        assert text in html, text
    assert '<html lang="en">' in html


def test_no_flagged_apps_says_no_signs_within_the_scope(photo):
    rows = [AppRow("com.torch", "Latarka", "safe", [], "silence", "done")]
    html = render_html(make_protocol(photo, rows=rows,
                                     recommendations=[Recommendation("general")]),
                       ServiceInfo(), GENERATED)
    assert "Nie wykryto oznak zagrożenia w zakresie wykonanego skanu." in html
    assert "Aplikacje bez uwag" not in html and "Wyciszono" in html
    assert "Bezpieczna" not in html  # bez etykiety werdyktu przy aplikacji bez uwag


def test_zero_clean_apps_with_flagged_rows_shows_no_headline(photo):
    rows = [AppRow("com.game", None, "review", ["Reklamy"], None, "none")]
    html = render_html(make_protocol(photo, rows=rows, clean_count=0,
                                     recommendations=[Recommendation("review_left",
                                                                     {"apps": "com.game"}),
                                                      Recommendation("general")]),
                       ServiceInfo(), GENERATED)
    assert "bez uwag" not in html
    assert "Nie wykryto oznak zagrożenia" not in html  # są aplikacje z uwagami: nie „bez uwag”


def test_limited_scope_and_incomplete_rows(photo):
    rows = [AppRow("com.game", None, "review", ["Reklamy"], None, "none", True,
                   ["usagestats", "apk"]),
            AppRow("com.torch", None, "safe", [], "silence", "done", True, [])]
    html = render_html(make_protocol(photo, rows=rows, scope=ScanScope([10], True, True, 3.0, 2),
                                     recommendations=[Recommendation("incomplete_scan")]),
                       ServiceInfo(), GENERATED)
    for text in ("Zakres skanu", "inne profile użytkownika (10)", "statystyki z 3 h",
                 "Aplikacje bez uwag z oceną niepełną", ": 2.",
                 "ocena niepełna — brak danych: statystyki użycia, analiza pliku APK",
                 "Brak oznak (ocena niepełna)", "Skan nie objął wszystkiego"):
        assert text in html, text
    assert "✓ Aplikacje bez uwag: 37" in html  # są aplikacje z uwagami: licznik zostaje

    only_safe = render_html(make_protocol(photo, rows=rows[1:],
                                          scope=ScanScope([], False, False, None, 0)),
                            ServiceInfo(), GENERATED)
    assert "Nie wykryto oznak zagrożenia w zakresie wykonanego skanu." in only_safe
    assert "Nie udało się odczytać listy profili" in only_safe


def test_full_scope_with_incomplete_table_row_still_shows_scope_and_warns(photo):
    rows = [AppRow("com.game", None, "review", ["Reklamy"], None, "none", True, ["apk"])]
    html = render_html(make_protocol(photo, rows=rows,
                                     recommendations=[Recommendation("incomplete_scan")]),
                       ServiceInfo(), GENERATED)
    assert "Zakres skanu" in html
    assert "Aplikacje w tabeli z oceną niepełną" in html
    assert ": 1." in html
    assert 'class="warn"' in html


def test_scope_lines():
    t = TEXTS["en"]
    assert scope_lines(None, t) == [] and scope_lines(FULL_SCOPE, t) == []
    lines = scope_lines(ScanScope([10, 11], True, True, None, 0), t)
    assert lines == [t["scope"]["other_profiles"].format(ids="10, 11"),
                     t["scope"]["low_data_unknown"]]
    assert scope_lines(FULL_SCOPE, t, 2) == [t["scope"]["incomplete_rows"].format(count=2)]
    assert scope_lines(None, t, 2) == []


def test_silhouette_approximate_note_and_missing_scan(photo):
    device = DeviceBlock("Samsung SM-A145R", "SM-A145R", None, "R58", None, SILHOUETTE, "none")
    html = render_html(make_protocol(photo, device=device, has_scan=False, clean_count=None,
                                     client_name=None, scope=None),
                       ServiceInfo(), GENERATED)
    assert "data:image/svg+xml;base64," in html
    assert "Brak zapisu skanu" in html and "bez uwag" not in html
    assert "Nie wykryto oznak" not in html and "Zakres skanu" not in html
    assert "podobnego modelu" not in html

    approx = DeviceBlock("Samsung SM-A145R", "SM-A145R", "14", "R58", None, photo, "approximate")
    assert "podobnego modelu" in render_html(make_protocol(photo, device=approx),
                                             ServiceInfo(), GENERATED)


def test_service_header_with_and_without_logo(photo, tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG....")
    html = render_html(make_protocol(photo),
                       ServiceInfo("Serwis Ząb", "ul. Długa 1", "600 000 000", logo), GENERATED)
    assert "Serwis Ząb" in html and "ul. Długa 1" in html and "600 000 000" in html
    assert "data:image/png;base64," in html

    html = render_html(make_protocol(photo), ServiceInfo(logo=tmp_path / "gone.png"), GENERATED)
    assert 'class="logo"' not in html


def test_data_uri(tmp_path):
    svg = tmp_path / "a.SVG"
    svg.write_text("<svg/>", "utf-8")
    assert data_uri(svg) == "data:image/svg+xml;base64,PHN2Zy8+"
    assert data_uri(tmp_path / "missing.png") is None
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"GIF89a")
    assert data_uri(gif) is None


@pytest.mark.parametrize(("outcome", "level", "pl", "en"), [
    ("done", "silence", "Wyciszono", "Silenced"),
    ("done", "disable", "Wyłączono", "Disabled"),
    ("done", "remove", "Usunięto", "Removed"),
    ("still_active", "disable", "Wyłączenie: wykonano, ale aplikacja nadal działa",
     "Disable: done, but the app is still active"),
    ("interrupted", "remove", "Usunięcie: przerwano, nie dokończono",
     "Remove: interrupted, not finished"),
    ("undone", "silence", "Wyciszenie: cofnięto", "Silence: undone"),
    ("partially_undone", "disable", "Wyłączenie: częściowo cofnięto", "Disable: partially undone"),
    ("none", None, "Bez zmian", "No change"),
])
def test_action_text(outcome, level, pl, en):
    row = AppRow("com.x", None, None, [], level, outcome)
    assert action_text(row, TEXTS["pl"]) == pl
    assert action_text(row, TEXTS["en"]) == en


def _shape(value):
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return ["list", len(value)]
    return type(value).__name__


def test_both_languages_have_the_same_keys():
    assert _shape(TEXTS["pl"]) == _shape(TEXTS["en"])
    keys = {"unfinished", "review_left", "incomplete_scan", "removed", "disabled", "old_patch",
            "general"}
    assert set(TEXTS["pl"]["recommendations"]) == keys
