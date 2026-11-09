"""Teksty protokołu serwisowego (spec §9.3, §9.4). Klucze PL i EN muszą być identyczne.

Etykiety werdyktów i braków danych są wspólne z CLI i GUI (`admenot.engine.texts`).
"""

from __future__ import annotations

from typing import Any

TEXTS: dict[str, dict[str, Any]] = {
    "pl": {
        "title": "Protokół serwisowy",
        "subject": "Przedmiot zlecenia",
        "model": "Kod modelu",
        "android": "Android",
        "serial": "Nr seryjny",
        "patch": "Poprawki zabezpieczeń",
        "client": "Klient",
        "date": "Data",
        "apps_title": "Aplikacje",
        "consent": "Zakres naprawy przedstawiono klientowi przed wykonaniem (kod {code}, {time}).",
        "shots_title": "Załącznik: zrzuty ekranu",
        "col_app": "Aplikacja",
        "col_problem": "Problem",
        "col_action": "Działanie",
        "no_rows": "Nie znaleziono aplikacji wymagających działań.",
        "watch_title": "Do sprawdzenia, bez zmian ({count})",
        "watch_note": "Te aplikacje mają cechy częste w aplikacjach z uciążliwymi reklamami "
                      "(np. wiele sieci reklamowych, pobieranie dodatkowego kodu), ale skan nie "
                      "wykazał, że szkodzą. Sprawdź, czy je znasz i używasz — jeśli nie, odinstaluj "
                      "je. Jeśli reklamy wrócą, zacznij od tej listy.",
        "no_scan": "Brak zapisu skanu dla tego zlecenia — kolumna „Problem” jest pusta.",
        "clean": "✓ Aplikacje bez uwag: {count}",
        "manual_note": "Aplikacje do naprawy wskazał serwisant; telefonu nie przeanalizowano w całości.",
        "no_signs": "Nie wykryto oznak zagrożenia w zakresie wykonanego skanu.",
        "incomplete": "ocena niepełna",
        "incomplete_gaps": "ocena niepełna — brak danych: {names}",
        "scope_title": "Zakres skanu",
        "scope": {
            "other_profiles": "Na telefonie są inne profile użytkownika ({ids}) — ich aplikacje "
                              "nie zostały sprawdzone.",
            "profiles_unknown": "Nie udało się odczytać listy profili użytkownika — sprawdzono "
                                "tylko profil główny; aplikacje z innych profili (np. służbowego) "
                                "mogły zostać pominięte.",
            "low_data": "Mało danych o zachowaniu aplikacji (statystyki z {hours} h lub niedawny "
                        "restart) — rzadko pojawiające się reklamy mogły nie zostać zauważone.",
            "low_data_unknown": "Mało danych o zachowaniu aplikacji (niedawny restart albo brak "
                                "statystyk użycia) — rzadko pojawiające się reklamy mogły nie "
                                "zostać zauważone.",
            "incomplete_apps": "Aplikacje bez uwag z oceną niepełną (części danych nie udało się "
                               "odczytać): {count}.",
            "incomplete_rows": "Aplikacje w tabeli z oceną niepełną (części danych nie udało się "
                               "odczytać): {count}.",
        },
        "levels": {"silence": "Wyciszenie", "disable": "Wyłączenie", "remove": "Usunięcie"},
        "outcomes": {
            "done": {"silence": "Wyciszono", "disable": "Wyłączono", "remove": "Usunięto"},
            "still_active": "{level}: wykonano, ale aplikacja nadal działa",
            "failed": "{level}: nie powiodło się",
            "interrupted": "{level}: przerwano, nie dokończono",
            "undone": "{level}: cofnięto",
            "partially_undone": "{level}: częściowo cofnięto",
            "none": "Bez zmian",
        },
        "phone_title": "Stan telefonu",
        "phone": {
            "note": "Powiadomienia z witryn w przeglądarkach — częste źródło reklam poza aplikacjami.",
            "col_browser": "Przeglądarka",
            "col_site": "Witryna",
            "col_state": "Stan przed naprawą",
            "col_result": "Wynik",
            "all_sites": "wszystkie witryny tej przeglądarki",
            "unreadable": "nie udało się odczytać",
            "unsupported": "tej przeglądarki program nie umie sprawdzić",
            "empty": "Nie znaleziono witryn z włączonymi powiadomieniami.",
            "unrecognized": "Nie udało się odczytać ustawień powiadomień — nie wiadomo, czy są "
                            "witryny z włączonymi powiadomieniami.",
            "before": {"active": "wysyła powiadomienia", "allowed": "ma zgodę na powiadomienia",
                       "shared": "powiadomienia witryn włączone", "unrecognized": "nieodczytane",
                       "unsupported": "nie sprawdzono"},
            "outcomes": {"done": "Wyłączono powiadomienia", "failed": "Nie powiodło się",
                         "interrupted": "Przerwano, nie dokończono", "undone": "Cofnięto",
                         "partially_undone": "Częściowo cofnięto", "none": "Bez zmian"},
        },
        "recommendations_title": "Zalecenia",
        "recommendations": {
            "unfinished": "Nie wszystko udało się naprawić: {apps}.",
            "review_left": "Na telefonie zostały aplikacje oznaczone do sprawdzenia: {apps}. "
                           "Jeśli ich nie używasz, odinstaluj je.",
            "review_left_many": "Aplikacje oznaczone wyżej (razem: {count}): jeśli ich nie "
                                "używasz, odinstaluj je.",
            "incomplete_scan": "Skan nie objął wszystkiego (patrz „Zakres skanu”). Jeśli reklamy "
                               "albo inne objawy wrócą, przynieś telefon ponownie — najlepiej "
                               "zaraz po ich wystąpieniu.",
            "removed": "Kopie usuniętych aplikacji są przechowywane w serwisie. "
                       "W razie potrzeby można je przywrócić.",
            "disabled": "Wyłączone aplikacje zostały na telefonie, ale nie działają. "
                        "Nie włączaj ich ponownie.",
            "old_patch": "Ostatnie poprawki zabezpieczeń pochodzą z {date}. "
                         "Sprawdź aktualizacje systemu w Ustawieniach.",
            "general": "Instaluj aplikacje tylko ze Sklepu Play. Nie pozwalaj nieznanym "
                       "aplikacjom wyświetlać się nad innymi aplikacjami ani wysyłać powiadomień.",
        },
        "nip": "NIP",
        "signature_service": "Podpis serwisanta",
        "generated": "Wygenerowano {date} programem AdMeNot",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M",
    },
    "en": {
        "title": "Service report",
        "subject": "Subject of the order",
        "model": "Model code",
        "android": "Android",
        "serial": "Serial no.",
        "patch": "Security patch",
        "client": "Client",
        "date": "Date",
        "apps_title": "Applications",
        "consent": "The scope of the repair was shown to the client before it was carried out (code {code}, {time}).",
        "shots_title": "Attachment: screenshots",
        "col_app": "Application",
        "col_problem": "Problem",
        "col_action": "Action",
        "no_rows": "No applications needed action.",
        "watch_title": "For review, no change ({count})",
        "watch_note": "These apps have traits common in apps with intrusive ads (e.g. many ad "
                      "networks, downloading extra code), but the scan did not show that they do "
                      "harm. Check whether you know and use them — if not, uninstall them. If ads "
                      "come back, start with this list.",
        "no_scan": "No scan record for this order — the “Problem” column is empty.",
        "clean": "✓ Apps with no issues: {count}",
        "manual_note": "The technician chose the apps to repair; the phone was not analysed in full.",
        "no_signs": "No signs of a threat within the scope of this scan.",
        "incomplete": "incomplete assessment",
        "incomplete_gaps": "incomplete assessment — missing data: {names}",
        "scope_title": "Scope of the scan",
        "scope": {
            "other_profiles": "The phone has other user profiles ({ids}) — their apps were not "
                              "checked.",
            "profiles_unknown": "Could not read the list of user profiles — only the main "
                                "profile was checked; apps in other profiles (e.g. a work "
                                "profile) may have been missed.",
            "low_data": "Little app behavior data ({hours} h of statistics or a recent reboot) — "
                        "ads that appear rarely may have gone unnoticed.",
            "low_data_unknown": "Little app behavior data (a recent reboot or no usage "
                                "statistics) — ads that appear rarely may have gone unnoticed.",
            "incomplete_apps": "Apps with no issues but an incomplete assessment (some data "
                               "could not be read): {count}.",
            "incomplete_rows": "Apps in the table with an incomplete assessment (some data "
                               "could not be read): {count}.",
        },
        "levels": {"silence": "Silence", "disable": "Disable", "remove": "Remove"},
        "outcomes": {
            "done": {"silence": "Silenced", "disable": "Disabled", "remove": "Removed"},
            "still_active": "{level}: done, but the app is still active",
            "failed": "{level}: failed",
            "interrupted": "{level}: interrupted, not finished",
            "undone": "{level}: undone",
            "partially_undone": "{level}: partially undone",
            "none": "No change",
        },
        "phone_title": "Phone settings",
        "phone": {
            "note": "Site notifications in browsers — a common source of ads outside apps.",
            "col_browser": "Browser",
            "col_site": "Site",
            "col_state": "State before repair",
            "col_result": "Result",
            "all_sites": "all sites of this browser",
            "unreadable": "could not be read",
            "unsupported": "this browser cannot be checked by the program",
            "empty": "No sites with notifications enabled were found.",
            "unrecognized": "Could not read the notification settings — it is not known whether "
                            "any sites have notifications enabled.",
            "before": {"active": "sends notifications", "allowed": "allowed to notify",
                       "shared": "site notifications enabled", "unrecognized": "unreadable",
                       "unsupported": "not checked"},
            "outcomes": {"done": "Notifications turned off", "failed": "Failed",
                         "interrupted": "Interrupted, not finished", "undone": "Undone",
                         "partially_undone": "Partially undone", "none": "No change"},
        },
        "recommendations_title": "Recommendations",
        "recommendations": {
            "unfinished": "Not everything could be fixed: {apps}.",
            "review_left": "Apps marked for review remain on the phone: {apps}. "
                           "If you do not use them, uninstall them.",
            "review_left_many": "Apps marked above ({count} in total): if you do not use them, "
                                "uninstall them.",
            "incomplete_scan": "The scan did not cover everything (see “Scope of the scan”). "
                               "If ads or other symptoms come back, bring the phone back — "
                               "ideally right after they appear.",
            "removed": "Copies of the removed apps are kept by the service "
                       "and can be restored if needed.",
            "disabled": "Disabled apps are still on the phone but do not run. "
                        "Do not enable them again.",
            "old_patch": "The latest security patch is from {date}. "
                         "Check for system updates in Settings.",
            "general": "Install apps only from the Play Store. Do not let unknown apps "
                       "display over other apps or send notifications.",
        },
        "nip": "VAT ID",
        "signature_service": "Technician signature",
        "generated": "Generated {date} by AdMeNot",
        "date_format": "%Y-%m-%d",
        "datetime_format": "%Y-%m-%d %H:%M",
    },
}


