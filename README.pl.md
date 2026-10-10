# AdMeNot

[English](README.md) | **Polski**

Program na Windows, który po podłączeniu telefonu z Androidem (debugowanie USB) heurystycznie wykrywa aplikacje intruzywne (reklamy, spam powiadomień, nakładki, fałszywe launchery, administratorzy urządzenia), pozwala je wyciszyć, wyłączyć albo usunąć i cofnąć każdą zmianę.

## Wymagania

- Windows 10/11 x64, Python 3.13, Node.js 24 (tylko do budowania UI)
- `adb.exe` jest dołączany razem ze scrcpy (`scripts\fetch_tools.py`); inny adb można wskazać w ustawieniach
- Microsoft Edge WebView2 Runtime (wbudowany w Windows 11)

## Instalacja (środowisko deweloperskie)

    py -3.13 -m venv .venv
    .venv\Scripts\pip install -e ".[dev,gui,release]"
    python scripts\build_phone_db.py            # baza telefonów i zdjęcia
    python scripts\fetch_tools.py               # scrcpy 4.1 z adb (podgląd ekranu)
    powershell -ExecutionPolicy Bypass -File scripts\build_ui.ps1
    python scripts\build_icons.py               # tylko po zmianie assets\icon\*.svg (PNG, ICO, kopia dla UI)

## Uruchomienie GUI

    .venv\Scripts\admenot gui

albo `.venv\Scripts\admenot-gui`. Okno wymaga zbudowanego UI (`src\admenot\app\web\`, poza gitem) — bez niego program podaje polecenie budowania.

Motyw (System / Jasny / Ciemny), język i tryb domyślny zmienia się w Ustawieniach; „System” podąża za motywem Windows.

Praca nad samym UI bez telefonu i bez Pythona (atrapa mostu odtwarza nagrane scenariusze):

    cd ui
    npm run dev          # http://localhost:5173/?scenario=adware|clean|disconnect|unauthorized|many|empty

## CLI

    admenot devices | device | scan [--apk] | capture | fix | undo | resume | history | cache | service | report | screenshot | selfcheck | gui

- `service` — zapisuje dane serwisu (nazwa, adres, telefon, logo) do protokołu, np. `admenot service --name "…"`.
- `report` — tworzy protokół serwisowy (PDF i HTML) dla zlecenia z dziennika, np. `admenot report --order ZS/…`.
- `screenshot` — zrzut ekranu telefonu: `--order ZS/…` zapisuje go w zleceniu (trafia do protokołu), `--out plik.png` zapisuje sam plik.
- `selfcheck` — sprawdza, czy program ma wszystkie pliki (dane, narzędzia, UI); `--device --reference plik` porównuje skan telefonu z wynikiem `scan --apk --all`.

## Wydanie

    .venv\Scripts\python scripts\build_release.py [--device]

Daje `dist\release\AdMeNot-<wersja>-setup.exe` (instalacja per-user, bez uprawnień administratora). Numer wersji: tylko `src\admenot\__init__.py`. Pełna procedura i lista kontrolna: `docs/release.md`.

## Testy

    .venv\Scripts\python -m pytest
    .venv\Scripts\python -m ruff check src tests
    cd ui; npm test; npm run check; npm run e2e

Po zmianie mostu (`src/admenot/app/`) odśwież nagrania scenariuszy dla UI:

    .venv\Scripts\python scripts\record_bridge_fixtures.py

## Dane użytkownika

`%LOCALAPPDATA%\AdMeNot\`: `settings.json`, `journal.db`, `backups\`, `logs\` (log sesji ADB i `app-*.log` z błędami okna), `phone_overrides.json`.

## Znane ograniczenia

- Porzucona analiza APK w tle (np. przez kliknięcie „Napraw” w jej trakcie) może jeszcze dokończyć do dwóch zaczętych, tylko-do-odczytu poleceń `adb pull` — nigdy nie dotykają dziennika, ale mogą pojawić się jako dodatkowe linie w konsoli ADB, już po starcie nowego zlecenia.
- Okno GUI, gdy jest otwarte, serwuje zbudowany UI z własnego lokalnego serwera statycznego na `127.0.0.1` (efemeryczny port; wywołania `js_api` nie idą przez HTTP).

## Wsparcie

AdMeNot jest darmowy. Jeśli oszczędza Ci czas, możesz go dobrowolnie wesprzeć: <https://admenot.e-wlodarski.workers.dev/pl/donate>. Wsparcie niczego nie odblokowuje.

## Licencja

AdMeNot jest darmowy i udostępniony na licencji [PolyForm Shield 1.0.0](LICENSE). Możesz go używać, także zarobkowo — np. w serwisie przy naprawie telefonów klientów. Nie wolno sprzedawać programu ani na bazie tego kodu udostępniać produktu, który z nim konkuruje. To kod jawny (source-available), a nie open source w rozumieniu OSI. Licencje składników innych autorów są w `THIRD_PARTY_NOTICES.txt` w katalogu zainstalowanego programu.
