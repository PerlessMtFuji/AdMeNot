import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';

test('rapid folder navigation and resizing keep both virtualized views usable without observer loops', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.addInitScript(() => {
    (window as any).__layoutErrors = [];
    window.addEventListener('error', event => (window as any).__layoutErrors.push(event.message));
  });
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki', exact: true }).click();
  const paths = ['/sdcard/DCIM/Camera', '/sdcard/Download', '/sdcard/Music', '/sdcard'];
  for (let i = 0; i < 24; i++) {
    await page.setViewportSize({ width: [1008, 1136, 1280][i % 3], height: [661, 740, 800][i % 3] });
    await page.evaluate(async ({ path, view }) => {
      const ex = (window as any).__admenot.ctl.explorer;
      ex.setView(view);
      await ex.go(path);
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }, { path: paths[i % paths.length], view: i % 2 ? 'list' : 'grid' });
  }
  await expect(page.getByRole('listbox', { name: 'Pliki w folderze' })).toBeVisible();
  expect(await page.evaluate(() => (window as any).__admenot.ctl.state.fatal)).toBeNull();
  expect(await page.evaluate(() => (window as any).__layoutErrors)).toEqual([]);
  expect(errors).toEqual([]);
});

test('PDF renders, searches all pages, highlights matches and handles page/zoom changes', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('http://127.0.0.1:4173/test-search.pdf', route => route.fulfill({
    body: readFileSync(new URL('./fixtures/search.pdf', import.meta.url)),
    contentType: 'application/pdf', headers: { 'Access-Control-Allow-Origin': '*' },
  }));
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki', exact: true }).click();
  await page.evaluate(() => {
    const ex = (window as any).__admenot.ctl.explorer;
    const entry = { ...ex.state.entries[0], path: '/sdcard/search.pdf', name: 'search.pdf', kind: 'file',
      type: 'doc', ext: 'pdf', url: 'http://127.0.0.1:4173/test-search.pdf', thumb: null };
    ex.state.entries = [...ex.state.entries, entry];
    ex.openPreview(entry.path);
  });
  const dialog = page.getByRole('dialog');
  await expect(dialog.locator('[data-page="1"] .textLayer')).toContainText('alpha beta alpha');
  const search = dialog.getByRole('searchbox', { name: 'Szukaj w treści' });
  await search.fill('alpha');
  await expect(dialog.getByRole('status').filter({ hasText: '1 z 3' })).toBeVisible();
  await expect(dialog.locator('[data-page="1"] mark')).toHaveCount(2);
  await dialog.getByRole('button', { name: 'Następne trafienie' }).click();
  await dialog.getByRole('button', { name: 'Następne trafienie' }).click();
  await expect(dialog.getByRole('spinbutton', { name: 'Strona' })).toHaveValue('2');
  await expect(dialog.locator('mark.pdf-active')).toHaveText('alpha');
  await search.fill('gamma');
  await expect(dialog.getByRole('status').filter({ hasText: '1 z 1' })).toBeVisible();
  await dialog.getByRole('button', { name: 'Powiększ PDF' }).click();
  await expect(dialog.locator('[data-page="2"] .textLayer')).toContainText('gamma alpha');
  await search.fill('absent');
  await expect(dialog.getByRole('status').filter({ hasText: '0 z 0' })).toBeVisible();
  expect(errors).toEqual([]);
});

async function openPdf(page: import('@playwright/test').Page) {
  await page.route('http://127.0.0.1:4173/test-search.pdf', route => route.fulfill({
    body: readFileSync(new URL('./fixtures/search.pdf', import.meta.url)),
    contentType: 'application/pdf', headers: { 'Access-Control-Allow-Origin': '*' },
  }));
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki', exact: true }).click();
  await page.evaluate(() => {
    const ex = (window as any).__admenot.ctl.explorer;
    const entry = { ...ex.state.entries[0], path: '/sdcard/search.pdf', name: 'search.pdf', kind: 'file',
      type: 'doc', ext: 'pdf', url: 'http://127.0.0.1:4173/test-search.pdf', thumb: null };
    ex.state.entries = [...ex.state.entries, entry];
    ex.openPreview(entry.path);
  });
  const dialog = page.getByRole('dialog');
  await dialog.locator('[data-page="1"] canvas').waitFor();
  return dialog;
}

