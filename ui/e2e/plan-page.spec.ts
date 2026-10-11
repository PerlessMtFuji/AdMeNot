import { readFileSync } from 'node:fs';
import { deflateRawSync } from 'node:zlib';
import { expect, type Page, test } from '@playwright/test';

const root = new URL('../../server/public/', import.meta.url);
const vector = JSON.parse(readFileSync(new URL('../../tests/fixtures/share_vector.json', import.meta.url), 'utf-8'));

async function serve(page: Page) {
  await page.route('https://plan.test/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const file = path === '/plan' ? 'plan.html' : path.slice(1);
    const type = file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html';
    await route.fulfill({ body: readFileSync(new URL(file, root)), contentType: type });
  });
}

test('plan page renders the local vector safely', async ({ page }) => {
  await serve(page);
  await page.goto(`https://plan.test/plan#${vector.local_fragment}`);
  await expect(page.locator('li.app')).toHaveCount(4);
  await expect(page.getByText('<img src=x onerror=alert(1)>')).toBeVisible();
  await expect(page.locator('li.app img')).toHaveCount(0);
  await expect(page.getByText('7F3K')).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'pl');
  await expect(page.getByText(/powiadomienia trzeba wyłączyć ręcznie/)).toBeVisible();
  // Nazwy aplikacji bywają po arabsku albo hebrajsku: kierunek tekstu wg treści, nie strony.
  for (const name of await page.locator('li.app b').all()) await expect(name).toHaveAttribute('dir', 'auto');
});

test('apps are grouped by what happens to them, one description per group', async ({ page }) => {
  const payload = { v: 1, lang: 'pl', at: '2026-10-11T14:30', phone: 'Telefon', code: 'AB12', notif: 1, apps: [
    { n: 'Zegar', l: 'silence' }, { n: 'Aparat', l: 'remove' }, { n: 'Bateria', l: 'silence' },
    { n: 'Usługi', l: 'disable', b: 1 }, { n: 'Cleaner', l: 'remove' },
  ] };
  const fragment = 'l.' + deflateRawSync(JSON.stringify(payload)).toString('base64url');
  await serve(page);
  await page.goto(`https://plan.test/plan#${fragment}`);
  await expect(page.getByRole('heading', { level: 2 })).toHaveText(['Do usunięcia', 'Do wyciszenia', 'Bez zmian']);
  await expect(page.getByText('Zostaną usunięte razem ze swoimi danymi. Same aplikacje da się przywrócić.')).toHaveCount(1);
  await expect(page.locator('section.remove li b')).toHaveText(['Aparat', 'Cleaner']);
  await expect(page.locator('section.silence li b')).toHaveText(['Bateria', 'Zegar']);
  await expect(page.getByText('Nie zostanie zmieniona.')).toHaveCount(1);
});

test('a browser without deflate-raw is asked to update, not told the plan is unreadable', async ({ page }) => {
  await page.addInitScript(() => { delete (globalThis as { DecompressionStream?: unknown }).DecompressionStream; });
  await serve(page);
  await page.goto(`https://plan.test/plan#${vector.local_fragment}`);
  await expect(page.getByText(/Ta przeglądarka jest za stara/)).toBeVisible();
});
