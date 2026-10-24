import base64
from dataclasses import replace
from datetime import datetime

import pytest

from admenot.engine.report.model import (
    AppRow,
    Consent,
    DeviceBlock,
    PhoneCheck,
    PhoneCheckRow,
    Protocol,
    Recommendation,
    ScanScope,
)
from admenot.engine.report.render import action_text, data_uri, render_html, scope_lines
from admenot.engine.report.texts import TEXTS
from admenot.engine.settings import ServiceInfo

GENERATED = datetime(2026, 9, 26, 14, 30)
FULL_SCOPE = ScanScope([], True, False, 72.0, 0)


def make_protocol(**changes) -> Protocol:
    fields = {
        "number": "ZS/2026/0926/01",
        "created_at": datetime(2026, 9, 26, 14, 5),
        "client_name": "Anna <b>Nowak</b> & Syn",
        "device": DeviceBlock("Samsung Galaxy A14", "SM-A145R", "14", "R58T00TEST",
                              "2026-07-01"),
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


def test_polish_protocol_has_every_section():
    html = render_html(make_protocol(), ServiceInfo(), GENERATED)
    for text in ("Protokół serwisowy", "ZS/2026/0926/01", "Przedmiot zlecenia",
                 "Samsung Galaxy A14", "SM-A145R", "R58T00TEST", "Klient", "26.09.2026",
                 "Aplikacja", "Problem", "Działanie", "Szkodliwa", "Usunięto",
                 "Do sprawdzenia, bez zmian (1)",
                 "Wyłączenie: nie powiodło się", "Ukryta aplikacja spoza Sklepu Play",
                 "✓ Aplikacje bez uwag: 37", "Zalecenia", "com.game",
                 "Instaluj aplikacje tylko ze Sklepu Play", "Podpis serwisanta",
                 "26.09.2026 14:30"):
        assert text in html, text
    assert '<html lang="pl">' in html and "size: A4" in html
    assert "data:image/svg+xml;base64," in html
    assert "<td>—</td>" in html  # com.old bez migawki problemów
    closing = html.split('<section class="closing">', 1)[1]  # podpis nie zostaje sam na stronie
    assert "Zalecenia" in closing and "Podpis serwisanta" in closing
    # Potwierdzenie odbioru i podpis klienta są w systemie serwisu (wydruk odbioru), nie tutaj.
    for absent in ("Brak zapisu skanu", "Zakres skanu", "ocena niepełna",
                   "Nie wykryto oznak zagrożenia", "Podpis klienta", "Klient potwierdza"):
        assert absent not in html, absent


def test_imei_replaces_the_serial_number():
    device = DeviceBlock("Samsung Galaxy A14", "SM-A145R", "14", "R58T00TEST", "2026-07-01",
                         "499001200000004")
    html = render_html(make_protocol(device=device), ServiceInfo(), GENERATED)
    assert "<dt>IMEI</dt>" in html and "499001200000004" in html
    assert "R58T00TEST" not in html and "Nr seryjny" not in html


def test_user_and_phone_text_is_escaped():
    html = render_html(make_protocol(),
                       ServiceInfo(name="Kowalski & <i>Syn</i>"), GENERATED)
    assert "Anna &lt;b&gt;Nowak&lt;/b&gt; &amp; Syn" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>" not in html
    assert "Kowalski &amp; &lt;i&gt;Syn&lt;/i&gt;" in html


def test_english_protocol():
    html = render_html(make_protocol(lang="en"), ServiceInfo(), GENERATED)
    for text in ("Service report", "Subject of the order", "Client", "2026-09-26",
                 "Application", "Action", "Malicious", "Removed", "For review, no change (1)",
                 "Disable: failed", "Recommendations", "Technician signature"):
        assert text in html, text
    assert '<html lang="en">' in html
    assert "Client signature" not in html and "Client confirms" not in html


def test_app_cell_has_icon_label_and_package_broken_at_dots():
    icon = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + bytes(8)).decode()
    rows = [AppRow("com.superbllc.torch.flashlight", "Flashlight", "safe", [], "silence", "done",
                   icon=icon),
            AppRow("com.game", None, "review", ["Reklamy"], None, "none",
                   icon="data:text/html;base64,PHNjcmlwdD4=")]
    html = render_html(make_protocol(rows=rows), ServiceInfo(), GENERATED)
    assert f'<img class="icon" src="{icon}" alt="">' in html
    assert "<b>Flashlight</b>" in html
    assert "com.<wbr>superbllc.<wbr>torch.<wbr>flashlight" in html  # łamanie tylko na kropkach
    assert "data:text/html" not in html  # ikona z dziennika to tylko rozpoznana bitmapa
    assert '<span class="icon initial">G</span><div><b>com.<wbr>game</b>' in html


