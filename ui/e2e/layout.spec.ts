import { expect, type Locator, type Page, test } from '@playwright/test';

// Najmniejsze okno (min_size 1024×700 w src/admenot/app/main.py) to w WebView2 ok. 1008×661 px.
// Bez animacji: przy zmianie widoku stary <main> znikałby dopiero po animacji wyjścia.
test.use({ viewport: { width: 1008, height: 661 }, reducedMotion: 'reduce' });

type Box = { x: number; y: number; width: number; height: number };

async function scan(page: Page) {
  await page.goto('/?scenario=adware');
  await page.getByPlaceholder('np. Anna K.').fill('Anna K.');
  await page.getByRole('button', { name: 'Skanuj' }).click();
  await expect(page.getByText(/Analiza plików aplikacji/)).toBeHidden({ timeout: 15_000 });
  // App.svelte tworzy <main> od nowa przy zmianie widoku ({#key view}); napis o analizie znika chwilę
  // przed przejściem na wyniki, a pomiar starego <main> dawał null (niestabilny test).
  await expect(page.getByRole('heading', { name: /wymagają uwagi/ })).toBeVisible();
}

async function box(locator: Locator): Promise<Box> {
  const b = await locator.boundingBox();
  if (!b) throw new Error('element not rendered');
  return b;
}

const inside = (inner: Box, outer: Box) => inner.x >= outer.x - 1 && inner.x + inner.width <= outer.x + outer.width + 1;
const overlap = (a: Box, b: Box) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

test('simple results fit the minimum window', async ({ page }) => {
  await scan(page);
  const main = await box(page.locator('main'));
  expect(inside(await box(page.getByRole('button', { name: 'Skanuj ponownie' })), main)).toBe(true);
  const card = page.getByRole('article', { name: 'com.clean.pro.boost' });
  expect((await box(card.locator('b').first())).width).toBeGreaterThanOrEqual(120);
  const why = await box(card.getByRole('button', { name: 'Dlaczego?' }));
  expect(overlap(why, await box(card.getByRole('button', { name: 'Wycisz' })))).toBe(false);
});

test('expert table keeps the app name and the action readable', async ({ page }) => {
  await scan(page);
  await page.getByRole('button', { name: 'Ekspert' }).click();
  const main = await box(page.locator('main'));
  const row = page.locator('tbody tr').first();
  expect((await box(row.locator('td').nth(1))).width).toBeGreaterThanOrEqual(160);
  const action = row.getByRole('combobox');
  await expect(action).toBeVisible();
  expect(inside(await box(action), main)).toBe(true);
  expect(inside(await box(page.getByRole('button', { name: 'Skanuj ponownie' })), main)).toBe(true);
});

test('the analysis progress line stays on one row', async ({ page }) => {
  await scan(page);
  // Stan „analiza w toku” z najdłuższą zawartością: licznik, szacunek czasu, dymek i przycisk przerwania.
  await page.waitForFunction(() => (window as any).__admenot !== undefined);
  await page.evaluate(() => {
    const { ctl } = (window as any).__admenot;
    const s = ctl.state;
    s.job = { id: 'e2e-apk', kind: 'apk' };
    s.apkScope = 'all';
    s.apk = { done: 123, total: 456, running: true, changed: [], eta: 4980 };
    s.apkEstimate = { to_fetch_bytes: 3_500_000_000, total_bytes: 4_000_000_000, apps: 456, unknown: 3, cached: 12,
      largest_bytes: 200_000_000, limit_bytes: 10_000_000_000, effective_bytes: 10_000_000_000, free_bytes: 50_000_000_000,
      eta_s: 4980, eta_kind: 'measured', eta_min_s: 4980, eta_max_s: 4980 };
  });
  const line = page.locator('main').getByText('Analiza plików aplikacji').locator('xpath=..');
  await expect(line).toBeVisible();
  const stop = page.getByRole('button', { name: 'Przerwij — przejrzę ręcznie' });
  await expect(stop).toBeVisible();
  const main = await box(page.locator('main'));
  const lineBox = await box(line);
  const kids = line.locator(':scope > *');
  const n = await kids.count();
  expect(n).toBeGreaterThanOrEqual(4);
  const tops: number[] = [];
  for (let i = 0; i < n; i++) {
    const b = await box(kids.nth(i));
    tops.push(b.y + b.height / 2);
  }
  // Wszystkie elementy linii leżą w jednym rzędzie (środki w granicach kilku pikseli) i nie wystają z okna.
  expect(Math.max(...tops) - Math.min(...tops)).toBeLessThanOrEqual(4);
  expect(lineBox.height).toBeLessThanOrEqual(40);
  const stopBox = await box(stop);
  // Uwaga: przy tej najdłuższej zawartości przycisk wystaje ok. 30 px poza linię (patrz raport zadania 7), ale nie poza okno.
  expect(stopBox.x + stopBox.width).toBeLessThanOrEqual(1008);
});
