import { expect, type Page, test } from '@playwright/test';

async function scan(page: Page, scenario = 'adware') {
  await page.goto(`/?scenario=${scenario}`);
  await page.getByPlaceholder('np. Anna K.').fill('Anna K.');
  await page.getByRole('button', { name: 'Skanuj' }).click();
  await expect(page.getByText(/Analiza APK w tle/)).toBeHidden({ timeout: 15_000 });
}

async function inject(page: Page, fn: (env: any) => void) {
  await page.waitForFunction(() => (window as any).__admenot !== undefined);
  await page.evaluate(fn as never, undefined);
}

for (const theme of ['light', 'dark'] as const) {
  test.describe(`screens (PL, 1280×800, ${theme})`, () => {
    test.use({ colorScheme: theme });

    test('connect: waiting, permission, connected', async ({ page }) => {
      await page.goto('/?scenario=empty');
      await expect(page.getByRole('heading', { name: 'Podłącz telefon' })).toBeVisible();
      await expect(page).toHaveScreenshot(`connect-empty-${theme}.png`);
      await page.goto('/?scenario=unauthorized');
      await expect(page.getByRole('heading', { name: 'Potwierdź na telefonie' })).toBeVisible();
      await expect(page).toHaveScreenshot(`connect-unauthorized-${theme}.png`);
      await page.goto('/?scenario=adware');
      await expect(page.getByRole('heading', { name: 'Połączono' })).toBeVisible();
      await expect(page).toHaveScreenshot(`connect-ready-${theme}.png`);
    });

    test('scan', async ({ page }) => {
      await page.goto('/?scenario=adware');
      await inject(page, () => {
        const { ctl } = (window as any).__admenot;
        ctl.state.phase = 'scanning';
        ctl.state.scanStage = 'collectors';
      });
      await expect(page.getByRole('heading', { name: 'Skanuję telefon' })).toBeVisible();
      await expect(page).toHaveScreenshot(`scan-${theme}.png`);
    });

    test('results: simple, expert, console, plan confirmation', async ({ page }) => {
      await scan(page);
      await expect(page).toHaveScreenshot(`results-simple-${theme}.png`);
      await page.getByRole('button', { name: 'Ekspert' }).click();
      await expect(page).toHaveScreenshot(`results-expert-${theme}.png`);
      await page.getByRole('button', { name: 'Znajdź źródło reklamy' }).click();
      await expect(page).toHaveScreenshot(`results-diagnostics-${theme}.png`);
      await page.getByRole('button', { name: 'Wróć' }).click();
      await page.getByRole('button', { name: 'Konsola ADB' }).click();
      await expect(page).toHaveScreenshot(`results-console-${theme}.png`);
      await page.getByRole('button', { name: 'Konsola ADB' }).click();
      await page.getByRole('button', { name: 'Prosty' }).click();
      await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
      await expect(page.getByRole('region', { name: 'Plan naprawy' })).toBeVisible();
      await expect(page).toHaveScreenshot(`plan-confirm-${theme}.png`);
    });

    test('execute: admin prompt and done', async ({ page }) => {
      await page.goto('/?scenario=empty');
      await inject(page, () => {
        const { ctl, bridge } = (window as any).__admenot;
        ctl.state.phase = 'executing';
        ctl.state.order = 'ZS/2026/0926/01';
        bridge.emit('exec:step', { action_id: 1, package: 'com.clean.pro.boost', name: 'Cleaner Pro',
          kind: 'installed', label: 'odinstalowanie (użytkownik 0)', status: 'running', error: null });
        bridge.emit('exec:admin_wait', { package: 'com.clean.pro.boost', name: 'Cleaner Pro', timeout: 180 });
      });
      await expect(page.getByText('Potrzebny jeden ruch na telefonie')).toBeVisible();
      await expect(page).toHaveScreenshot(`execute-admin-${theme}.png`,
        { mask: [page.getByText(/Czekam jeszcze/), page.locator('svg circle + circle')] });
      await scan(page);
      await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
      await page.getByRole('button', { name: /^Wykonaj/ }).click();
      await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
      await expect(page).toHaveScreenshot(`execute-done-${theme}.png`);
    });

    test('history and settings', async ({ page }) => {
      await scan(page);
      await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
      await page.getByRole('button', { name: /^Wykonaj/ }).click();
      await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
      await page.getByRole('button', { name: 'Historia' }).click();
      await expect(page.getByRole('heading', { name: 'Historia zleceń' })).toBeVisible();
      await expect(page).toHaveScreenshot(`history-${theme}.png`, { mask: [page.locator('li b.block.text-\\[13px\\]')] });
      await page.getByRole('button', { name: 'Ustawienia' }).click();
      await expect(page).toHaveScreenshot(`settings-${theme}.png`);
    });
  });
}

test.describe('motion', () => {
  test('animations run normally', async ({ browser }) => {
    const page = await browser.newPage({ reducedMotion: 'no-preference' });
    await page.goto('http://localhost:4173/?scenario=empty');
    const name = await page.locator('.spin').first().evaluate((el) => getComputedStyle(el).animationName);
    expect(name).toBe('spin');
    await page.close();
  });

  test('prefers-reduced-motion turns animations off on every screen type', async ({ page }) => {
    await page.goto('/?scenario=empty');
    const names = await page.locator('.spin, .scanline, [data-state] .plug').evaluateAll(
      (els) => els.map((el) => getComputedStyle(el).animationName));
    expect(names.length).toBeGreaterThan(0);
    expect(names.every((n) => n === 'none')).toBe(true);
  });
});