def test_no_flagged_apps_says_no_signs_within_the_scope():
    rows = [AppRow("com.torch", "Latarka", "safe", [], "silence", "done")]
    html = render_html(make_protocol(rows=rows,
                                     recommendations=[Recommendation("general")]),
                       ServiceInfo(), GENERATED)
    assert "Nie wykryto oznak zagrożenia w zakresie wykonanego skanu." in html
    assert "Aplikacje bez uwag" not in html and "Wyciszono" in html
    assert "Brak istotnych sygnałów" not in html  # bez etykiety werdyktu przy aplikacji bez uwag


def test_zero_clean_apps_with_flagged_rows_shows_no_headline():
    rows = [AppRow("com.game", None, "review", ["Reklamy"], None, "none")]
    html = render_html(make_protocol(rows=rows, clean_count=0,
                                     recommendations=[Recommendation("review_left",
                                                                     {"apps": "com.game"}),
                                                      Recommendation("general")]),
                       ServiceInfo(), GENERATED)
    assert "bez uwag" not in html
    assert "Nie wykryto oznak zagrożenia" not in html  # są aplikacje z uwagami: nie „bez uwag”


def test_limited_scope_and_incomplete_rows():
    rows = [AppRow("com.game", None, "review", ["Reklamy"], None, "none", True,
                   ["usagestats", "apk"]),
            AppRow("com.torch", None, "safe", [], "silence", "done", True, [])]
    html = render_html(make_protocol(rows=rows, scope=ScanScope([10], True, True, 3.0, 2),
                                     recommendations=[Recommendation("incomplete_scan")]),
                       ServiceInfo(), GENERATED)
    for text in ("Zakres skanu", "inne profile użytkownika (10)", "statystyki z 3 h",
                 "Aplikacje bez uwag z oceną niepełną", ": 2.",
                 "ocena niepełna — brak danych: statystyki użycia, analiza pliku APK",
                 "Brak istotnych sygnałów (ocena niepełna)", "Skan nie objął wszystkiego"):
        assert text in html, text
    assert "✓ Aplikacje bez uwag: 37" in html  # są aplikacje z uwagami: licznik zostaje

    only_safe = render_html(make_protocol(rows=rows[1:],
                                          scope=ScanScope([], False, False, None, 0)),
                            ServiceInfo(), GENERATED)
    assert "Nie wykryto oznak zagrożenia w zakresie wykonanego skanu." in only_safe
    assert "Nie udało się odczytać listy profili" in only_safe


def test_full_scope_with_incomplete_table_row_still_shows_scope_and_warns():
    rows = [AppRow("com.game", None, "review", ["Reklamy"], None, "none", True, ["apk"])]
    html = render_html(make_protocol(rows=rows,
                                     recommendations=[Recommendation("incomplete_scan")]),
                       ServiceInfo(), GENERATED)
    assert "Zakres skanu" in html
    assert "Aplikacje w tabeli z oceną niepełną" in html
    assert ": 1." in html
    assert 'class="warn"' in html