test('PDF: the wheel scrolls through the pages and the page number follows', async ({ page }) => {
  const dialog = await openPdf(page);
  const scroller = dialog.locator('[data-pdf-scroll]');
  await scroller.hover();
  const pageBox = dialog.getByRole('spinbutton', { name: 'Strona' });
  await expect(pageBox).toHaveValue('1');
  for (let i = 0; i < 40; i++) await page.mouse.wheel(0, 300);
  await expect(pageBox).toHaveValue('2');
  await expect(dialog.locator('[data-page="2"] canvas')).toBeVisible();
});

test('PDF: Ctrl+wheel zooms the document, not the program', async ({ page }) => {
  const dialog = await openPdf(page);
  await dialog.locator('[data-pdf-scroll]').hover();
  const width = () => dialog.locator('[data-page="1"]').evaluate((el) => el.getBoundingClientRect().width);
  const before = await width();
  await page.keyboard.down('Control');
  await page.mouse.wheel(0, -200);
  await page.keyboard.up('Control');
  await expect.poll(width).toBeGreaterThan(before);
  await expect(dialog.getByText('110%')).toBeVisible();
  expect(await page.evaluate(() => window.visualViewport!.scale)).toBe(1);
});

test('view choice survives folder navigation', async ({ page }) => {
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki', exact: true }).click();
  await page.getByRole('button', { name: 'Lista', exact: true }).click();
  await page.getByRole('navigation', { name: 'Miejsca' }).getByRole('button', { name: /Pobrane/ }).click();
  await expect(page.getByRole('button', { name: 'Lista', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('navigation', { name: 'Miejsca' }).getByRole('button', { name: /Aparat/ }).click();
  await expect(page.getByRole('button', { name: 'Lista', exact: true })).toHaveAttribute('aria-pressed', 'true');
});

for (const view of ['grid', 'list']) {
  test(`explorer ${view}: double click never mounts the selection bar`, async ({ page }) => {
    await page.goto('/?scenario=explorer');
    await page.getByRole('button', { name: 'Pliki' }).click();
    await page.getByRole('button', { name: view === 'grid' ? 'Siatka' : 'Lista', exact: true }).click();
    await page.evaluate(() => {
      (window as any).__selectionBars = 0;
      new MutationObserver((records) => {
        for (const record of records) for (const node of record.addedNodes) {
          if (node instanceof Element && (node.matches('[aria-label="Zaznaczenie"]') || node.querySelector('[aria-label="Zaznaczenie"]'))) {
            (window as any).__selectionBars++;
          }
        }
      }).observe(document.body, { childList: true, subtree: true });
    });
    await page.getByRole('listbox', { name: 'Pliki w folderze' }).getByRole('option').first().dblclick({ delay: 150 });
    await expect(page.getByRole('dialog')).toBeVisible();
    expect(await page.evaluate(() => (window as any).__selectionBars)).toBe(0);
    await page.keyboard.press('Escape');
    await expect(page.getByRole('region', { name: 'Zaznaczenie' })).toHaveCount(0);
    expect(await page.evaluate(() => (window as any).__admenot.ctl.explorer.state.selected.size)).toBe(0);
  });
}

for (const view of ['grid', 'list']) {
  test.describe(`hover preview in ${view}`, () => {
    const one = (page: import('@playwright/test').Page, name: string) => page.locator(`[data-path="/sdcard/peek/${name}"]`);
    async function openFiles(page: import('@playwright/test').Page, errors: string[]) {
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto('/?scenario=explorer');
      await page.getByRole('button', { name: 'Pliki', exact: true }).click();
      await page.getByRole('button', { name: view === 'grid' ? 'Siatka' : 'Lista', exact: true }).click();
      await page.evaluate(() => {
        const ex = (window as any).__admenot.ctl.explorer;
        const file = (name: string, type: string, ext: string, url: string | null) => ({ ...ex.state.entries[0], kind: 'file', label: null,
          path: `/sdcard/peek/${name}`, name, type, ext, url, thumb: null, size: 2048 });
        ex.state.entries = [
          file('pierwszy.txt', 'text', 'txt', null), file('drugi.txt', 'text', 'txt', null),
          file('search.pdf', 'doc', 'pdf', 'http://127.0.0.1:4173/peek-search.pdf'),
          file('zdjecie.png', 'image', 'png', 'http://127.0.0.1:4173/peek.png'),
          file('zepsute.png', 'image', 'png', 'http://127.0.0.1:4173/peek-404.png'),
        ];
      });
    }

    test('stays in the window, swaps at once, the wheel closes it, a click still selects', async ({ page }) => {
      const errors: string[] = [];
      await openFiles(page, errors);
      const peek = page.getByTestId('peek');
      await one(page, 'pierwszy.txt').hover();
      await expect(peek).toBeVisible();
      await expect(peek).toContainText('pierwszy.txt');
      await expect(peek.locator('pre')).toContainText('Przykładowy tekst');
      const box = (await peek.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(1280);
      expect(box.y + box.height).toBeLessThanOrEqual(800);
      // Wiersz listy ma całą szerokość: bez zakotwiczenia przy kursorze dymek przyklejałby się do lewej krawędzi i zasłaniał nazwę.
      if (view === 'list') expect(box.x).toBeGreaterThan(8);

      await one(page, 'drugi.txt').hover();
      await expect(peek).toContainText('drugi.txt', { timeout: 200 });  // w przejeździe bez opóźnienia

      await page.mouse.wheel(0, 40);
      await expect(peek).toHaveCount(0);
      await expect(peek).toBeVisible();  // cisza i zwykłe opóźnienie: plik pod kursorem wraca

      await one(page, 'drugi.txt').click();
      await expect(peek).toHaveCount(0);
      expect(await page.evaluate(() => (window as any).__admenot.ctl.explorer.state.selected.has('/sdcard/peek/drugi.txt'))).toBe(true);
      expect(errors).toEqual([]);
    });

    test('PDF and photo show their content; an unreadable file closes silently', async ({ page }) => {
      const errors: string[] = [];
      await page.route('http://127.0.0.1:4173/peek-search.pdf', route => route.fulfill({
        body: readFileSync(new URL('./fixtures/search.pdf', import.meta.url)),
        contentType: 'application/pdf', headers: { 'Access-Control-Allow-Origin': '*' },
      }));
      await page.route('http://127.0.0.1:4173/peek.png', route => route.fulfill({
        body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64'),
        contentType: 'image/png', headers: { 'Access-Control-Allow-Origin': '*' },
      }));
      await page.route('http://127.0.0.1:4173/peek-404.png', route => route.fulfill({ status: 404, body: '' }));
      await openFiles(page, errors);
      const peek = page.getByTestId('peek');

      await one(page, 'search.pdf').hover();
      await expect(peek.locator('canvas')).toBeVisible();
      await expect(peek.locator('[data-peek-icon]')).toHaveCount(0, { timeout: 10_000 });
      expect(await peek.locator('canvas').evaluate((c: HTMLCanvasElement) => c.width)).toBeGreaterThan(300);

      await one(page, 'zdjecie.png').hover();
      await expect(peek.locator('img')).toHaveCount(1);
      await expect(peek.locator('img')).not.toHaveClass(/opacity-0/);

      await one(page, 'zepsute.png').hover();
      await expect(peek).toHaveCount(0);
      await expect(page.getByRole('alert')).toHaveCount(0);
      expect(await page.evaluate(() => (window as any).__admenot.ctl.explorer.state.error)).toBeNull();
      expect(errors).toEqual([]);
    });
  });
}

test('hover preview: a video plays with sound, leaving frees it, nothing keeps animating', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki', exact: true }).click();
  await page.evaluate(async () => {
    const canvas = document.createElement('canvas');
    canvas.width = 160;
    canvas.height = 120;
    const stream = canvas.captureStream(10);
    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => chunks.push(event.data);
    const recorded = new Promise<Blob>((resolve) => { recorder.onstop = () => resolve(new Blob(chunks, { type: 'video/webm' })); });
    recorder.start();
    const ctx = canvas.getContext('2d')!;
    for (let i = 0; i < 12; i++) {
      ctx.fillStyle = i % 2 ? '#222' : '#ddd';
      ctx.fillRect(0, 0, 160, 120);
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    recorder.stop();
    const url = URL.createObjectURL(await recorded);
    stream.getTracks().forEach((track) => track.stop());
    const ex = (window as any).__admenot.ctl.explorer;
    ex.state.entries = [{ ...ex.state.entries[0], kind: 'file', label: null, path: '/sdcard/peek/film.webm', name: 'film.webm',
      type: 'video', ext: 'webm', url, thumb: null }];
  });
  await page.locator('[data-path="/sdcard/peek/film.webm"]').hover();
  const peek = page.getByTestId('peek');
  const video = peek.locator('video');
  await expect(video).toBeVisible();
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBeGreaterThan(0);
  expect(await video.evaluate((el: HTMLVideoElement) => el.muted)).toBe(false);
  await page.waitForTimeout(250);  // wejście dymka minęło
  const endless = await peek.evaluate((el) => el.getAnimations({ subtree: true })
    .filter((a) => a.effect?.getComputedTiming().iterations === Infinity).length);
  expect(endless).toBe(0);
  expect(await peek.evaluate((el) => getComputedStyle(el).backdropFilter)).toBe('none');

  await video.evaluate((el) => { (window as any).__peekVideo = el; });
  await page.mouse.move(2, 2);
  await expect(peek).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).__peekVideo.hasAttribute('src'))).toBe(false);
  expect(errors).toEqual([]);
});

test('explorer: picker and drop upload paths render tasks without JavaScript errors', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki' }).click();
  await page.getByRole('button', { name: 'Wgraj tutaj' }).click();
  await page.getByRole('menuitem', { name: /^Pliki…/ }).click();
  await expect(page.getByText('Wgrywanie na telefon', { exact: true }).first()).toBeVisible();
  await page.evaluate(() => {
    (window as any).__admenot.bridge.emit('explorer:drop', { paths: ['C:\\film.mp4'], count: 1, bytes: 20 });
  });
  await expect.poll(() => page.evaluate(() => (window as any).__admenot.ctl.explorer.state.tasks.length)).toBe(2);
  expect(errors).toEqual([]);
});

