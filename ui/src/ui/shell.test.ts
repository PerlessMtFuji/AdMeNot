import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import App from '../App.svelte';
import { setupCtl } from '../test-utils';

test('console entry appears in expert mode after a scan and toggles the drawer', async () => {
  const { ctl, s } = await setupCtl('adware');
  render(App, { props: { ctl } });
  expect(screen.queryByRole('button', { name: 'Konsola ADB' })).toBeNull();
  await ctl.startScan();
  await vi.waitFor(() => expect(s.job).toBeNull());
  await ctl.setMode('expert');
  await tick();
  const entry = screen.getByRole('button', { name: 'Konsola ADB' });
  await fireEvent.click(entry);
  expect(s.consoleOpen).toBe(true);
  expect(entry.getAttribute('aria-pressed')).toBe('true');
});

test('back-to-order label while an order is in progress', async () => {
  const { ctl, s } = await setupCtl('empty');
  render(App, { props: { ctl } });
  s.phase = 'results';
  s.screen = 'settings';
  await tick();
  expect(screen.getByRole('button', { name: 'Wróć do zlecenia' })).toBeTruthy();
});
