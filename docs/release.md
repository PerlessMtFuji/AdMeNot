# Wydanie AdMeNot

Spec: `docs/superpowers/specs/2026-10-04-release-build-design.md`.

## Przygotowanie (raz)

    .venv\Scripts\pip install -e ".[dev,gui,release]"

Inno Setup 6 w `C:\Program Files (x86)\Inno Setup 6\` (albo `--iscc`). Node.js 24 do UI.

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
2. [ ] Maszyna testowa (czysty Windows): przywróć punkt kontrolny, skopiuj instalator, zainstaluj.
       Brak okna UAC, skrót w menu Start i na pulpicie, program w `%LOCALAPPDATA%\Programs\AdMeNot`,
       okno `AdMeNot <wersja> beta` się otwiera, `admenot-cli.exe selfcheck` → same `OK`.

       Restore-VMCheckpoint -VMName AdMeNot-Test -Name "czysty Windows" -Confirm:$false

3. [ ] Podgląd ekranu (scrcpy) z zainstalowanej wersji na tym komputerze.
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
