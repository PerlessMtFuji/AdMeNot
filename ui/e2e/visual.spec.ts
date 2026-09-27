import { expect, type Page, test } from '@playwright/test';

async function scan(page: Page, scenario = 'adware') {
  await page.goto(`/?scenario=${scenario}`);
  await page.getByPlaceholder('np. Anna K.').fill('Anna K.');
  await page.getByRole('button', { name: 'Skanuj' }).click();
  await expect(page.getByText(/Analiza APK w tle/)).toBeHidden({ timeout: 15_000 });
}

test.describe('screens (PL, 1280×800)', () => {
  test('connect: waiting', async ({ page }) => {
    await page.goto('/?scenario=empty');
    await expect(page.getByText('Czekam na telefon…')).toBeVisible();
    await expect(page).toHaveScreenshot('connect-empty.png');
  });

  test('results: simple and expert', async ({ page }) => {
    await scan(page);
    await expect(page).toHaveScreenshot('results-simple.png');
    await page.getByRole('button', { name: 'Ekspert' }).click();
    await expect(page).toHaveScreenshot('results-expert.png');
    await page.getByRole('button', { name: 'Konsola ADB' }).click();
    await expect(page).toHaveScreenshot('results-console.png');
  });

  test('plan preview and execution result', async ({ page }) => {
    await scan(page);
    await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
    await expect(page).toHaveScreenshot('plan-preview.png');
    await page.getByRole('button', { name: /^Wykonaj/ }).click();
    await expect(page.getByText(/: wykonane/)).toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveScreenshot('execute-done.png');
  });

  test('admin prompt', async ({ page }) => {
    await page.goto('/?scenario=empty');
    await page.waitForFunction(() => (window as any).__demalware !== undefined);
    await page.evaluate(() => {
      const { ctl, bridge } = (window as any).__demalware;
      ctl.state.phase = 'executing';
      ctl.state.order = 'ZS/2026/0926/01';
      bridge.emit('exec:step', { action_id: 1, package: 'com.clean.pro.boost', name: 'Cleaner Pro',
        kind: 'installed', label: 'odinstalowanie (użytkownik 0)', status: 'running', error: null });
      bridge.emit('exec:admin_wait', { package: 'com.clean.pro.boost', name: 'Cleaner Pro', timeout: 180 });
    });
    await expect(page.getByText('Potrzebny jeden ruch na telefonie')).toBeVisible();
    await expect(page).toHaveScreenshot('execute-admin.png', { mask: [page.getByText(/Czekam jeszcze/)] });
  });

  test('history and settings', async ({ page }) => {
    await scan(page);
    await page.getByRole('button', { name: /Napraw zaznaczone/ }).click();
    await page.getByRole('button', { name: /^Wykonaj/ }).click();
    await expect(page.getByText(/: wykonane/)).toBeVisible({ timeout: 15_000 });
    await page.getByRole('button', { name: 'Historia' }).click();
    await expect(page.getByText('Historia zleceń')).toBeVisible();
    await expect(page).toHaveScreenshot('history.png');
    await page.getByRole('button', { name: 'Ustawienia' }).click();
    await expect(page).toHaveScreenshot('settings.png');
  });
});

test.describe('motion', () => {
  test('animations run normally', async ({ browser }) => {
    const page = await browser.newPage({ reducedMotion: 'no-preference' });
    await page.goto('http://localhost:4173/?scenario=empty');
    const name = await page.locator('.spin').first().evaluate((el) => getComputedStyle(el).animationName);
    expect(name).toBe('spin');
    await page.close();
  });

  test('prefers-reduced-motion turns animations off', async ({ page }) => {
    await page.goto('/?scenario=empty');
    const name = await page.locator('.spin').first().evaluate((el) => getComputedStyle(el).animationName);
    expect(name).toBe('none');
  });
});