def test_untouched_review_apps_are_a_compact_list():
    rows = [AppRow("com.torch", "Latarka", "safe", [], "silence", "done"),
            AppRow("com.sus", "Podejrzana app", "suspicious", ["Czyta powiadomienia"], None, "none"),
            AppRow("com.gap", "Z lukami", "review", ["Opis luki"], None, "none", True, ["apk"])]
    rows += [AppRow(f"com.ads{i}", f"Reklamy {i}", "review", [f"Opis reklam {i}"], None, "none")
             for i in range(5)]
    recs = [Recommendation("review_left_many", {"count": "7"}), Recommendation("general")]
    html = render_html(make_protocol(rows=rows, recommendations=recs),
                       ServiceInfo(), GENERATED)
    table, rest = html.split("</table>", 1)
    # Działania, nieruszone „Podejrzana” i ocena niepełna (lista braków) zostają pełnymi wierszami.
    for text in ("Latarka", "Czyta powiadomienia", "Opis luki", "ocena niepełna"):
        assert text in table, text
    assert "Reklamy 0" not in table
    # Nieruszone „Do sprawdzenia” z pełną oceną: sama nazwa i pakiet, bez opisów problemu.
    assert "Do sprawdzenia, bez zmian (5)" in rest
    assert TEXTS["pl"]["watch_note"] in rest  # czym jest „Do sprawdzenia” i co z tym zrobić
    assert all(f"Reklamy {i}" in rest for i in range(5))
    assert "Opis reklam" not in html
    assert "Aplikacje oznaczone wyżej (razem: 7): jeśli ich nie używasz" in rest


def test_only_compact_apps_still_have_no_table():
    rows = [AppRow("com.ads", "Reklamy", "review", ["Opis"], None, "none")]
    html = render_html(make_protocol(rows=rows), ServiceInfo(), GENERATED)
    assert "<table" not in html and "Do sprawdzenia, bez zmian (1)" in html
    assert TEXTS["pl"]["no_rows"] not in html


def test_scope_lines():
    t = TEXTS["en"]
    assert scope_lines(None, t) == [] and scope_lines(FULL_SCOPE, t) == []
    lines = scope_lines(ScanScope([10, 11], True, True, None, 0), t)
    assert lines == [t["scope"]["other_profiles"].format(ids="10, 11"),
                     t["scope"]["low_data_unknown"]]
    assert scope_lines(FULL_SCOPE, t, 2) == [t["scope"]["incomplete_rows"].format(count=2)]
    assert scope_lines(None, t, 2) == []


def test_silhouette_and_missing_scan():
    device = DeviceBlock("Samsung SM-A145R", "SM-A145R", None, "R58", None)
    html = render_html(make_protocol(device=device, has_scan=False, clean_count=None,
                                     client_name=None, scope=None),
                       ServiceInfo(), GENERATED)
    assert "data:image/svg+xml;base64," in html
    assert "Brak zapisu skanu" in html and "bez uwag" not in html
    assert "Nie wykryto oznak" not in html and "Zakres skanu" not in html


def test_service_header_with_and_without_logo(tmp_path):
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG....")
    html = render_html(make_protocol(),
                       ServiceInfo("Serwis Ząb", "ul. Długa 1", "600 000 000", logo), GENERATED)
    assert "Serwis Ząb" in html and "ul. Długa 1" in html and "600 000 000" in html
    assert "data:image/png;base64," in html

    html = render_html(make_protocol(), ServiceInfo(logo=tmp_path / "gone.png"), GENERATED)
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
    keys = {"unfinished", "review_left", "review_left_many", "incomplete_scan", "removed",
            "disabled", "old_patch", "general"}
    assert set(TEXTS["pl"]["recommendations"]) == keys


def test_screenshots_are_an_attachment_page(tmp_path):
    from admenot.engine.report.model import ProtocolShot

    jpg = tmp_path / "1.jpg"
    jpg.write_bytes(b"\xff\xd8jpeg")
    shot = ProtocolShot(jpg, datetime(2026, 9, 26, 14, 7),
                        {"foreground": {"package": "a", "name": "Cleaner <b>Pro</b>"},
                         "overlays": [], "black": False})
    html = render_html(make_protocol(screenshots=[shot]), ServiceInfo(), GENERATED)
    assert "Załącznik: zrzuty ekranu" in html
    assert 'class="shots"' in html and "data:image/jpeg;base64," in html
    assert "26.09.2026 14:07" in html
    assert "Na pierwszym planie: Cleaner &lt;b&gt;Pro&lt;/b&gt;" in html
    assert html.index('class="shots"') > html.index('class="closing"')


def test_no_screenshots_no_attachment():
    html = render_html(make_protocol(), ServiceInfo(), GENERATED)
    assert 'class="shots"' not in html and "Załącznik" not in html


