import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test } from 'vitest';
import App from '../App.svelte';
import type { UpdateView } from '../lib/types';
import { setupCtl } from '../test-utils';

const NONE: UpdateView = { available: null, dismissed: false, retired: null, updated_to: null, updated_notes: null, installable: true };
const AVAILABLE: UpdateView = { ...NONE, available: { version: '9.9.9', notes: 'Poprawki cofania.', size: 52_428_800 } };

test('new version banner, dismissed for this version', async () => {
  const { ctl, bridge } = await setupCtl('empty');
  render(App, { props: { ctl } });
  bridge.emit('update:state', AVAILABLE);
  expect(await screen.findByText('Dostępna wersja 9.9.9')).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Nie przypominaj o tej wersji' }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'dismiss_update', args: ['9.9.9'] });
  await tick();
  expect(screen.queryByText('Dostępna wersja 9.9.9')).toBeNull();
});

test('retired banner has no dismiss and names the reason', async () => {
  const { ctl, bridge } = await setupCtl('empty');
  render(App, { props: { ctl } });
  bridge.emit('update:state', { ...AVAILABLE, retired: { min_supported: '9.0.0', reason: 'Błąd cofania na Xiaomi' } });
  expect(await screen.findByText('Ta wersja jest wycofana')).toBeTruthy();
  expect(screen.getByText(/Błąd cofania na Xiaomi\. Zmiany na telefonach są zablokowane/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Nie przypominaj o tej wersji' })).toBeNull();
});

test('install is disabled while a job runs', async () => {
  const { ctl, s, bridge } = await setupCtl('empty');
  render(App, { props: { ctl } });
  bridge.emit('update:state', AVAILABLE);
  s.job = { id: 'job-1', kind: 'scan' };
  await tick();
  const install = await screen.findByRole('button', { name: 'Zainstaluj' });
  expect((install as HTMLButtonElement).disabled).toBe(true);
  expect(install.getAttribute('title')).toBe('Dostępne po zakończeniu bieżącego zadania');
});

test('updated message shows once', async () => {
  const { ctl, bridge } = await setupCtl('empty');
  render(App, { props: { ctl } });
  bridge.emit('update:state', { ...NONE, updated_to: '0.9.3', updated_notes: 'Nowy baner.' });
  expect(await screen.findByText('Zaktualizowano do 0.9.3')).toBeTruthy();
  expect(screen.getByText('Nowy baner.')).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Zamknij' }));
  await tick();
  expect(screen.queryByText('Zaktualizowano do 0.9.3')).toBeNull();
});

test('init asks for the update state', async () => {
  const { bridge } = await setupCtl('empty');
  expect(bridge.calls.some((c) => c.method === 'update_state')).toBe(true);
});
