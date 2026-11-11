import { expect, type Page, test } from '@playwright/test';

async function scan(page: Page, scenario = 'adware', query = '') {
  await page.goto(`/?scenario=${scenario}${query}`);
  await page.getByPlaceholder('np. Anna K.').fill('Anna K.');
  await page.getByRole('button', { name: 'Skanuj' }).click();
  await expect(page.getByText(/Analiza plików aplikacji/)).toBeHidden({ timeout: 15_000 });
}

async function inject(page: Page, fn: (env: any) => void) {
  await page.waitForFunction(() => (window as any).__admenot !== undefined);
  await page.evaluate(fn as never, undefined);
}

for (const theme of ['light', 'dark'] as const) {
  test.describe(`screens (PL, 1280×800, ${theme})`, () => {
    test.use({ colorScheme: theme });
    // Zegar w makiecie telefonu i daty pokazują czas systemowy; bez tego zrzut zmienia się co minutę.
    test.beforeEach(async ({ page }) => {
      await page.clock.setFixedTime(new Date('2026-10-11T09:41:00'));
    });

    test('ekran powitalny', async ({ page }) => {
      await page.goto('/?scenario=empty&welcome=1');
      await expect(page.getByRole('heading', { name: 'Witaj w AdMeNot' })).toBeVisible();
      await expect(page).toHaveScreenshot(`welcome-${theme}.png`);
    });

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
      await page.goto('/?scenario=many');  // dwa telefony tego samego modelu: lista wyboru i jeden zestaw narzędzi
      await expect(page.getByRole('heading', { name: 'Wybierz telefon' })).toBeVisible();
      await page.getByRole('radio').first().check();
      await expect(page.getByRole('button', { name: 'Zrzut ekranu' })).toBeVisible();
      await expect(page).toHaveScreenshot(`connect-many-${theme}.png`);
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
      await page.getByRole('button', { name: /Podsumowanie/ }).click();
      await expect(page.getByRole('region', { name: 'Plan naprawy' })).toBeVisible();
      await expect(page).toHaveScreenshot(`plan-confirm-${theme}.png`);
    });

    test('results: phone state with site notification fixes', async ({ page }) => {
      await scan(page, 'adware', '&checks=populated');
      await page.getByRole('tab', { name: /^Telefon/ }).click();
      await page.getByRole('switch', { name: 'Wycisz tanie-bilety.example' }).check();
      await expect(page.getByRole('complementary', { name: 'Plan naprawy' }).getByText('tanie-bilety.example')).toBeVisible();
      await expect(page).toHaveScreenshot(`results-phone-state-${theme}.png`);
    });

    test('execute: admin prompt and done', async ({ page }) => {
      await page.goto('/?scenario=empty');
      await inject(page, () => {
        const { ctl, bridge } = (window as any).__admenot;
        ctl.state.phase = 'executing';
        ctl.state.order = 'ZS/2026/0926/01';
        bridge.emit('exec:step', { action_id: 1, package: 'com.clean.pro.boost', name: 'Cleaner Pro',
          kind: 'installed', label: 'odinstalowanie (użytkownik 0)', status: 'running', error: null });
        bridge.emit('exec:user_wait', { package: 'com.clean.pro.boost', name: 'Cleaner Pro', kind: 'admin', timeout: 180, action_id: 1 });
      });
      await expect(page.getByText('Potrzebny jeden ruch na telefonie')).toBeVisible();
      await expect(page).toHaveScreenshot(`execute-admin-${theme}.png`,
        { mask: [page.getByText(/Czekam jeszcze/), page.locator('svg circle + circle')] });
      await scan(page);
      await page.getByRole('button', { name: /Podsumowanie/ }).click();
      await page.getByRole('button', { name: /^Wykonaj/ }).click();
      await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
      await expect(page).toHaveScreenshot(`execute-done-${theme}.png`);
    });

    test('history: undo with the site queue', async ({ page }) => {
      await page.goto('/?scenario=empty');
      await inject(page, () => {
        const { ctl, bridge } = (window as any).__admenot;
        const chrome = 'com.android.chrome';
        const step = (id: number, host: string) => ({ id, package: chrome, level: 'fix', level_label: 'Ustawienia witryn',
          kind: 'channel', step_label: `Wyłączenie powiadomień: ${host} (Chrome)`, status: 'done', status_label: 'wykonane',
          error: null, manual_undo: null, site_url: null });
        ctl.state.history = { serial: 'R58T00TEST', serials: ['R58T00TEST'],
          devices: [{ serial: 'R58T00TEST', name: 'Samsung Galaxy A14', model: 'SM-A145R', image: '' }],
          orders: [{ id: 1, number: 'ZS/2026/1011/01', created_at: '2026-10-11T09:20', status: 'done', status_label: 'wykonane',
            client: 'Anna K.', model: 'SM-A145R', interrupted: false, manual: false, screenshots: 0,
            actions: [step(4, 'win-prize.top'), step(5, 'news-daily.click'), { ...step(6, ''), package: 'com.sec.android.app.sbrowser',
              step_label: 'Wyłączenie powiadomień wszystkich witryn (Samsung Internet)' }] }] };
        ctl.state.screen = 'history';
        ctl.state.job = { id: 'job-9', kind: 'undo' };
        bridge.emit('undo:sites', { order: 'ZS/2026/1011/01', sites: [
          { action_id: 4, package: chrome, browser: 'Chrome', site: 'win-prize.top' },
          { action_id: 5, package: chrome, browser: 'Chrome', site: 'news-daily.click' },
          { action_id: 6, package: 'com.sec.android.app.sbrowser', browser: 'Samsung Internet', site: null }] });
        bridge.emit('undo:step', { action_id: 4, package: chrome, name: 'Chrome', kind: 'channel',
          label: 'Wyłączenie powiadomień: win-prize.top (Chrome)', status: 'undone', error: null, error_key: null });
        bridge.emit('exec:user_wait', { package: chrome, name: 'Chrome', kind: 'channel', browser: 'Chrome',
          site: 'news-daily.click', timeout: 180, action_id: 5 });
      });
      await expect(page.getByText('Przywracanie powiadomień witryn')).toBeVisible();
      await expect(page).toHaveScreenshot(`history-undo-sites-${theme}.png`, { mask: [page.locator('li[aria-current] .mono')] });
    });

    test('history and settings', async ({ page }) => {
      await scan(page);
      await page.getByRole('button', { name: /Podsumowanie/ }).click();
      await page.getByRole('button', { name: /^Wykonaj/ }).click();
      await expect(page.getByRole('heading', { name: 'Telefon naprawiony' })).toBeVisible({ timeout: 15_000 });
      await page.getByRole('button', { name: 'Historia' }).click();
      await expect(page.getByRole('heading', { name: 'Historia zleceń' })).toBeVisible();
      await expect(page).toHaveScreenshot(`history-${theme}.png`, { mask: [page.locator('li b.block.text-\\[13px\\]')] });
      await page.getByRole('button', { name: 'Ustawienia' }).click();
      await expect(page).toHaveScreenshot(`settings-${theme}.png`);
    });

    // Snapshots for the two cases below are generated on Windows (`--update-snapshots`), like the rest of the suite.
    test('explorer: gallery and preview', async ({ page }) => {
      await page.goto('/?scenario=explorer');
      await expect(page.getByRole('heading', { name: 'Połączono' })).toBeVisible();
      await page.getByRole('button', { name: 'Pliki' }).click();
      const list = page.getByRole('listbox', { name: 'Pliki w folderze' });
      await expect(list.getByRole('option').first()).toBeVisible();
      await expect(page.getByRole('img', { name: /Zajęte \d+% pamięci telefonu/ })).toBeVisible();
      await expect(page).toHaveScreenshot(`explorer-gallery-${theme}.png`);
      await list.getByRole('option').first().dblclick();
      await expect(page.getByRole('dialog', { name: /^Podgląd pliku/ })).toBeVisible();
      await expect(page).toHaveScreenshot(`explorer-preview-${theme}.png`);
    });
  });
}

