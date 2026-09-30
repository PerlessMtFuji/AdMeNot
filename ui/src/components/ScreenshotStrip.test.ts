import { fireEvent, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test } from 'vitest';
import { renderWith } from '../test-utils';
import ScreenshotStrip from './ScreenshotStrip.svelte';

const ORDER = 'ZS/2026/0926/01';
const flush = () => new Promise((r) => setTimeout(r, 0));

test('nothing to show without screenshots', async () => {
  await renderWith(ScreenshotStrip, 'empty', { order: ORDER });
  await flush();
  expect(screen.queryByText('Zrzuty ekranu')).toBeNull();
});

test('toggle, limit of 8 and zoom', async () => {
  const { ctl } = await renderWith(ScreenshotStrip, 'empty', { order: ORDER });
  for (let i = 0; i < 9; i++) await ctl.takeScreenshot('R58T00TEST');
  await ctl.loadShots(ORDER);
  await tick();
  expect(screen.getByText('w protokole: 8/8')).toBeTruthy();
  const boxes = screen.getAllByRole('checkbox', { name: 'w protokole' }) as HTMLInputElement[];
  expect(boxes).toHaveLength(9);
  expect(boxes[8].checked).toBe(false);
  expect(boxes[8].disabled).toBe(true);
  await fireEvent.click(boxes[0]);
  await flush();
  await tick();
  expect(screen.getByText('w protokole: 7/8')).toBeTruthy();
  expect((screen.getAllByRole('checkbox', { name: 'w protokole' })[8] as HTMLInputElement).disabled).toBe(false);
  await fireEvent.click(screen.getAllByRole('button', { name: /Powiększ zrzut/ })[0]);
  expect(screen.getByRole('dialog')).toBeTruthy();
});