test('portrait video fits above controls and reports decoded dimensions without MediaStore', async ({ page }) => {
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki' }).click();
  await page.evaluate(async () => {
    const { ctl, bridge } = (window as any).__admenot;
    const canvas = document.createElement('canvas');
    canvas.width = 180;
    canvas.height = 320;
    const stream = canvas.captureStream(10);
    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => chunks.push(event.data);
    const recorded = new Promise<Blob>((resolve) => {
      recorder.onstop = () => resolve(new Blob(chunks, { type: 'video/webm' }));
    });
    recorder.start();
    canvas.getContext('2d')!.fillRect(0, 0, 180, 320);
    await new Promise((resolve) => setTimeout(resolve, 200));
    recorder.stop();
    const url = URL.createObjectURL(await recorded);
    stream.getTracks().forEach((track) => track.stop());
    const entry = { ...ctl.explorer.state.entries[0], path: '/sdcard/portrait.mp4', name: 'portrait.mp4',
      type: 'video', ext: 'mp4', url, thumb: null };
    ctl.explorer.state.entries = [...ctl.explorer.state.entries, entry];
    bridge.answerNext('explorer_meta', { meta: { size: entry.size, mtime: entry.mtime, path: entry.path } });
    ctl.explorer.openPreview(entry.path);
  });
  const video = page.locator('video');
  await expect(video).toBeVisible();
  await expect(page.getByRole('dialog').locator('header')).toContainText('180 × 320');
  await page.getByRole('button', { name: 'Informacje o pliku' }).click();
  await expect(page.getByRole('complementary', { name: 'Informacje o pliku' })).toContainText('180 × 320');
  await expect(page.getByRole('complementary', { name: 'Informacje o pliku' })).toContainText('MP4');
  const fits = await video.evaluate((el) => {
    const bounds = el.getBoundingClientRect();
    const dialog = el.closest('[role="dialog"]')!.getBoundingClientRect();
    return getComputedStyle(el).objectFit === 'contain' && bounds.top >= dialog.top
      && bounds.bottom <= dialog.bottom - 100 && bounds.right <= dialog.right;
  });
  expect(fits).toBe(true);
});

