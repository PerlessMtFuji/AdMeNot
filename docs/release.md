# Wydanie AdMeNot

## Przygotowanie (raz)

    .venv\Scripts\pip install -e ".[dev,gui,release]"

Inno Setup 6 w `C:\Program Files (x86)\Inno Setup 6\` (albo `--iscc`). Node.js 24 do UI.

## Przed wypchnięciem do publicznego repo

Oba skany na całej historii:

    gitleaks git -v --redact --report-path build\gitleaks.json .
    .venv\Scripts\python scripts\scan_history.py

gitleaks: brak znalezisk albo każde opisane w `.gitleaks.toml`. Skaner: `brak trafień`;
fałszywe alarmy trafiają do `scripts/scan_history_allow.txt` z uzasadnieniem. Skaner widzi
tylko to, co jest w commitach (nie drzewo robocze ani indeks), więc nowe nagranie z telefonu:
commit lokalnie, skan, a push dopiero przy `brak trafień`. Trafienie w nowym nagraniu — popraw
plik i przepisz lokalny commit (`git commit --amend`) przed pushem.

## Build

1. Podbij `__version__` w `src/admenot/__init__.py` i zatwierdź zmiany (build wymaga czystego drzewa).
2. Podłącz OPPO CPH2271 (debugowanie USB) i uruchom:

       .venv\Scripts\python scripts\build_release.py --device

   Bez telefonu: bez `--device` (podsumowanie mówi, że porównanie skanu pominięto).
   Opcjonalnie: `VT_API_KEY` (VirusTotal), `ADMENOT_SIGN_CMD` (podpis, `{file}` = ścieżka).
3. Wynik: `dist\release\AdMeNot-<wersja>-setup.exe`, `.sha256`, `-release-notes.md`.
   Podsumowanie kończy się `NIEPODPISANE — …`, dopóki nie ma certyfikatu.

## Lista kontrolna

Wynik każdego punktu wpisz w sekcji „Uwagi” notatek do wydania. Punkt, którego nie dało się
sprawdzić, zapisz wprost jako niesprawdzony.

1. [ ] Build z `--device` na OPPO: `selfcheck --device: skan z paczki = skan deweloperski`.
2. Instalacja:
   - [ ] 2a. Na tym komputerze (obowiązkowo): brak okna UAC, skrót w menu Start i na pulpicie,
         program w `%LOCALAPPDATA%\Programs\AdMeNot`, okno `AdMeNot <wersja> beta` się otwiera,
         `admenot-cli.exe selfcheck --online` → same `OK` (także `serwer` — TLS i proxy z paczki),
         w katalogu programu są `LICENSE.txt` i `THIRD_PARTY_NOTICES.txt`.
   - [ ] 2b. To samo na maszynie testowej (czysty Windows): przywróć punkt kontrolny, skopiuj
         instalator, zainstaluj i sprawdź jak w 2a. Można pominąć — wtedy zapisz to w „Uwagach”.

             Restore-VMCheckpoint -VMName AdMeNot-Test -Name "czysty Windows" -Confirm:$false

3. [ ] Podgląd ekranu (scrcpy) z wersji zainstalowanej w 2a. Sprawdza też, że adb z paczki sam
       uruchamia swój serwer (`selfcheck --device` w buildzie korzysta z działającego już serwera
       adb deweloperskiego) — przed testem zatrzymaj ten serwer (`adb kill-server` z Android SDK).
4. [ ] Aktualizacja w miejscu: zainstaluj wydanie, potem build z podbitą wersją testową
       (`--allow-dirty`) na wierzch. Dziennik i ustawienia zostają, adb z katalogu programu
       zamknięty przed kopiowaniem, w `_internal` nie ma plików z poprzedniej wersji.
5. [ ] Deinstalacja w maszynie testowej: „Nie” → `%LOCALAPPDATA%\AdMeNot` zostaje; ponowna
       instalacja; deinstalacja „Tak” → katalog danych znika. Na komputerze autora tylko „Nie”
       albo po kopii `%LOCALAPPDATA%\AdMeNot`.
6. [ ] Deinstalacja przy uruchomionym AdMeNot: prośba o zamknięcie; „Anuluj” przerywa deinstalację.
       `unins000.exe /VERYSILENT /SUPPRESSMSGBOXES` przy uruchomionym programie niczego nie usuwa
       (samo `/VERYSILENT` pokazuje prośbę o zamknięcie i czeka).
7. [ ] adb z Android SDK (jeśli jest) działa dalej po instalacji i deinstalacji.
8. [ ] Wynik VirusTotal w notatkach (albo „nie sprawdzono” z powodem).