def test_shot_texts_exist_in_both_languages():
    assert TEXTS["pl"]["shots_title"] == "Załącznik: zrzuty ekranu"
    assert TEXTS["en"]["shots_title"] == "Attachment: screenshots"


@pytest.mark.parametrize(("lang", "text"), [
    ("pl", "Zakres naprawy przedstawiono klientowi przed wykonaniem (kod K7F3, 14:32)."),
    ("en", "The scope of the repair was shown to the client before it was carried out (code K7F3, 14:32)."),
])
def test_consent_line(lang, text):
    p = replace(make_protocol(lang=lang),
                consent=Consent("K7F3", datetime(2026, 10, 11, 14, 32), datetime(2026, 10, 11, 14, 35)))
    assert text in render_html(p, ServiceInfo(), GENERATED)


def test_no_consent_no_line():
    html = render_html(make_protocol(lang="pl"), ServiceInfo(), GENERATED)
    assert "przedstawiono klientowi" not in html


def test_manual_protocol_has_note_and_no_clean_headline():
    rows = [AppRow("com.torch", "Latarka", "safe", [], "silence", "done")]
    html = render_html(make_protocol(rows=rows, clean_count=None, manual=True,
                                     recommendations=[Recommendation("general")]),
                       ServiceInfo(), GENERATED)
    assert TEXTS["pl"]["manual_note"] in html
    assert TEXTS["pl"]["no_signs"] not in html and "Aplikacje bez uwag" not in html


def test_protocol_without_manual_has_no_note():
    html = render_html(make_protocol(), ServiceInfo(), GENERATED)
    assert TEXTS["pl"]["manual_note"] not in html


def _phone_check(state="review", rows=None):
    rows = [PhoneCheckRow("Chrome", "a.pl", "active", "done"),
            PhoneCheckRow("Samsung Internet", None, "shared", "failed")] if rows is None else rows
    return PhoneCheck("site_notifications", state, rows)


def test_phone_section_lists_rows_with_results():
    html = render_html(make_protocol(phone_checks=[_phone_check()]), ServiceInfo(), GENERATED)
    for text in ("Stan telefonu", "Przeglądarka", "Witryna", "Stan przed naprawą", "Chrome", "a.pl",
                 "wysyła powiadomienia", "Wyłączono powiadomienia", "Samsung Internet",
                 "wszystkie witryny tej przeglądarki", "Nie powiodło się"):
        assert text in html, text
    en = render_html(make_protocol(lang="en", phone_checks=[_phone_check()]), ServiceInfo(), GENERATED)
    assert "Phone settings" in en and "Notifications turned off" in en and "Failed" in en


def test_no_checks_no_phone_section():
    html = render_html(make_protocol(), ServiceInfo(), GENERATED)
    assert "Stan telefonu" not in html


def test_phone_section_without_rows_says_ok_or_unreadable():
    ok = render_html(make_protocol(phone_checks=[_phone_check("ok", [])]), ServiceInfo(), GENERATED)
    assert TEXTS["pl"]["phone"]["empty"] in ok
    bad = render_html(make_protocol(phone_checks=[_phone_check("unrecognized", [])]),
                      ServiceInfo(), GENERATED)
    assert TEXTS["pl"]["phone"]["unrecognized"] in bad and TEXTS["pl"]["phone"]["empty"] not in bad


def test_unsupported_browser_row_says_not_checked():
    html = render_html(make_protocol(phone_checks=[_phone_check(rows=[PhoneCheckRow("Odd", None, "unsupported", "none")])]),
                       ServiceInfo(), GENERATED)
    assert "tej przeglądarki program nie umie sprawdzić" in html and "nie sprawdzono" in html
    assert "wszystkie witryny tej przeglądarki" not in html


def test_phone_text_is_escaped():
    check = _phone_check(rows=[PhoneCheckRow("Chrome", "<b>x</b>.pl", "allowed", "none")])
    html = render_html(make_protocol(phone_checks=[check]), ServiceInfo(), GENERATED)
    assert "<b>x</b>" not in html and "&lt;b&gt;x" in html
