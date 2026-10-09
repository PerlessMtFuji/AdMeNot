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

## Backend (Cloudflare Worker `admenot`)

Kod w `server/`: strona (`public/`), API (`src/index.ts`), migracje D1 (`migrations/`).
Adres: `https://admenot.e-wlodarski.workers.dev` (ten sam co `BASE_URL` w `src/admenot/net/client.py`).

Przed wdrożeniem: `npm test` i `npm run check` w `server/` oraz `pytest tests/test_site.py`.

    cd server
    npx wrangler login                                  # raz na komputer
    npx wrangler d1 migrations apply admenot --remote   # zawsze PRZED deploy
    npx wrangler deploy

Kolejność ma znaczenie: nowy kod nigdy nie trafia na stary schemat. Sprawdzenie po wdrożeniu:
`curl.exe -s <adres>/api/v1/health` → `{"ok":true,"db":true}` i `admenot selfcheck --online` → `OK      serwer`.
Polityka obiecuje brak ciasteczek: `curl.exe -sI <adres>/ | findstr /i set-cookie` → puste.

Przycisk pobierania na stronie: `data-released="false"` → `"true"` w `public/index.html`
i `public/pl/index.html` przy pierwszym publicznym wydaniu, potem `deploy`.
Przy przełączeniu na `"true"` najpierw popraw kontrast przycisku pobierania w trybie ciemnym
(biały tekst na `#8b93fb` to ok. 2,9:1 — ciemniejsze tło akcentu albo ciemny tekst), w tym samym commicie.
Zmiana treści polityki prywatności: obie wersje językowe i data wersji naraz.

## Klucz podpisu manifestu aktualizacji

- Tworzenie (raz): `.venv\Scripts\python scripts\publish_update.py keygen` — pyta o hasło dwa razy,
  zapisuje `%USERPROFILE%\.admenot\update-signing-key.pem` (inna ścieżka: `ADMENOT_SIGNING_KEY`)
  i wypisuje klucz publiczny do dopisania w `src/admenot/net/update_key.py`.
- **Kopia zapasowa obowiązkowa:** plik PEM i hasło osobno (np. menedżer haseł + nośnik offline).
  Bez klucza zainstalowane kopie nie dostaną już żadnej aktualizacji — betowców trzeba by prosić
  o ręczną instalację.
- Rotacja: dopisz nowy klucz publiczny do `PUBLIC_KEYS` (stary zostaje), wydaj wersję, a stary
  usuń dopiero w kolejnej. Wyciek klucza: wersja z samym nowym kluczem + prośba o ręczną aktualizację.

## Aktualizacje

Po wgraniu instalatora do GitHub Release `v<wersja>`:

1. Notatki: `notes-pl.txt`, `notes-en.txt` (krótko, dla serwisanta).
2. `.venv\Scripts\python scripts\publish_update.py release <wersja> --notes-pl notes-pl.txt --notes-en notes-en.txt`
   (opcjonalnie `--min <wersja> --reason-pl … --reason-en …`). Skrypt sprawdza, że SHA-256 pliku
   na GitHubie = lokalny `dist\release\…sha256`.
3. `git add server/public/updates/v1/manifest.json`, commit, `wrangler deploy` (z `server/`).
4. `admenot selfcheck --online` → `OK      aktualizacje — aktualna (<wersja>)` z nowej wersji
   i `dostępna <wersja>` z poprzedniej.