for (const scan of ['scan-ccitt', 'scan-jpx']) {
  test(`${scan}: a scanned PDF shows its picture, not a blank page`, async ({ page }) => {
    await page.route(`http://127.0.0.1:4173/${scan}.pdf`, route => route.fulfill({
      body: readFileSync(new URL(`./fixtures/${scan}.pdf`, import.meta.url)),
      contentType: 'application/pdf', headers: { 'Access-Control-Allow-Origin': '*' },
    }));
    await page.goto('/?scenario=explorer');
    await page.getByRole('button', { name: 'Pliki', exact: true }).click();
    await page.evaluate((scan) => {
      const ex = (window as any).__admenot.ctl.explorer;
      const entry = { ...ex.state.entries[0], path: `/sdcard/${scan}.pdf`, name: `${scan}.pdf`, kind: 'file',
        type: 'doc', ext: 'pdf', url: `http://127.0.0.1:4173/${scan}.pdf`, thumb: null };
      ex.state.entries = [...ex.state.entries, entry];
      ex.openPreview(entry.path);
    }, scan);
    await expect.poll(() => page.evaluate(() => {
      const c = document.querySelector('[role=dialog] canvas') as HTMLCanvasElement | null;
      if (!c || c.width < 300) return 0;
      const d = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
      let dark = 0;
      for (let i = 0; i < d.length; i += 4) if (d[i] < 128) dark++;
      return dark / (d.length / 4);
    }), { timeout: 10_000 }).toBeGreaterThan(0.1);
  });
}