# Protokół przeniesienia danych (spec przenoszenia §6.2). Klucze PL i EN muszą być identyczne.
TRANSFER_TEXTS: dict[str, dict[str, Any]] = {
    "pl": {
        "title": "Protokół przeniesienia danych",
        "from_phone": "Z telefonu",
        "to_phone": "Na telefon",
        "no_target": "nie wskazano telefonu docelowego",
        "serial": "nr seryjny",
        "client": "Klient",
        "received": "Przyjęto",
        "issued": "Wydano",
        "data_title": "Dane",
        "apps_title": "Aplikacje",
        "installed_label": "zainstalowano",
        "of": "z",
        "tiles": {"contacts": "Kontakty", "sms": "SMS i MMS", "calls": "Połączenia",
                  "photos": "Zdjęcia i filmy", "downloads": "Pobrane i dokumenty",
                  "whatsapp": "WhatsApp", "others": "Inne foldery"},
        "state": {
            "all": "✓ wszystkie",
            "all_checked": "✓ każdy plik sprawdzony",
            "missing": "nie wgrano",
            "remaining": "{n} nie wgrano",
            "failed": "{n} nie wgrano z powodu błędu",
            "manual": "zapisane jako plik w Pobranych — do importu",
            "synced": "✓ {n} wróci z synchronizacją kont",
            "existed": "✓ już były na telefonie",
            "not_chosen": "nie wybrano do wgrania",
            "malicious": "pominięto jako szkodliwe: {n}",
            "suspicious": "pominięto jako podejrzane: {n}",
            "wa_restored": "✓ Czaty przywrócone",
            "wa_pending": "Kopia czatów na telefonie — czaty jeszcze nieprzywrócone",
        },
        "headline": {
            "done": "Dane przeniesione.",
            "warn_data": "Dane przeniesione. Część danych wymaga uwagi — szczegóły poniżej.",
            "apps_one": "{n} aplikacja nie została zainstalowana.",
            "apps_few": "{n} aplikacje nie zostały zainstalowane.",
            "apps_many": "{n} aplikacji nie zostało zainstalowanych.",
            "bad_none": "Dane nie zostały wgrane na nowy telefon.",
            "bad_partial": "Wgrywanie przerwane — przeniesiono część danych.",
        },
        "names_more": "i {n} innych",
        "problems_more": "…i {n} innych z problemem",
        "not_restored_apps": "Aplikacje nie zostały wgrane na nowy telefon.",
        "malicious_apps": "Pominięto {n} aplikacji ocenionych jako szkodliwe.",
        "reasons": {
            "user_restricted": "telefon zablokował instalację przez USB",
            "no_consent": "instalacja nie została zatwierdzona na telefonie",
            "too_old": "za stara dla tego Androida",
            "too_new": "wymaga nowszego Androida",
            "no_abi": "niezgodna z procesorem tego telefonu",
            "no_space": "brak miejsca na telefonie",
            "version_downgrade": "na telefonie jest nowsza wersja",
            "conflict": "konflikt z aplikacją na telefonie",
            "invalid_apk": "uszkodzony plik aplikacji",
            "disconnected": "telefon został odłączony",
            "failed": "telefon odrzucił instalację",
            "incomplete": "kopia aplikacji jest niekompletna",
            "pending": "instalacja nie została dokończona",
            "unknown": "błąd instalacji ({code})",
        },
        "cannot_title": "Czego nie da się przenieść przez USB",
        "cannot": ["Czaty RCS (przenosi je kopia Google)", "Dane i logowania w aplikacjach",
                   "Zdjęcia przypisane do kontaktów"],
        "info_title": "Informacje dla klienta",
        "info_login": "W aplikacjach zaloguj się ponownie.",
        "info_bank": "Aplikację banku, która nie działa, zainstaluj ze Sklepu Play.",
        "info_whatsapp": "WhatsApp: po zalogowaniu swoim numerem wybierz „Przywróć”.",
        "copy_until": "Kopia danych zostanie usunięta z komputera serwisu po {date}.",
        "copy_deleted": "Kopia danych została usunięta z komputera serwisu {date}.",
        "signature_service": "Podpis serwisu",
        "signature_client": "Podpis klienta (odbiór)",
        "generated": "Wygenerowano programem AdMeNot {version} · {date}",
        "date_format": "%d.%m.%Y",
        "datetime_format": "%d.%m.%Y %H:%M",
    },
    "en": {
        "title": "Data transfer report",
        "from_phone": "From phone",
        "to_phone": "To phone",
        "no_target": "no target phone recorded",
        "serial": "serial no.",
        "client": "Client",
        "received": "Received",
        "issued": "Issued",
        "data_title": "Data",
        "apps_title": "Applications",
        "installed_label": "installed",
        "of": "of",
        "tiles": {"contacts": "Contacts", "sms": "SMS and MMS", "calls": "Call history",
                  "photos": "Photos and videos", "downloads": "Downloads and documents",
                  "whatsapp": "WhatsApp", "others": "Other folders"},
        "state": {
            "all": "✓ all",
            "all_checked": "✓ every file verified",
            "missing": "not restored",
            "remaining": "{n} not restored",
            "failed": "{n} not restored because of an error",
            "manual": "saved as a file in Downloads — to be imported",
            "synced": "✓ {n} will return with account sync",
            "existed": "✓ already on the phone",
            "not_chosen": "not selected for restore",
            "malicious": "skipped as harmful: {n}",
            "suspicious": "skipped as suspicious: {n}",
            "wa_restored": "✓ Chats restored",
            "wa_pending": "Chat backup on the phone — chats not restored yet",
        },
        "headline": {
            "done": "Data transferred.",
            "warn_data": "Data transferred. Some data needs attention — details below.",
            "apps_one": "{n} app was not installed.",
            "apps_few": "{n} apps were not installed.",
            "apps_many": "{n} apps were not installed.",
            "bad_none": "The data was not restored to the new phone.",
            "bad_partial": "Restore interrupted — part of the data was transferred.",
        },
        "names_more": "and {n} more",
        "problems_more": "…and {n} more with a problem",
        "not_restored_apps": "The apps were not restored to the new phone.",
        "malicious_apps": "{n} apps assessed as harmful were skipped.",
        "reasons": {
            "user_restricted": "the phone blocked installation over USB",
            "no_consent": "installation was not approved on the phone",
            "too_old": "too old for this Android",
            "too_new": "needs a newer Android",
            "no_abi": "incompatible with this phone's processor",
            "no_space": "not enough space on the phone",
            "version_downgrade": "a newer version is on the phone",
            "conflict": "conflicts with an app on the phone",
            "invalid_apk": "damaged app file",
            "disconnected": "the phone was disconnected",
            "failed": "the phone rejected the installation",
            "incomplete": "the app copy is incomplete",
            "pending": "installation was not finished",
            "unknown": "installation error ({code})",
        },
        "cannot_title": "What cannot be moved over USB",
        "cannot": ["RCS chats (moved by Google backup)", "App data and logins",
                   "Photos attached to contacts"],
        "info_title": "Information for the client",
        "info_login": "Sign in to your apps again.",
        "info_bank": "If a banking app does not work, install it from the Play Store.",
        "info_whatsapp": "WhatsApp: after signing in with your number, choose “Restore”.",
        "copy_until": "The data copy will be deleted from the service computer after {date}.",
        "copy_deleted": "The data copy was deleted from the service computer on {date}.",
        "signature_service": "Service signature",
        "signature_client": "Client signature (pickup)",
        "generated": "Generated by AdMeNot {version} · {date}",
        "date_format": "%Y-%m-%d",
        "datetime_format": "%Y-%m-%d %H:%M",
    },
}
