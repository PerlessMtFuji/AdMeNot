import { expect, type Page, test } from '@playwright/test';

async function scan(page: Page, scenario: string) {
  await page.goto(`/?scenario=${scenario}`);
  await expect(page.getByRole('heading', { name: 'Połączono' })).toBeVisible();
  await page.getByPlaceholder('np. Anna K.').fill('Anna K.');
  await page.getByRole('button', { name: 'Skanuj' }).click();
  await expect(page.getByRole('complementary', { name: 'Plan naprawy' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Analiza APK w tle/)).toBeHidden({ timeout: 15_000 });
}

test('adware: scan, confirm the plan, fix with the admin step, undo from history', async ({ page }) => {
  await scan(page, 'adware');
  await expect(page.getByRole('heading', { name: /wymaga(ją)? uwagi/ })).toBeVisible();
  await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
  await expect(page.getByRole('region', { name: 'Plan naprawy' })).toBeVisible();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/· sprawdzone$/)).toHaveCount(2);
  await page.getByRole('button', { name: 'Protokół PDF' }).click();
  await expect(page.getByText(/Otwarto protokół/)).toBeVisible();
  await page.getByRole('button', { name: 'Cofnij całe zlecenie' }).click();
  await expect(page.getByText(/ZS\/2026\/0926\/01: cofnięte/).first()).toBeVisible({ timeout: 15_000 });
});

test('clean phone has nothing to fix', async ({ page }) => {
  await scan(page, 'clean');
  await expect(page.getByRole('heading', { name: 'Nie wykryto oznak zagrożenia' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Napraw zaznaczone (0)' })).toBeDisabled();
});

test('disconnect during the order, then finish it', async ({ page }) => {
  await scan(page, 'disconnect');
  await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
  await page.getByRole('button', { name: /^Wykonaj/ }).click();
  await expect(page.getByText(/Telefon odłączony w trakcie zlecenia/)).toBeVisible({ timeout: 15_000 });
  await page.getByRole('button', { name: 'Dokończ' }).first().click();
  await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
});

test('report scenario: PDF error falls back to HTML, service details saved', async ({ page }) => {
  await scan(page, 'report');
  await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
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
  await expect(page.getByRole('button', { name: /^Fix \(/ })).toBeVisible();
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
  await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
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
  await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
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
