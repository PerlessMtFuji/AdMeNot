import { deflateRawSync } from 'node:zlib';
import { readFileSync } from 'node:fs';
import { expect, type Page, test } from '@playwright/test';

// Zrzuty ekranów do README.md (en) i README.pl.md (pl) na atrapie mostka. Uruchom po zmianach UI:
//   cd ui && npm run readme-shots
// Pliki: docs/img/<lang>/<ekran>.png (jasny motyw) i hero-dark.png (ciemny, dla <picture>).

const out = (lang: string, name: string) => `../docs/img/${lang}/${name}.png`;
const site = new URL('../../server/public/', import.meta.url);

const T = {
  pl: { scenario: 'adware', client: 'np. Anna K.', scan: 'Skanuj', apk: /Analiza APK w tle/, expert: 'Ekspert',
    simple: 'Prosty', why: 'Dlaczego?', technical: 'Szczegóły techniczne', source: 'Znajdź źródło reklamy',
    back: 'Wróć', console: 'Konsola ADB', summary: /Podsumowanie/, plan: 'Plan naprawy', share: 'Pokaż klientowi',
    run: /^Wykonaj/, done: 'Telefon naprawiony', history: 'Historia', historyTitle: 'Historia zleceń',
    ready: 'Połączono', phone: 'Samsung Galaxy A14' },
  en: { scenario: 'adware-en', client: 'e.g. Anna K.', scan: 'Scan', apk: /APK analysis in the background/,
    expert: 'Expert', simple: 'Simple', why: 'Why?', technical: 'Technical details', source: 'Find the ad source',
    back: 'Back', console: 'ADB console', summary: /Summary/, plan: 'Repair plan', share: 'Show the client',
    run: /^Run/, done: 'Phone fixed', history: 'History', historyTitle: 'Order history', ready: 'Connected',
    phone: 'Samsung Galaxy A14' },
} as const;

type Lang = keyof typeof T;

async function scan(page: Page, lang: Lang) {
  const t = T[lang];
  await page.goto(`/?scenario=${t.scenario}&lang=${lang}`);
  await page.getByPlaceholder(t.client).fill('Anna K.');
  await page.getByRole('button', { name: t.scan, exact: true }).click();
  await expect(page.getByText(t.apk)).toBeHidden({ timeout: 15_000 });
}

async function shot(page: Page, lang: Lang, name: string) {
  await page.waitForTimeout(150); // fonty i przejścia
  await page.screenshot({ path: out(lang, name) });
}

for (const lang of ['pl', 'en'] as const) {
  const t = T[lang];
  test.describe(`README ${lang}`, () => {
    test.use({ colorScheme: 'light', locale: lang === 'pl' ? 'pl-PL' : 'en-US' });
    test.beforeEach(async ({ page }) => { await page.clock.setFixedTime(new Date('2026-10-11T09:41:00')); });

    test('connect', async ({ page }) => {
      await page.goto(`/?scenario=${t.scenario}&lang=${lang}`);
      await expect(page.getByRole('heading', { name: t.ready })).toBeVisible();
      await shot(page, lang, 'connect');
    });

    test('results, details, diagnostics, console', async ({ page }) => {
      await scan(page, lang);
      await shot(page, lang, 'results-simple');
      await page.getByRole('button', { name: t.expert }).click();
      await shot(page, lang, 'results-expert');
      // Wyższe okno: punkty reguł mieszczą się w panelu bez przewijania.
      await page.setViewportSize({ width: 1280, height: 1040 });
      await page.getByText(t.technical, { exact: true }).click();
      await shot(page, lang, 'results-technical');
      await page.setViewportSize({ width: 1280, height: 800 });
      await page.getByRole('button', { name: t.source }).click();
      await shot(page, lang, 'diagnostics');
      await page.getByRole('button', { name: t.back }).click();
      await page.getByRole('button', { name: t.console }).click();
      await shot(page, lang, 'console');
    });

    test('plan, client QR, done, history', async ({ page }) => {
      await scan(page, lang);
      await page.getByRole('button', { name: t.summary }).click();
      await expect(page.getByRole('region', { name: t.plan })).toBeVisible();
      await page.getByRole('button', { name: t.share }).click();
      await expect(page.getByRole('img', { name: /QR/ })).toBeVisible();
      await shot(page, lang, 'share-qr');
      await page.getByRole('checkbox').last().check();
      await page.getByRole('button', { name: t.run }).click();
      await expect(page.getByRole('heading', { name: t.done })).toBeVisible({ timeout: 15_000 });
      await shot(page, lang, 'done');
      await page.getByRole('button', { name: t.history, exact: true }).click();
      await expect(page.getByRole('heading', { name: t.historyTitle })).toBeVisible();
      await shot(page, lang, 'history');
    });

    test('client plan page on the phone', async ({ page }) => {
      await page.setViewportSize({ width: 390, height: 780 });
      await page.route('https://plan.test/**', async (route) => {
        const path = new URL(route.request().url()).pathname;
        const file = path === '/plan' ? 'plan.html' : path.slice(1);
        const type = file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html';
        await route.fulfill({ body: readFileSync(new URL(file, site)), contentType: type });
      });
      const payload = { v: 1, lang, at: '2026-10-11T09:41', phone: t.phone, code: '8LEU', notif: 1, apps: [
        { n: 'Cleaner Pro', l: 'remove' }, { n: 'Weather Live', l: 'disable' },
      ] };
      const fragment = 'l.' + deflateRawSync(JSON.stringify(payload)).toString('base64url');
      await page.goto(`https://plan.test/plan#${fragment}`);
      await expect(page.getByText('8LEU')).toBeVisible();
      await shot(page, lang, 'client-plan');
    });
  });

  test.describe(`README ${lang} dark`, () => {
    test.use({ colorScheme: 'dark', locale: lang === 'pl' ? 'pl-PL' : 'en-US' });
    test.beforeEach(async ({ page }) => { await page.clock.setFixedTime(new Date('2026-10-11T09:41:00')); });

    test('hero', async ({ page }) => {
      await scan(page, lang);
      await page.getByRole('button', { name: t.expert }).click();
      await shot(page, lang, 'results-expert-dark');
    });
  });
}
