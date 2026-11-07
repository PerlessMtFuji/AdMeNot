import { screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test } from 'vitest';
import { renderWith } from '../test-utils';
import ReportButton from './ReportButton.svelte';

const ORDER = 'ZS/2026/0929/01';
const DIR = 'C:\\reports\\ZS-2026-0929-01';

test('saved report that Windows could not open shows the path, not "opened"', async () => {
  const { s } = await renderWith(ReportButton, 'empty', { order: ORDER });
  s.reports[ORDER] = { order: ORDER, html: `${DIR}.html`, pdf: `${DIR}.pdf`, error: null, opened: null };
  await tick();
  const text = document.body.textContent ?? '';
  expect(text).toContain(`Zapisano protokół: ${DIR}.pdf`);
  expect(text).not.toContain('Otwarto');
  expect(screen.getByRole('button', { name: 'Protokół PDF' })).toBeTruthy();
});

test('report not opened on purpose (setting off) shows the path in a neutral tone, not a failure', async () => {
  const { s } = await renderWith(ReportButton, 'empty', { order: ORDER });
  s.reports[ORDER] = { order: ORDER, html: `${DIR}.html`, pdf: `${DIR}.pdf`, error: null, opened: null, open_skipped: true };
  await tick();
  const text = document.body.textContent ?? '';
  expect(text).toContain(`Zapisano protokół: ${DIR}.pdf`);
  expect(text).not.toContain('nie udało się');
  expect(document.querySelector('.text-warn')).toBeNull();
});

test('PDF error wins over the skipped opening: the HTML fallback reason is shown', async () => {
  const { s } = await renderWith(ReportButton, 'empty', { order: ORDER });
  s.reports[ORDER] = { order: ORDER, html: `${DIR}.html`, pdf: null, pdf_target: `${DIR}.pdf`, error: 'failed',
    opened: null, open_skipped: true };
  await tick();
  const text = document.body.textContent ?? '';
  expect(text).toContain('Nie udało się utworzyć PDF.');
  expect(text).toContain(`${DIR}.html`);
  expect(text).not.toContain('brak programu');
});