test('deep path: the current folder stays visible in the breadcrumbs', async ({ page }) => {
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki', exact: true }).click();
  await page.evaluate(() => {
    const ex = (window as any).__admenot.ctl.explorer;
    ex.state.crumbs = Array.from({ length: 7 }, (_, i) => ({ label: `bardzo długa nazwa folderu numer ${i}`, path: `/sdcard/${i}` }));
  });
  const last = page.getByRole('navigation', { name: 'Ścieżka' }).getByRole('button').last();
  await expect(last).toBeInViewport({ ratio: 0.95 });
});

test('notices and action bars do not move the side panel or the file area', async ({ page }) => {
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki', exact: true }).click();
  const list = page.getByRole('listbox', { name: 'Pliki w folderze' });
  await list.getByRole('option').first().waitFor();
  const places = page.getByRole('navigation', { name: 'Miejsca' }).locator('xpath=ancestor::aside');
  const area = list.locator('xpath=ancestor::section[1]');
  const before = [await places.boundingBox(), await area.boundingBox()];
  await list.getByRole('option').first().click();
  await expect(page.getByRole('region', { name: 'Zaznaczenie' })).toBeVisible();
  await page.evaluate(() => {
    const { ctl, bridge } = (window as any).__admenot;
    ctl.explorer.state.error = { key: 'explorer_denied', message: '' };
    bridge.emit('explorer:task', { task: { id: 'x', kind: 'to_phone', status: 'running', done_files: 1, total_files: 3,
      done_bytes: 1, total_bytes: 3, speed: 1, eta_s: 5, skipped: 0, renamed: 0, failed: [], verified: null, dest: '/sdcard', omitted: 0, targets: [] } });
  });
  await expect(page.getByRole('region', { name: 'Zadania' })).toBeVisible();
  expect([await places.boundingBox(), await area.boundingBox()]).toEqual(before);
});

test('the last row can still be scrolled above the action bars', async ({ page }) => {
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki', exact: true }).click();
  await page.getByRole('button', { name: 'Lista', exact: true }).click();
  const list = page.getByRole('listbox', { name: 'Pliki w folderze' });
  await list.getByRole('option').first().click();
  const bar = page.getByRole('region', { name: 'Zaznaczenie' });
  await expect(bar).toBeVisible();
  await list.evaluate((el) => { el.scrollTop = el.scrollHeight; });
  await page.waitForTimeout(200);
  const last = await list.getByRole('option').last().boundingBox();
  const dock = await bar.boundingBox();
  expect(last!.y + last!.height).toBeLessThanOrEqual(dock!.y);
});

