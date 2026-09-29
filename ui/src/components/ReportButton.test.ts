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
