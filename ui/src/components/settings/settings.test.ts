import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import Toggle from '../../ui/Toggle.svelte';
import { matches } from './search.svelte';
import GroupHarness from './GroupHarness.test.svelte';

test('matches ignores diacritics and case; empty query matches all', () => {
  expect(matches('zrodlo', 'Źródło adb')).toBe(true);
  expect(matches('PDF', 'Folder protokołów pdf')).toBe(true);
  expect(matches('lodz', 'Łódź')).toBe(true);
  expect(matches('bajt', 'Sprawdzaj bajt po bajcie')).toBe(true);
  expect(matches('', 'cokolwiek')).toBe(true);
  expect(matches('xyz', 'abc')).toBe(false);
});

test('Toggle: click calls onchange(true)', async () => {
  const onchange = vi.fn();
  render(Toggle, { props: { checked: false, label: 'Opcja', onchange } });
  await fireEvent.click(screen.getByRole('switch', { name: 'Opcja' }));
  expect(onchange).toHaveBeenCalledWith(true);
});

test('Toggle reverts to the stored value when the save fails', async () => {
  const onchange = vi.fn().mockResolvedValue(false);
  render(Toggle, { props: { checked: false, label: 'Opcja', onchange } });
  const sw = screen.getByRole('switch', { name: 'Opcja' });
  await fireEvent.click(sw);
  await tick();
  expect(sw.getAttribute('aria-checked')).toBe('false');
});

async function type(value: string): Promise<void> {
  const input = screen.getByLabelText('q') as HTMLInputElement;
  input.value = value;
  await fireEvent.input(input);
}

test('SettingGroup disappears when no row matches, shows when one does', async () => {
  const { container } = render(GroupHarness);
  const group = () => container.querySelector('[data-setting-group]') as HTMLElement;
  expect(group().hidden).toBe(false);
  await type('zzz');
  await tick();
  expect(group().hidden).toBe(true);
  await type('ZRODLO');
  await tick();
  expect(group().hidden).toBe(false);
  expect((container.querySelector('[data-setting-id="a"]') as HTMLElement).hidden).toBe(false);
  expect((container.querySelector('[data-setting-id="b"]') as HTMLElement).hidden).toBe(true);
});
