"""Teksty PL/EN silnika: poziomy akcji, kroki, blokady, błędy, statusy, werdykty (spec §9.4).

Używają ich CLI i GUI; komunikaty samego CLI (pytania, podpowiedzi poleceń) zostają w CLI.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from admenot.engine.actions.errors import hint_key
from admenot.engine.browsers.known import browser_names, known_browsers
from admenot.engine.parsers.site_notifications import site_origin

TEXTS: dict[str, dict[str, dict[str, str]]] = {
    "pl": {
        "levels": {"silence": "WYCISZ", "disable": "WYŁĄCZ", "remove": "USUŃ", "fix": "Ustawienia witryn"},
        "steps": {
            "force_stop": "zatrzymanie aplikacji",
            "appop": "appops {op} → {mode}",
            "appop:POST_NOTIFICATION": "blokada powiadomień",
            "appop:SYSTEM_ALERT_WINDOW": "blokada okien nad innymi aplikacjami",
            "appop:USE_FULL_SCREEN_INTENT": "blokada powiadomień pełnoekranowych",
            "permission:0": "odebranie zgody na powiadomienia",
            "permission:1": "przywrócenie zgody na powiadomienia",
            "secure_list": "zmiana {key}",
            "secure_list:enabled_accessibility_services": "wyłączenie usługi ułatwień dostępu",
            "secure_list:enabled_notification_listeners": "odebranie dostępu do powiadomień",
            "home": "zmiana ekranu głównego na {component}",
            "enabled:0": "wyłączenie aplikacji",
            "enabled:1": "włączenie aplikacji",
            "backup": "kopia APK na komputerze",
            "installed:0": "odinstalowanie (użytkownik 0)",
            "installed:1": "przywrócenie aplikacji",
            "admin": "odebranie uprawnień administratora (na telefonie)",
            "channel": "Wyłączenie powiadomień: {site} ({browser})",
            "channel:all": "Wyłączenie powiadomień wszystkich witryn ({browser})",
            "site_permission": "Blokada powiadomień: {site} ({browser})",
        },
        "reasons": {
            "protected": "aplikacja chroniona (tryb ekspercki: --unlock {package})",
            "active_ime": "to aktywna klawiatura — najpierw wybierz inną klawiaturę na telefonie",
            "home_no_alternative": "to jedyny launcher — nie ma na co przełączyć ekranu głównego",
            "not_installed": "nie ma takiej aplikacji na telefonie",
            "unknown_level": "nieznany poziom (silence | disable | remove)",
            "context_unknown": "nie rozpoznano odpowiedzi telefonu ({detail}) — bez tego nie "
                               "wyłączam ani nie usuwam; możesz wyciszyć",
            "unknown_fix": "tej zmiany ustawień nie ma już w stanie telefonu ({detail}) — zrób nowy skan",
            "browser_removed": "to zlecenie wyłącza albo usuwa tę przeglądarkę — jej ustawień "
                               "witryn nie zmieniam osobno",
        },
        "warnings": {
            "home_not_switched": "ekran główny zostaje bez zmian (brak launchera systemowego)",
            "app_data_lost": "usunięcie kasuje dane aplikacji (konta, ustawienia, pliki) — "
                             "cofnięcie przywróci samą aplikację, bez danych",
        },
        "errors": {
            "device_admin": "aplikacja jest administratorem urządzenia i nie oddała uprawnień",
            "security": "telefon odmówił dostępu (SecurityException)",
            "security_miui": "telefon odmówił dostępu — w opcjach programisty włącz "
                             "„Debugowanie USB (ustawienia zabezpieczeń)”",
            "security_coloros": "telefon odmówił dostępu — w opcjach programisty włącz "
                                "„Wyłącz monitorowanie uprawnień”",
            "unsupported": "niedostępne w tej wersji Androida",
            "failed": "polecenie nie powiodło się",
            "unrecognized": "nierozpoznana odpowiedź telefonu — zmiany nie wysłano",
            "context_unknown": "nie rozpoznano stanu telefonu — nie wyłączam ani nie usuwam",
            "active_ime": "to teraz aktywna klawiatura — najpierw wybierz inną na telefonie",
            "home_active": "to nadal ekran główny (przełączenie się nie udało) — nie wyłączam",
            "backup_stale": "aplikacja zmieniła się od zrobienia kopii APK — zrób nowy plan",
            "not_restored": "telefon przyjął polecenie, ale stan się nie zmienił — spróbuj ponownie",
            "device_busy": "inne okno albo CLI wykonuje teraz zlecenie na tym telefonie",
            "backup_failed": "nie udało się zrobić kopii APK — aplikacji nie usunięto",
            "no_backup": "brak kopii APK — nie da się przywrócić aplikacji",
            "skipped": "pominięto, bo poprzedni krok się nie udał",
            "not_started": "krok nie zdążył się zacząć",
            "app_gone": "aplikacji nie ma już na telefonie — nie ma czego cofać",
            "admin_timeout": "nie odebrano uprawnień administratora na czas",
            "user_timeout": "nie zmieniono ustawienia na telefonie na czas — powiadomienia "
                            "zostają włączone",
            "site_skipped": "pominięto — włączysz ją później z historii zlecenia",
            "site_timeout": "nie włączono na czas — włączysz ją później z historii zlecenia",
            "channel_gone": "przeglądarka usunęła ten kanał — włącz powiadomienia witryny ręcznie "
                            "w ustawieniach przeglądarki",
            "rdp_unavailable": "Firefox nie odpowiada na zdalne debugowanie — włącz je w Firefoksie "
                               "(Ustawienia → Zdalne debugowanie przez USB) i spróbuj w nowym planie",
            "rdp_failed": "Firefox odpowiedział w nieoczekiwany sposób — ustawienia witryny nie zmieniono",
            "browser_removed": "przeglądarka jest w tym zleceniu wyłączana albo usuwana",
            "unknown_fix": "tej zmiany ustawień nie ma już w stanie telefonu",
            "not_admin": "system odmówił, choć aplikacja nie jest administratorem",
            "disconnected": "telefon odłączony",
            "offline": "telefon offline",
            "unauthorized": "telefon nie jest autoryzowany",
            "adb_missing": "nie znaleziono adb",
            "timeout": "przekroczony limit czasu",
        },
        "order_status": {"running": "w toku", "done": "wykonane", "failed": "z błędami",
                         "undone": "cofnięte", "partially_undone": "częściowo cofnięte"},
        "action_status": {"pending": "oczekuje", "done": "wykonane", "failed": "błąd",
                          "undone": "cofnięte"},
    },
    "en": {
        "levels": {"silence": "SILENCE", "disable": "DISABLE", "remove": "REMOVE", "fix": "Site settings"},
        "steps": {
            "force_stop": "force-stop the app",
            "appop": "appops {op} → {mode}",
            "appop:POST_NOTIFICATION": "block notifications",
            "appop:SYSTEM_ALERT_WINDOW": "block drawing over other apps",
            "appop:USE_FULL_SCREEN_INTENT": "block full-screen notifications",
            "permission:0": "revoke notification permission",
            "permission:1": "restore notification permission",
            "secure_list": "change {key}",
            "secure_list:enabled_accessibility_services": "turn off accessibility service",
            "secure_list:enabled_notification_listeners": "revoke notification access",
            "home": "switch home screen to {component}",
            "enabled:0": "disable the app",
            "enabled:1": "enable the app",
            "backup": "APK backup on this computer",
            "installed:0": "uninstall (user 0)",
            "installed:1": "restore the app",
            "admin": "remove device admin rights (on the phone)",
            "channel": "Turning off notifications: {site} ({browser})",
            "channel:all": "Turning off notifications for all sites ({browser})",
            "site_permission": "Blocking notifications: {site} ({browser})",
        },
        "reasons": {
            "protected": "protected app (expert mode: --unlock {package})",
            "active_ime": "this is the active keyboard — pick another keyboard on the phone first",
            "home_no_alternative": "this is the only launcher — nothing to switch the home screen to",
            "not_installed": "no such app on the phone",
            "unknown_level": "unknown level (silence | disable | remove)",
            "context_unknown": "unrecognized phone response ({detail}) — not disabling or "
                               "removing without it; you can silence",
            "unknown_fix": "this settings change is no longer in the phone state ({detail}) — "
                           "scan again",
            "browser_removed": "this order disables or removes this browser — its site settings "
                               "are not changed separately",
        },
        "warnings": {
            "home_not_switched": "home screen stays as is (no system launcher)",
            "app_data_lost": "removal deletes the app's data (accounts, settings, files) — "
                             "undo restores the app itself, without its data",
        },
        "errors": {
            "device_admin": "the app is a device admin and kept its rights",
            "security": "the phone denied access (SecurityException)",
            "security_miui": "the phone denied access — enable “USB debugging (Security "
                             "settings)” in developer options",
            "security_coloros": "the phone denied access — enable “Disable permission "
                                "monitoring” in developer options",
            "unsupported": "not available on this Android version",
            "failed": "command failed",
            "unrecognized": "unrecognized phone response — nothing was sent",
            "context_unknown": "phone state not recognized — not disabling or removing",
            "active_ime": "this is now the active keyboard — pick another one on the phone first",
            "home_active": "this is still the home screen (switch failed) — not disabling",
            "backup_stale": "the app changed since the APK backup — make a new plan",
            "not_restored": "the phone accepted the command but the state did not change — retry",
            "device_busy": "another window or the CLI is running an order on this phone",
            "backup_failed": "APK backup failed — the app was not removed",
            "no_backup": "no APK backup — the app cannot be restored",
            "skipped": "skipped because a previous step failed",
            "not_started": "step had not started",
            "app_gone": "the app is no longer on the phone — nothing to undo",
            "admin_timeout": "device admin rights were not removed in time",
            "user_timeout": "the setting was not changed on the phone in time — notifications "
                            "stay on",
            "site_skipped": "skipped — turn it on later from the order history",
            "site_timeout": "not turned on in time — turn it on later from the order history",
            "channel_gone": "the browser removed this channel — turn the site's notifications on "
                            "manually in the browser settings",
            "rdp_unavailable": "Firefox does not answer remote debugging — turn it on in Firefox "
                               "(Settings → Remote debugging via USB) and try in a new plan",
            "rdp_failed": "Firefox answered unexpectedly — the site setting was not changed",
            "browser_removed": "the browser is disabled or removed in this order",
            "unknown_fix": "this settings change is no longer in the phone state",
            "not_admin": "the system refused although the app is not a device admin",
            "disconnected": "phone disconnected",
            "offline": "phone offline",
            "unauthorized": "phone not authorized",
            "adb_missing": "adb not found",
            "timeout": "timed out",
        },
        "order_status": {"running": "in progress", "done": "done", "failed": "with errors",
                         "undone": "undone", "partially_undone": "partially undone"},
        "action_status": {"pending": "pending", "done": "done", "failed": "failed",
                          "undone": "undone"},
    },
}

VERDICT_LABELS = {
    "pl": {"safe": "Brak istotnych sygnałów", "review": "Do sprawdzenia", "suspicious": "Podejrzana",
           "malicious": "Szkodliwa", "safe_incomplete": "Brak istotnych sygnałów (ocena niepełna)"},
    "en": {"safe": "No significant signals", "review": "Review", "suspicious": "Suspicious",
           "malicious": "Malicious", "safe_incomplete": "No significant signals (incomplete)"},
}

GAP_LABELS = {
    "pl": {"components": "komponenty (ikony, ekran główny, autostart)",
           "appops": "użycie uprawnień (appops)", "notifications": "aktywne powiadomienia",
           "usagestats": "statystyki użycia", "alarm": "wybudzenia (alarmy)",
           "device_policy": "administratorzy urządzenia", "roles": "domyślne aplikacje (role)",
           "secure_settings": "ułatwienia dostępu i dostęp do powiadomień",
           "packages": "szczegóły pakietu (wersja, uprawnienia)", "apk": "analiza pliku APK"},
    "en": {"components": "components (icons, home screen, autostart)",
           "appops": "permission use (appops)", "notifications": "active notifications",
           "usagestats": "usage statistics", "alarm": "wake-ups (alarms)",
           "device_policy": "device administrators", "roles": "default apps (roles)",
           "secure_settings": "accessibility and notification access",
           "packages": "package details (version, permissions)", "apk": "APK file analysis"},
}

SCOPE_LABELS = {
    "pl": {"not_analyzed": "Kod aplikacji nie był analizowany — ocena tylko z danych telefonu",
           "obfuscated": "Kod w dużej części zaciemniony — nazwy klas mówią o nim mało",
           "dynamic_code": "Aplikacja może ładować dodatkowy kod w trakcie działania — tego kodu nie badano",
           "code_undetermined": "Głęboka analiza nie ustaliła wszystkich ścieżek w kodzie (refleksja, limit analizy, kod w splitach albo przerwana analiza)"},
    "en": {"not_analyzed": "The app's code was not analyzed — assessment from phone data only",
           "obfuscated": "Code largely obfuscated — class names reveal little",
           "dynamic_code": "The app can load extra code at run time — that code was not examined",
           "code_undetermined": "Deep analysis could not settle every code path (reflection, analysis limit, code in splits or an interrupted analysis)"},
}

CAPABILITY_LABELS = {
    "pl": {"overlay": "Okna nad innymi aplikacjami", "accessibility": "Ułatwienia dostępu",
           "boot": "Start z telefonem", "hide_icon": "Ukrywanie ikony"},
    "en": {"overlay": "Windows over other apps", "accessibility": "Accessibility",
           "boot": "Start with the phone", "hide_icon": "Hiding the icon"},
}

CONFIDENCE_LABELS = {
    "pl": {"low": "niska — tylko cechy pakietu i przyznane uprawnienia",
           "medium": "średnia — zaobserwowane zachowanie",
           "high": "wysoka — potwierdzony wskaźnik lub zachowanie kilku rodzajów"},
    "en": {"low": "low — package traits and granted permissions only",
           "medium": "medium — observed behavior",
           "high": "high — confirmed indicator or several kinds of behavior"},
}


CLIENT_FIX_TEXTS = {
    "pl": {"channel": "Wyłączenie powiadomień witryny {site} w {browser}",
           "channel:all": "Wyłączenie powiadomień wszystkich witryn w {browser}",
           "site_permission": "Blokada powiadomień witryny {site} w {browser}"},
    "en": {"channel": "Turning off notifications from {site} in {browser}",
           "channel:all": "Turning off notifications from all sites in {browser}",
           "site_permission": "Blocking notifications from {site} in {browser}"},
}

MANUAL_UNDO = {
    "pl": {"channel": "Ustawienia → Aplikacje → {browser} → Powiadomienia → {site}",
           "channel:all": "Ustawienia → Aplikacje → {browser} → Powiadomienia"},
    "en": {"channel": "Settings → Apps → {browser} → Notifications → {site}",
           "channel:all": "Settings → Apps → {browser} → Notifications"},
}

SITE_RESUBSCRIBE = {
    "pl": "Powiadomienia wrócą, gdy strona zapisze się od nowa — otwórz ją na telefonie: {url}",
    "en": "Notifications come back once the site subscribes again — open it on the phone: {url}",
}


def site_resubscribe(url: str, lang: str) -> str:
    return SITE_RESUBSCRIBE[lang].format(url=url)


CHECK_STATE_LABELS = {
    "pl": {"ok": "W porządku", "review": "Do sprawdzenia", "unrecognized": "Nie udało się odczytać"},
    "en": {"ok": "OK", "review": "Review", "unrecognized": "Could not be read"},
}


def check_state_label(state: str, lang: str) -> str:
    return CHECK_STATE_LABELS[lang].get(state, state)


def capability_label(key: str, lang: str) -> str:
    return CAPABILITY_LABELS[lang].get(key, key)


def gap_label(key: str, lang: str) -> str:
    return GAP_LABELS[lang].get(key, key)


def scope_label(key: str, lang: str) -> str:
    return SCOPE_LABELS.get(lang, SCOPE_LABELS["pl"]).get(key, key)


def confidence_label(level: str, lang: str) -> str:
    return CONFIDENCE_LABELS[lang].get(level, level)


def browser_name(package: str, names: Mapping[str, str] | None = None) -> str:
    """Nazwa przeglądarki: tabela znanych, nazwy popularnych, potem nazwy ze skanu, na końcu sam pakiet.
    Nazwa ze skanu bywa samym pakietem (etykieta jeszcze nieodczytana), więc popularne mają pierwszeństwo."""
    known = known_browsers().get(package)
    if known:
        return known.name
    return browser_names().get(package) or (names or {}).get(package) or package


def _site_of(step: dict[str, Any]) -> tuple[str, str | None]:
    """(klucz tekstu, host witryny albo None dla wspólnego kanału przeglądarki)."""
    params = step.get("params") or {}
    if step["kind"] == "site_permission":
        return "site_permission", _host(str(params.get("origin") or ""))
    channel = str(params.get("channel_id") or "")
    browser = known_browsers().get(step["package"])
    if browser and channel == browser.shared_channel:
        return "channel:all", None
    origin = site_origin(channel)
    return "channel", _host(origin) if origin else channel


def _host(origin: str) -> str:
    return origin.split("://", 1)[-1]


def fix_step_texts(step: dict[str, Any], lang: str, names: Mapping[str, str] | None = None) -> dict[str, str | None]:
    """Teksty kroku poprawki witryny: etykieta, zdanie dla klienta i miejsce ręcznego cofnięcia."""
    key, site = _site_of(step)
    values = {"site": site or "", "browser": browser_name(step["package"], names)}
    return {"site": site, "label": TEXTS[lang]["steps"][key].format(**values),
            "client": CLIENT_FIX_TEXTS[lang][key].format(**values),
            # ścieżka ręczna, gdy cofanie nie znajdzie kanału (przeglądarka go usunęła)
            "manual_undo": (MANUAL_UNDO[lang][key].format(**values) if step["kind"] == "channel" else None)}


def step_label(step: dict[str, Any], lang: str, names: Mapping[str, str] | None = None) -> str:
    labels = TEXTS[lang]["steps"]
    kind, params = step["kind"], step.get("params") or {}
    if kind in ("channel", "site_permission"):
        return str(fix_step_texts(step, lang, names)["label"])
    if kind == "appop":
        template = labels.get(f"appop:{params['op']}", labels["appop"])
    elif kind == "secure_list":
        template = labels.get(f"secure_list:{params['key']}", labels["secure_list"])
    elif kind in ("permission", "enabled", "installed"):
        flag = params["granted"] if kind == "permission" else params[kind]
        template = labels[f"{kind}:{flag}"]
    else:
        template = labels[kind]
    return template.format(**params)


def error_text(key: str, lang: str, manufacturer: str = "") -> str:
    errors = TEXTS[lang]["errors"]
    return errors.get(hint_key(key, manufacturer), errors.get(key, key))


def level_label(level: str, lang: str) -> str:
    return TEXTS[lang]["levels"].get(level, level)


def verdict_label(verdict: str, lang: str) -> str:
    return VERDICT_LABELS[lang].get(verdict, verdict)


def reason_text(reason: str, lang: str, package: str, detail: str = "") -> str:
    return TEXTS[lang]["reasons"].get(reason, reason).format(package=package, detail=detail)


def warning_text(key: str, lang: str) -> str:
    return TEXTS[lang]["warnings"].get(key, key)


def order_status_label(status: str, lang: str) -> str:
    return TEXTS[lang]["order_status"].get(status, status)


SHOT_TEXTS = {
    "pl": {
        "foreground": "Na pierwszym planie: {name}",
        "overlays": "nakładki: {names}",
        "black": "czarny ekran — telefon uśpiony albo aplikacja chroni obraz",
        "unknown": "nie udało się ustalić, co było na ekranie",
    },
    "en": {
        "foreground": "In the foreground: {name}",
        "overlays": "overlays: {names}",
        "black": "black screen — the phone was asleep or the app protects its screen",
        "unknown": "could not tell what was on the screen",
    },
}


def screenshot_caption(context: dict[str, Any], lang: str) -> str:
    """Podpis zrzutu (Plan 6b §5.3) — ten sam w oknie i w protokole."""
    t = SHOT_TEXTS[lang]
    parts = []
    if foreground := context.get("foreground"):
        parts.append(t["foreground"].format(name=foreground["name"]))
    if overlays := context.get("overlays"):
        parts.append(t["overlays"].format(names=", ".join(o["name"] for o in overlays)))
    if context.get("black"):
        parts.append(t["black"])
    return " · ".join(parts) or t["unknown"]
