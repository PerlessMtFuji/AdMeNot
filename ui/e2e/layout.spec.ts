import { expect, type Locator, type Page, test } from '@playwright/test';

// Najmniejsze okno (min_size 1024×700 w src/admenot/app/main.py) to w WebView2 ok. 1008×661 px.
test.use({ viewport: { width: 1008, height: 661 } });

type Box = { x: number; y: number; width: number; height: number };

async function scan(page: Page) {
  await page.goto('/?scenario=adware');
  await page.getByPlaceholder('np. Anna K.').fill('Anna K.');
  await page.getByRole('button', { name: 'Skanuj' }).click();
  await expect(page.getByText(/Analiza APK w tle/)).toBeHidden({ timeout: 15_000 });
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
