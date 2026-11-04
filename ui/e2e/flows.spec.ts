import { expect, type Page, test } from '@playwright/test';

async function scan(page: Page, scenario: string) {
  await page.goto(`/?scenario=${scenario}`);
  await expect(page.getByRole('heading', { name: 'Połączono' })).toBeVisible();
  await page.getByPlaceholder('np. Anna K.').fill('Anna K.');
  await page.getByRole('button', { name: 'Skanuj' }).click();
  await expect(page.getByRole('complementary', { name: 'Plan naprawy' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Analiza plików aplikacji/)).toBeHidden({ timeout: 15_000 });
}

test('adware: scan, confirm the plan, fix with the admin step, undo from history', async ({ page }) => {
  await scan(page, 'adware');
  await expect(page.getByRole('heading', { name: /wymaga(ją)? uwagi/ })).toBeVisible();
  await page.getByRole('button', { name: /Podsumowanie/ }).click();
  await expect(page.getByRole('region', { name: 'Plan naprawy' })).toBeVisible();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/· sprawdzone$/)).toHaveCount(2);
  await page.getByRole('button', { name: 'Protokół PDF' }).click();
  await expect(page.getByText(/Otwarto protokół/)).toBeVisible();
  await page.getByRole('button', { name: 'Cofnij całe zlecenie' }).click();
  await expect(page.getByText(/ZS\/2026\/0926\/01: cofnięte/).first()).toBeVisible({ timeout: 15_000 });
});

