import { expect, type Locator, type Page, test } from '@playwright/test';

// „Zaznacz wszystkie” w nagłówku grupy musi zawsze pokazywać stan wierszy. W Chromium kliknięcie
// z `preventDefault` przywraca stan pola po tym, jak Svelte już je zapisał (jsdom tego nie odtwarza).

async function scan(page: Page) {
  await page.goto('/?scenario=adware');
  await expect(page.getByRole('heading', { name: 'Połączono' })).toBeVisible();
  await page.getByPlaceholder('np. Anna K.').fill('Anna K.');
  await page.getByRole('button', { name: 'Skanuj' }).click();
  await expect(page.getByRole('complementary', { name: 'Plan naprawy' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Analiza plików aplikacji/)).toBeHidden({ timeout: 15_000 });
}

const header = (page: Page, group: string) =>
  page.getByRole('checkbox', { name: `Zaznacz wszystkie: ${group}` });
const indeterminate = (box: Locator) => box.evaluate((e) => (e as HTMLInputElement).indeterminate);
const rows = (page: Page, group: string) => page.getByRole('region', { name: group }).getByRole('article')
  .getByRole('checkbox');

async function expectState(box: Locator, state: 'all' | 'some' | 'none') {
  if (state === 'all') await expect(box).toBeChecked();
  else await expect(box).not.toBeChecked();
  await expect.poll(() => indeterminate(box)).toBe(state === 'some');
}

async function selectAllConfirmed(page: Page, box: Locator) {
  await box.click();
  const dialog = page.getByRole('dialog');
  if (await dialog.isVisible()) await dialog.getByRole('button', { name: /Potwierdź|Zastosuj/ }).click();
}

test('select all, clear with the header: the header is empty, also after a row goes on and off', async ({ page }) => {
  await scan(page);
  const box = header(page, 'Szkodliwe');
  const row = rows(page, 'Szkodliwe').first();
  if (!(await box.isChecked())) await selectAllConfirmed(page, box);
  await expectState(box, 'all');

  await box.click(); // odznaczenie nagłówkiem idzie od razu, bez dialogu
  await expect(row).not.toBeChecked();
  await expectState(box, 'none');

  await row.click();
  await expectState(box, 'all');
  await row.click();
  await expectState(box, 'none');
});

/** „Do sprawdzenia” z kilkoma aplikacjami: nagrany scenariusz ma w niej jedną, więc „Bez uwag” trafia tam. */
async function reviewGroup(page: Page): Promise<Locator> {
  await page.evaluate(() => {
    const { ctl } = (window as any).__admenot;
    const scan = ctl.state.scan;
    ctl.state.scan = { ...scan, apps: scan.apps.map((a: any) => (a.verdict === 'safe' ? { ...a, verdict: 'review' } : a)) };
    ctl.setGroupOpen('review', true);
  });
  const all = rows(page, 'Do sprawdzenia');
  await expect.poll(() => all.count()).toBeGreaterThan(1);
  return all;
}

test('select all without a dialog (silence only): the header is checked at once', async ({ page }) => {
  await scan(page);
  await page.evaluate(() => (window as any).__admenot.ctl.saveSettings({ select_level: 'silence' }));
  const all = await reviewGroup(page);
  const box = header(page, 'Do sprawdzenia');
  await expectState(box, 'none');
  await box.click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  for (let i = 0; i < (await all.count()); i++) await expect(all.nth(i)).toBeChecked();
  await expectState(box, 'all');
  await box.click();
  await expectState(box, 'none');
});

test('a group with several apps: some rows give the indeterminate header, none gives an empty one', async ({ page }) => {
  await scan(page);
  const group = 'Do sprawdzenia';
  const box = header(page, group);
  const all = await reviewGroup(page);

  if (await box.isChecked()) await box.click();
  await selectAllConfirmed(page, box);
  await expectState(box, 'all');
  await box.click();
  await expectState(box, 'none');

  await all.nth(0).click();
  await expectState(box, 'some');
  await all.nth(0).click();
  await expectState(box, 'none');

  await selectAllConfirmed(page, box);
  await expectState(box, 'all');
  for (let i = 0; i < (await all.count()); i++) await all.nth(i).click();
  await expectState(box, 'none');
});
