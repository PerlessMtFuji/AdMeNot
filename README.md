# DeMalware

Program na Windows, który po podłączeniu telefonu z Androidem (debugowanie USB) heurystycznie wykrywa aplikacje intruzywne (reklamy, spam powiadomień, nakładki, fałszywe launchery, administratorzy urządzenia), pozwala je wyciszyć, wyłączyć albo usunąć i cofnąć każdą zmianę.

Specyfikacja: `docs/superpowers/specs/2026-09-26-demalware-design.md`. Plany: `docs/superpowers/plans/`.

## Wymagania

- Windows 10/11 x64, Python 3.13, Node.js 24 (tylko do budowania UI)
- `adb.exe` (Android platform-tools) w `PATH` albo wskazany w ustawieniach
- Microsoft Edge WebView2 Runtime (wbudowany w Windows 11)

## Instalacja (środowisko deweloperskie)

    py -3.13 -m venv .venv
    .venv\Scripts\pip install -e ".[dev,gui]"
    python scripts\build_phone_db.py            # baza telefonów i zdjęcia (Plan 3)
    powershell -ExecutionPolicy Bypass -File scripts\build_ui.ps1

## Uruchomienie GUI

    .venv\Scripts\demalware gui

albo `.venv\Scripts\demalware-gui`. Okno wymaga zbudowanego UI (`src\demalware\app\web\`, poza gitem) — bez niego program podaje polecenie budowania.

Motyw (System / Jasny / Ciemny), język i tryb domyślny zmienia się w Ustawieniach; „System” podąża za motywem Windows.

Praca nad samym UI bez telefonu i bez Pythona (atrapa mostu odtwarza nagrane scenariusze):

    cd ui
    npm run dev          # http://localhost:5173/?scenario=adware|clean|disconnect|unauthorized|many|empty

## CLI

    demalware devices | device | scan [--apk] | capture | fix | undo | resume | history | cache | service | report | gui

- `service` — zapisuje dane serwisu (nazwa, adres, telefon, logo) do protokołu, np. `demalware service --name "…"`.
- `report` — tworzy protokół serwisowy (PDF i HTML) dla zlecenia z dziennika, np. `demalware report --order ZS/…`.

## Testy

    .venv\Scripts\python -m pytest
    .venv\Scripts\python -m ruff check src tests
    cd ui; npm test; npm run check; npm run e2e

Po zmianie mostu (`src/demalware/app/`) odśwież nagrania scenariuszy dla UI:

    .venv\Scripts\python scripts\record_bridge_fixtures.py

## Dane użytkownika

`%LOCALAPPDATA%\DeMalware\`: `settings.json`, `journal.db`, `backups\`, `logs\` (log sesji ADB i `app-*.log` z błędami okna), `phone_overrides.json`.

## Znane ograniczenia

- Porzucona analiza APK w tle (np. przez kliknięcie „Napraw” w jej trakcie) może jeszcze dokończyć do dwóch zaczętych, tylko-do-odczytu poleceń `adb pull` — nigdy nie dotykają dziennika, ale mogą pojawić się jako dodatkowe linie w konsoli ADB, już po starcie nowego zlecenia.
- Okno GUI, gdy jest otwarte, serwuje zbudowany UI z własnego lokalnego serwera statycznego na `127.0.0.1` (efemeryczny port; wywołania `js_api` nie idą przez HTTP) — patrz punkt 9 doprecyzowań w planie GUI.