// Ekrany przenoszenia danych (spec §7.2–§7.6): jasny i ciemny motyw, 1280 i 1200 px (wiersze nie mogą się łamać).
const NEW_PHONE = /IMEI 499001200000020/;  // IMEI zamiast numeru seryjnego

async function planRestore(page: Page, scenario: string) {
  await page.goto(`/?scenario=${scenario}`);
  await page.getByRole('radio', { name: NEW_PHONE }).dispatchEvent('click');  // radio jest sr-only pod kartą
  await page.getByRole('button', { name: 'Wgraj', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Co wgrać na nowy telefon?' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('complementary', { name: 'Miejsce na nowym telefonie' })).toBeVisible();
}

async function restoreDone(page: Page, scenario = 'transfer_restore') {
  await planRestore(page, scenario);
  await page.getByRole('complementary', { name: 'Miejsce na nowym telefonie' }).getByRole('button', { name: /^Wgraj/ }).click();
  await expect(page.getByRole('heading', { name: 'Dane przeniesione' })).toBeVisible({ timeout: 15_000 });
}

for (const theme of ['light', 'dark'] as const) {
  for (const width of [1280, 1200]) {
    test.describe(`transfer screens (PL, ${width}×900, ${theme})`, () => {
      test.use({ colorScheme: theme, viewport: { width, height: 900 } });
      test.beforeEach(async ({ page }) => {
        await page.clock.setFixedTime(new Date('2026-09-26T15:00:00'));  // nagrana kopia jest świeża (< 24 h)
      });
      const shot = (name: string) => `transfer-${name}-${width}-${theme}.png`;

      test('7.2 copy: choose, and 7.5 copy done', async ({ page }) => {
        await page.goto('/?scenario=transfer');
        await page.getByRole('button', { name: 'Kopiuj dane' }).click();
        await expect(page.getByRole('heading', { name: 'Co skopiować ze starego telefonu?' })).toBeVisible({ timeout: 15_000 });
        await expect(page.getByRole('button', { name: /^Rozpocznij kopię/ })).toBeVisible();
        await expect(page).toHaveScreenshot(shot('choose'));
        await page.getByRole('button', { name: /^Rozpocznij kopię/ }).click();
        await expect(page.getByRole('heading', { name: 'Kopia gotowa' })).toBeVisible({ timeout: 15_000 });
        await expect(page.getByText('Podłącz nowy telefon')).toBeVisible();
        await expect(page).toHaveScreenshot(shot('copy-done'));
      });

      test('7.3 restore plan with apps, and the Xiaomi block opened', async ({ page }) => {
        await planRestore(page, 'transfer_restore');
        await expect(page).toHaveScreenshot(shot('restore-plan'));
        await planRestore(page, 'transfer_restore_xiaomi');
        await page.getByRole('button', { name: /Xiaomi blokuje instalację/ }).click();
        await expect(page.getByText(/Jak włączyć: Ustawienia → Dodatkowe ustawienia/)).toBeVisible();
        await page.getByRole('main').evaluate((el) => { el.scrollTop = el.scrollHeight; });  // lista aplikacji pod instrukcją
        await expect(page).toHaveScreenshot(shot('restore-plan-xiaomi'));
      });

      test('7.5 data transferred, and 7.6 history of transfers', async ({ page }) => {
        await restoreDone(page);
        await expect(page).toHaveScreenshot(shot('restore-done'));
        await page.getByRole('button', { name: 'Historia' }).click();
        await page.getByRole('button', { name: /^Przeniesienia \(/ }).click();
        await expect(page.getByText('ZS/2026/0926/01').first()).toBeVisible();
        await expect(page).toHaveScreenshot(shot('history'));
      });

      test('7.5 data transferred with contacts, messages and the call log import file', async ({ page }) => {
        await restoreDone(page, 'transfer_restore_tel');
        await expect(page.getByText('Kontakty', { exact: true }).first()).toBeVisible();
        await expect(page).toHaveScreenshot(shot('restore-done-tel'));
      });
    });
  }
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
    await expect(page.locator('.spin, .scanline, [data-state] .plug').first()).toBeVisible();
    const names = await page.locator('.spin, .scanline, [data-state] .plug').evaluateAll(
      (els) => els.map((el) => getComputedStyle(el).animationName));
    expect(names.length).toBeGreaterThan(0);
    expect(names.every((n) => n === 'none')).toBe(true);
  });
});

test.describe('minimum window (PL, 1008×661, light)', () => {
  test.use({ viewport: { width: 1008, height: 661 }, colorScheme: 'light' });
  test.beforeEach(async ({ page }) => { await page.clock.setFixedTime(new Date('2026-10-11T09:41:00')); });

  test('results simple and expert', async ({ page }) => {
    await scan(page);
    await expect(page).toHaveScreenshot('min-results-simple.png');
    await page.getByRole('button', { name: 'Ekspert' }).click();
    await expect(page).toHaveScreenshot('min-results-expert.png');
  });
});