Wycofanie wersji (bez nowego release'u):
`publish_update.py retire --min <pierwsza dobra wersja> --reason-pl "…" --reason-en "…"`, commit,
`wrangler deploy`. Cache: do 5 minut (`server/public/_headers`).

## Raporty błędów

- Wdrożenie zmian w raportach: najpierw `npx wrangler d1 migrations apply admenot --remote`, potem `npx wrangler deploy` (z `server/`).
- Przegląd: `.venv\Scripts\python scripts\reports.py list --new`, szczegóły `show R-XXXXXX` (oznacza jako przejrzany).
- Usunięcie na prośbę (RODO): `reports.py delete R-XXXXXX`. Wszystkie raporty znikają same po 90 dniach.
- Próba lokalna: w `server/` `npx wrangler d1 migrations apply admenot --local` i `npx wrangler dev` (port 8787);
  program z `ADMENOT_API_URL=http://127.0.0.1:8787`; `reports.py list --local`.

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
9. [ ] Aktualizacja z programu (przed pierwszym publicznym wydaniem i po zmianach w aktualizacjach).
       Kopia `%LOCALAPPDATA%\AdMeNot` przed próbą (`Copy-Item -Recurse $env:LOCALAPPDATA\AdMeNot $env:TEMP\AdMeNot-backup`).
   - [ ] 9a. Klucz testowy: `$env:ADMENOT_SIGNING_KEY = "$env:TEMP\admenot-test-key.pem"`,
         `.venv\Scripts\python scripts\publish_update.py keygen`; wypisany klucz publiczny wpisz
         **tymczasowo** jako jedyny w `PUBLIC_KEYS` w `src/admenot/net/update_key.py` (bez commitu).
   - [ ] 9b. Dwa buildy z `--allow-dirty` (bez commitu): `__version__ = "0.9.90"`, build, instalacja
         `dist\release\AdMeNot-0.9.90-dirty-setup.exe`; potem `__version__ = "0.9.91"` i ten sam build.
         `publish_update.py` szuka nazwy bez `-dirty`: skopiuj `AdMeNot-0.9.91-dirty-setup.exe.sha256`
         jako `AdMeNot-0.9.91-setup.exe.sha256` w `dist\release` (usuń po próbie).
   - [ ] 9c. Serwer lokalny: skopiuj `AdMeNot-0.9.91-dirty-setup.exe` jako `AdMeNot-0.9.91-setup.exe` do
         `$env:TEMP\admenot-update-test`, w osobnym oknie
         `.venv\Scripts\python -m http.server 8788 --bind 127.0.0.1 --directory $env:TEMP\admenot-update-test`
         (nie 8787 — ten port zajmuje `wrangler dev`).
         W oknie z kluczem testowym: `$env:ADMENOT_API_URL = "http://127.0.0.1:8788"` (lokalny adres
         działa tylko z tą zmienną) i
         `publish_update.py release 0.9.91 --min 0.9.90 --notes-pl n-pl.txt --notes-en n-en.txt --download-base http://127.0.0.1:8788/`
         (bez `--min` pierwszy manifest ma `min_supported` = `latest` i 0.9.90 od razu dostaje czerwony baner).
         Skopiuj `server\public\updates\v1\manifest.json` do `$env:TEMP\admenot-update-test\updates\v1\`
         i usuń z repo (`Remove-Item -Recurse server\public\updates`) — manifest testowy nie trafia do commitu.
   - [ ] 9d. Ustaw `ADMENOT_API_URL` na `http://127.0.0.1:8788` (użytkownika albo w PowerShellu, z którego
         uruchamiasz program) i uruchom zainstalowane 0.9.90. Po ok. 10 s baner „Dostępna wersja 0.9.91”;
         Zainstaluj → pobieranie → instalator z paskiem → program wraca jako `AdMeNot 0.9.91 beta`
         z komunikatem „Zaktualizowano do 0.9.91”; dziennik i ustawienia zostały;
         `%LOCALAPPDATA%\AdMeNot\updates` jest pusty najpóźniej po kolejnym uruchomieniu.
   - [ ] 9e. Wycofanie: zainstaluj ręcznie `AdMeNot-0.9.90-dirty-setup.exe`, `publish_update.py retire --min 0.9.91 --reason-pl "Test" --reason-en "Test"`
         (z `ADMENOT_API_URL`) — `retire` czyta manifest z repo, więc najpierw skopiuj testowy manifest z
         `$env:TEMP\admenot-update-test\updates\v1\` z powrotem do `server\public\updates\v1\`; po `retire` skopiuj wynik
         do katalogu testowego i znów usuń `server\public\updates`. Uruchom program ponownie: czerwony baner,
         „Napraw” na telefonie otwiera okno instalacji zamiast zlecenia, cofanie starego zlecenia
         z Historii działa. Telefon tylko z listy modyfikowalnych (nigdy moto g54 ani Vivo).
   - [ ] 9f. Sprzątanie: usuń zmienną `ADMENOT_API_URL` (`[Environment]::SetEnvironmentVariable("ADMENOT_API_URL", $null, "User")`),
         `git checkout -- src/admenot/__init__.py src/admenot/net/update_key.py` i osobno
         `Remove-Item -Recurse -ErrorAction SilentlyContinue server\public\updates` (katalog jest nieśledzony),
         usuń klucz testowy (wyciek klucza prywatnego do repo wykrywa przebieg gitleaks, spec §2.3 / §11.5), przywróć `%LOCALAPPDATA%\AdMeNot` z kopii i zainstaluj właściwą wersję.
10. [ ] Raport błędu z buildu: `ADMENOT_CRASH_TEST=error` → „Wyślij raport” na karcie błędu, numer, raport widać
        w `reports.py list --local`; `ADMENOT_CRASH_TEST=fatal` → po ponownym starcie baner, wysyłka z ADB,
        `show` bez numeru seryjnego i nazwy konta. Bez `wrangler dev`: komunikat offline, raport czeka.
   - [ ] 10a. Po wdrożeniu raportów na produkcję (migracja `--remote` i `wrangler deploy`): jeden raport
         próbny na produkcję — `ADMENOT_CRASH_TEST=error` **bez** `ADMENOT_API_URL`, „Wyślij raport”, numer;
         `.venv\Scripts\python scripts\reports.py list --new` pokazuje ten numer; potem
         `.venv\Scripts\python scripts\reports.py delete <numer>`.
   - [ ] 10b. Czysta sesja: zwykła praca (skan, okno wyboru pliku, podgląd ekranu); przed zamknięciem
         zajrzyj do `%LOCALAPPDATA%\AdMeNot\crashes\fault.txt` — wolno w nim być tylko blokom
         `Windows fatal exception: code 0x8…` (obsłużone wyjątki COM, np. `0x8001010d` przy starcie okna;
         `recover` je pomija). Inny nagłówek zanotuj do filtra. Zakończ proces bez czystego zamknięcia
         (`Stop-Process -Name AdMeNot`) i uruchom ponownie → brak banera o błędzie.