test('an idle photo preview does no work every frame', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.route('http://127.0.0.1:4173/idle.png', route => route.fulfill({
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64'),
    contentType: 'image/png', headers: { 'Access-Control-Allow-Origin': '*' },
  }));
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki', exact: true }).click();
  await page.evaluate(() => {
    const ex = (window as any).__admenot.ctl.explorer;
    const entry = { ...ex.state.entries[0], path: '/sdcard/idle.png', name: 'idle.png', kind: 'file', type: 'image', ext: 'png',
      url: 'http://127.0.0.1:4173/idle.png', thumb: 'http://127.0.0.1:4173/idle.png' };
    ex.state.entries = [...ex.state.entries, entry];
    ex.openPreview(entry.path);
  });
  await expect(page.getByRole('dialog').locator('.glow')).toHaveCount(1);  // poświata jest, tylko nie pracuje bez przerwy
  // Pełnoekranowe rozmycie w ruchu przerysowuje się co klatkę: na 165 Hz zabierało dwa rdzenie i klatkowało grę w tle.
  // Bezgłowy Chromium tego nie pokazuje w licznikach, więc pilnujemy samej przyczyny.
  expect(await page.locator('.glow').evaluate((el) => el.getAnimations().length)).toBe(0);
});

test('closing a zoomed photo takes no snapshot of it', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.route('http://127.0.0.1:4173/zoom.png', route => route.fulfill({
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64'),
    contentType: 'image/png', headers: { 'Access-Control-Allow-Origin': '*' },
  }));
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki', exact: true }).click();
  await page.evaluate(() => {
    const start = document.startViewTransition.bind(document);
    (window as any).__transitions = 0;
    document.startViewTransition = ((cb: () => void) => { (window as any).__transitions++; return start(cb); }) as typeof document.startViewTransition;
    const ex = (window as any).__admenot.ctl.explorer;
    ex.state.entries = [...ex.state.entries, { ...ex.state.entries[0], path: '/sdcard/zoom.png', name: 'zoom.png', kind: 'file', type: 'image', ext: 'png',
      url: 'http://127.0.0.1:4173/zoom.png', thumb: 'http://127.0.0.1:4173/zoom.png' }];
  });
  const open = () => page.evaluate(() => (window as any).__admenot.ctl.explorer.openPreview('/sdcard/zoom.png'));
  const transitions = () => page.evaluate(() => (window as any).__transitions);
  const dialog = page.getByRole('dialog');

  await open();
  const photo = dialog.locator('[data-morph="photo"]');
  await photo.waitFor();
  const box = (await photo.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, -120);
  await expect(photo).toHaveAttribute('style', /scale\(1\.25\)/);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  // Zrzut elementu ze scale(8) to 593 MB na klatkę, zmierzone 2,5 GB: zapełniał kartę i klatkował cały komputer.
  expect(await transitions()).toBe(0);

  await open();
  await photo.waitFor();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  expect(await transitions()).toBe(1);  // zwykłe zdjęcie nadal kurczy się płynnie
});

test('the storage wave rests when nothing happens and moves during a task', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.goto('/?scenario=explorer');
  await page.getByRole('button', { name: 'Pliki', exact: true }).click();
  await page.getByTestId('phone-storage').waitFor();
  // Stała animacja to 165 klatek na sekundę w bezczynności: 0,7 rdzenia, zmierzone na monitorze 165 Hz.
  const count = () => page.locator('.wave').first().evaluate((el) => getComputedStyle(el).animationIterationCount);
  expect(await count()).not.toBe('infinite');
  await page.evaluate(() => {
    (window as any).__admenot.bridge.emit('explorer:task', { task: { id: 'x', kind: 'to_phone', status: 'running', done_files: 1, total_files: 3,
      done_bytes: 1, total_bytes: 3, speed: 1, eta_s: 5, skipped: 0, renamed: 0, failed: [], verified: null, dest: '/sdcard', omitted: 0, targets: [] } });
  });
  await expect.poll(count).toBe('infinite');
});