test('tryb ręczny: wyszukaj, zaznacz, przeanalizuj, napraw', async ({ page }) => {
  await scan(page, 'manual');
  await expect(page.getByRole('heading', { name: 'Wyszukaj aplikacje do usunięcia' })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Tryb widoku' })).toHaveCount(0);
  await page.getByRole('searchbox').fill('clean');
  await page.getByRole('checkbox', { name: /clean/ }).check();
  await page.getByRole('button', { name: /Przeanalizuj zaznaczone \(1\)/ }).click();
  await expect(page.getByRole('button', { name: 'Dlaczego?' })).toBeVisible({ timeout: 15_000 }); // karta z werdyktem
  await expect(page.getByRole('heading', { name: 'Nie wykryto oznak zagrożenia' })).toHaveCount(0);
  await page.getByRole('button', { name: /Podsumowanie \(1\)/ }).click();
  await expect(page.getByRole('region', { name: 'Plan naprawy' })).toBeVisible();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
});

test('clean phone has nothing to fix', async ({ page }) => {
  await scan(page, 'clean');
  await expect(page.getByRole('heading', { name: 'Nie wykryto oznak zagrożenia' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Podsumowanie (0)' })).toBeDisabled();
});

test('disconnect during the order, then finish it', async ({ page }) => {
  await scan(page, 'disconnect');
  await page.getByRole('button', { name: /Podsumowanie/ }).click();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByText(/Telefon odłączony w trakcie zlecenia/)).toBeVisible({ timeout: 15_000 });
  await page.getByRole('button', { name: 'Dokończ' }).first().click();
  await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
});

test('report scenario: PDF error falls back to HTML, service details saved', async ({ page }) => {
  await scan(page, 'report');
  await page.getByRole('button', { name: /Podsumowanie/ }).click();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
  const report = page.getByRole('button', { name: 'Protokół PDF' });
  await report.click();
  await expect(page.getByText(/Otwarto protokół/)).toBeVisible();
  await report.click();
  await expect(page.getByText(/otwarty w innym programie/)).toBeVisible();
  await page.getByRole('button', { name: 'Ustawienia' }).click();
  await page.getByLabel('Nazwa serwisu').fill('Serwis Ząb');
  await page.getByRole('button', { name: 'Zapisz dane serwisu' }).click();
  await expect(page.getByText(/Zapisano/)).toBeVisible();
});

test('unauthorized phone asks for the permission', async ({ page }) => {
  await page.goto('/?scenario=unauthorized');
  await expect(page.getByRole('heading', { name: 'Potwierdź na telefonie' })).toBeVisible();
});

test('expert mode and English', async ({ page }) => {
  await scan(page, 'adware');
  await page.getByRole('button', { name: 'Ekspert' }).click();
  await expect(page.getByRole('columnheader', { name: 'Aplikacja' })).toBeVisible();
  await page.getByRole('button', { name: 'Ustawienia' }).click();
  await page.getByRole('button', { name: 'English' }).click();
  await page.getByRole('button', { name: 'Back to the order' }).click();
  await expect(page.getByRole('button', { name: /^Summary \(/ })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'App' })).toBeVisible();
});

test('theme: explicit dark, then system follows Windows', async ({ page }) => {
  await page.goto('/?scenario=empty');
  await page.getByRole('button', { name: 'Ustawienia' }).click();
  await page.getByRole('button', { name: 'Ciemny' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('button', { name: 'System' }).click();
  await page.emulateMedia({ colorScheme: 'light' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.emulateMedia({ colorScheme: 'dark' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('expert table keeps every row reachable when the list is longer than the window', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 300 });
  await scan(page, 'adware');
  await page.getByRole('button', { name: 'Ekspert' }).click();
  await page.getByRole('button', { name: /^Bez uwag/ }).click();
  const table = page.getByRole('group', { name: 'Tabela aplikacji' });
  const rows = table.locator('tbody tr');
  expect(await rows.count()).toBeGreaterThan(3);
  const clipped = await table.evaluate((el) => el.scrollHeight - el.clientHeight);
  expect(clipped).toBe(0);
  await rows.last().scrollIntoViewIfNeeded();
  await expect(rows.last()).toBeInViewport();
});

test('find the ad source opens in the side panel and comes back to the plan', async ({ page }) => {
  await scan(page, 'adware');
  await page.getByRole('button', { name: 'Znajdź źródło reklamy' }).click();
  const panel = page.getByRole('complementary', { name: 'Znajdź źródło reklamy' });
  await panel.getByRole('button', { name: 'Kto to wyświetla?' }).click();
  await expect(panel.getByRole('status')).toBeVisible();
  const result = await panel.getByRole('status').innerText();
  await panel.getByRole('button', { name: 'Wróć' }).click();
  await expect(page.getByRole('complementary', { name: 'Plan naprawy' })).toBeVisible();
  // Wynik zostaje po powrocie do panelu (spec §4).
  await page.getByRole('button', { name: 'Znajdź źródło reklamy' }).click();
  await expect(panel.getByRole('status')).toHaveText(result);
});

test('repair cards keep their full height when the order is longer than the window', async ({ page }) => {
  await scan(page, 'adware');
  await page.getByRole('button', { name: /Podsumowanie/ }).click();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
  await page.setViewportSize({ width: 1280, height: 300 });
  const cards = page.getByRole('main').getByRole('article');
  expect(await cards.count()).toBeGreaterThan(0);
  for (const card of await cards.all()) {
    expect(await card.evaluate((el) => el.scrollHeight - el.clientHeight)).toBe(0);
  }
});

test('screen view and screenshots: start, stop, screenshot lands in the order strip', async ({ page }) => {
  await scan(page, 'report');
  const panel = page.getByRole('complementary', { name: 'Plan naprawy' });
  await panel.getByRole('button', { name: 'Podgląd ekranu' }).click();
  await expect(panel.getByRole('button', { name: 'Zamknij podgląd' })).toBeVisible();
  await panel.getByRole('button', { name: 'Zrzut ekranu' }).click();
  await expect(panel.getByText('1 zrzut do protokołu')).toBeVisible();
  await panel.getByRole('button', { name: 'Zamknij podgląd' }).click();
  await expect(panel.getByRole('button', { name: 'Podgląd ekranu' })).toBeVisible();
  await page.getByRole('button', { name: /Podsumowanie/ }).click();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
  const box = page.getByRole('checkbox', { name: 'w protokole' });
  await expect(box).toBeChecked();
  await expect(page.getByText('w protokole: 1/8')).toBeVisible();
  await box.uncheck();
  await expect(page.getByText('w protokole: 0/8')).toBeVisible();
});

test('pierwsze uruchomienie: ostrzeżenie i zgody', async ({ page }) => {
  await page.goto('/?scenario=adware&welcome=1');
  await expect(page.getByRole('heading', { name: 'Witaj w AdMeNot' })).toBeVisible();
  const start = page.getByRole('button', { name: 'Zaczynamy' });
  await expect(start).toBeDisabled();
  await page.getByLabel('Rozumiem i akceptuję').check();
  await page.getByLabel(/Wysyłaj anonimowe statystyki użycia/).check();
  await start.click();
  await expect(page.getByRole('heading', { name: 'Witaj w AdMeNot' })).toBeHidden();
  await expect(page.getByRole('heading', { name: 'Połączono' })).toBeVisible();
});
test('show the plan to the client: QR, code and consent go with the order', async ({ page }) => {
  await scan(page, 'adware');
  await page.getByRole('button', { name: /Podsumowanie/ }).click();
  await page.getByRole('button', { name: 'Pokaż klientowi' }).click();
  await expect(page.getByRole('img', { name: /Kod QR/ })).toBeVisible();
  // Atrapa udostępnia ten sam plan co podgląd: kod kontrolny z nagrania tests/fixtures/bridge/adware.json.
  await expect(page.getByText('8LEU', { exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: /zapoznał się/ }).check();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
});

test('phone state: tick a site, see it in the plan, Firefox waits for remote debugging', async ({ page }) => {
  await page.goto('/?scenario=adware&checks=populated');
  await expect(page.getByRole('heading', { name: 'Połączono' })).toBeVisible();
  await page.getByRole('button', { name: 'Skanuj' }).click();
  await expect(page.getByText(/Analiza plików aplikacji/)).toBeHidden({ timeout: 15_000 });
  await expect(page.getByRole('region', { name: 'Stan telefonu' })).toBeVisible();
  await expect(page.getByText(/Zdalne debugowanie przez USB/)).toBeVisible();
  const site = page.getByRole('switch', { name: 'Wycisz tanie-bilety.example' });
  await expect(site).not.toBeChecked();
  await site.check();
  await expect(page.getByRole('complementary', { name: 'Plan naprawy' }).getByText('tanie-bilety.example')).toBeVisible();
  await page.getByRole('button', { name: /Podsumowanie/ }).click();
  await expect(page.getByRole('list', { name: 'Ustawienia witryn (1)', exact: true })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Chrome', exact: true }).getByText('tanie-bilety.example')).toBeVisible();
});

test('phone state in English', async ({ page }) => {
  await page.goto('/?scenario=adware&checks=populated&lang=en');
  await page.getByRole('button', { name: 'Scan' }).click();
  await expect(page.getByRole('region', { name: 'Phone state' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('switch', { name: 'All sites in Samsung Internet' })).toBeVisible();
});

test('upload a copy: the new phone is offered the copy, the plan shows APK labels, the result is green', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.clock.setFixedTime(new Date('2026-09-26T15:00:00'));  // nagrana kopia jest świeża (< 24 h)
  await page.goto('/?scenario=transfer_restore');
  await page.getByRole('radio', { name: /R58W20NEW01/ }).dispatchEvent('click');  // radio jest sr-only pod kartą
  await expect(page.getByText(/Wgrać kopię z samsung SM-A145R \(Anna K\./)).toBeVisible();
  await page.getByRole('button', { name: 'Wgraj', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Co wgrać na nowy telefon?' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('pominięty jako szkodliwy')).toBeVisible();
  await expect(page.getByText('podejrzany — odznaczony')).toBeVisible();
  await page.getByRole('complementary', { name: 'Miejsce na nowym telefonie' }).getByRole('button', { name: /^Wgraj/ }).click();
  await expect(page.getByText('Pliki wgrane', { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('pominięto 1 plik oceniony jako szkodliwy')).toBeVisible();
  expect(errors).toEqual([]);
});

test('phone state: a site fix on an app from the plan runs as one row with the app level', async ({ page }) => {
  // Przeglądarka z poprawką witryny i własnym poziomem w jednym zleceniu: bez scalenia ekran wykonania pada.
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/?scenario=adware&checks=app_browser');
  await page.getByRole('button', { name: 'Skanuj' }).click();
  await expect(page.getByText(/Analiza plików aplikacji/)).toBeHidden({ timeout: 15_000 });
  await page.getByRole('switch', { name: 'Wycisz tanie-bilety.example' }).check();
  await page.getByRole('button', { name: /Podsumowanie/ }).click();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('wyłączona · sprawdzone')).toHaveCount(1);
  await expect(page.getByRole('complementary', { name: 'Zlecenie' }).getByText('com.wlive.forecast')).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('explorer: open, enter Camera, select a day, preview, Esc, back', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.clock.setFixedTime(new Date('2026-10-11T09:41:00'));
  await page.goto('/?scenario=explorer');
  await expect(page.getByRole('heading', { name: 'Połączono' })).toBeVisible();
  await page.getByRole('button', { name: 'Pliki' }).click();
  const places = page.getByRole('navigation', { name: 'Miejsca' });
  await expect(places).toBeVisible();
  // pamięć telefonu: sylwetka z „cieczą” i legenda
  await expect(page.getByRole('img', { name: /Zajęte \d+% pamięci telefonu/ })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Pamięć telefonu' }).getByText('Zdjęcia', { exact: true })).toBeVisible();
  // wejście w Aparat (z innego miejsca)
  await places.getByRole('button', { name: /Pobrane/ }).click();
  await expect(places.getByRole('button', { name: /Pobrane/ })).toHaveAttribute('aria-current', 'location');
  await places.getByRole('button', { name: /Aparat/ }).click();
  await expect(places.getByRole('button', { name: /Aparat/ })).toHaveAttribute('aria-current', 'location');
  const list = page.getByRole('listbox', { name: 'Pliki w folderze' });
  await expect(list.getByRole('option').first()).toBeVisible();
  // zaznaczenie dnia
  await page.getByRole('button', { name: /^Zaznacz pliki z dnia/ }).first().click();
  await expect(list.locator('[role="option"][aria-selected="true"]').first()).toBeVisible();
  await expect(page.getByText(/zaznaczon/i).first()).toBeVisible();
  // podgląd i Esc
  await list.getByRole('option').first().dblclick();
  const preview = page.getByRole('dialog', { name: /^Podgląd pliku/ });
  await expect(preview).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(preview).toBeHidden();
  // „Wróć” na ekran „Połącz”
  await page.getByRole('button', { name: 'Wróć' }).click();
  await expect(page.getByRole('heading', { name: 'Połączono' })).toBeVisible();
  expect(errors).toEqual([]);
});

test.describe('explorer folder zoom (motion on)', () => {
  test.use({ reducedMotion: 'no-preference' });

  test('entering a folder leaves a zooming snapshot of the old content that disappears afterwards', async ({ page }) => {
    await page.goto('/?scenario=explorer');
    await page.getByRole('button', { name: 'Pliki' }).click();
    const places = page.getByRole('navigation', { name: 'Miejsca' });
    await places.getByRole('button', { name: /Cała pamięć/ }).click();
    const list = page.getByRole('listbox', { name: 'Pliki w folderze' });
    await expect(list.getByRole('option', { name: /DCIM/ })).toBeVisible();
    await list.getByRole('option', { name: /DCIM/ }).dblclick();
    const ghost = page.locator('section[aria-label] > [inert]');
    await expect(ghost).toHaveCount(1);
    await expect(ghost).toHaveCount(0, { timeout: 3000 });
    await expect(page.getByRole('navigation', { name: 'Ścieżka' }).getByRole('button', { name: 'DCIM' })).toBeVisible();
  });
});
