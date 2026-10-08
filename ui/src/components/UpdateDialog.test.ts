import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test } from 'vitest';
import App from '../App.svelte';
import type { UpdateView } from '../lib/types';
import { setupCtl } from '../test-utils';

const AVAILABLE: UpdateView = { available: { version: '9.9.9', notes: 'Poprawki cofania.', size: 52_428_800 },
  dismissed: false, retired: null, updated_to: null, updated_notes: null, installable: true };

async function opened(view: UpdateView = AVAILABLE) {
  const env = await setupCtl('empty');
  render(App, { props: { ctl: env.ctl } });
  env.bridge.emit('update:state', view);
  await fireEvent.click(await screen.findByRole('button', { name: 'Zainstaluj' }));
  return env;
}

test('dialog shows notes, downloads with progress and can be cancelled', async () => {
  const { bridge } = await opened();
  const dialog = await screen.findByRole('dialog', { name: 'AdMeNot 9.9.9' });
  expect(dialog.textContent).toContain('Poprawki cofania.');
  expect(dialog.textContent).toContain('AdMeNot zamknie się, zainstaluje 9.9.9 i uruchomi ponownie.');
  await fireEvent.click(screen.getAllByRole('button', { name: 'Zainstaluj' }).at(-1)!);
  expect(bridge.calls.at(-1)).toEqual({ method: 'install_update', args: [] });
  bridge.emit('update:progress', { done: 26_214_400, total: 52_428_800 });
  await tick();
  expect(screen.getByRole('progressbar', { name: 'Pobieranie aktualizacji' }).getAttribute('aria-valuenow')).toBe('50');
  expect(screen.getByText('Pobrano 25.0 z 50.0 MB')).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Anuluj' }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'stop', args: ['job-update'] });
});

test('download error offers a retry', async () => {
  const { bridge } = await opened();
  await fireEvent.click(screen.getAllByRole('button', { name: 'Zainstaluj' }).at(-1)!);
  bridge.emit('job:error', { job_id: 'job-update', kind: 'update', key: 'update_corrupt', message: '' });
  bridge.emit('job:end', { job_id: 'job-update', kind: 'update' });
  expect(await screen.findByText('Pobrany plik jest uszkodzony lub podmieniony — spróbuj ponownie.')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Spróbuj ponownie' })).toBeTruthy();
  expect(screen.queryByRole('progressbar')).toBeNull();
});

test('launch failure names the download page', async () => {
  const { bridge } = await opened();
  await fireEvent.click(screen.getAllByRole('button', { name: 'Zainstaluj' }).at(-1)!);
  bridge.emit('job:error', { job_id: 'job-update', kind: 'update', key: 'update_launch_failed', message: 'x',
    page: 'https://admenot.e-wlodarski.workers.dev/pl/' });
  expect(await screen.findByText(/Pobierz go ze strony: https:\/\/admenot\.e-wlodarski\.workers\.dev\/pl\//)).toBeTruthy();
});

test('development build closes the dialog after opening the page', async () => {
  const { bridge } = await opened({ ...AVAILABLE, installable: false });
  expect(screen.getByText('Wersja deweloperska — otworzę stronę pobierania.')).toBeTruthy();
  await fireEvent.click(screen.getAllByRole('button', { name: 'Zainstaluj' }).at(-1)!);
  await tick();
  expect(bridge.calls.at(-1)?.method).toBe('install_update');
  expect(screen.queryByRole('dialog')).toBeNull();
});

test('a change blocked by a withdrawn version opens the dialog', async () => {
  const { ctl, bridge, s } = await setupCtl('empty');
  render(App, { props: { ctl } });
  bridge.emit('update:state', { ...AVAILABLE, retired: { min_supported: '9.0.0', reason: 'Błąd cofania' } });
  await ctl.execute();
  await tick();
  expect(s.error).toBeNull();
  const dialog = await screen.findByRole('dialog', { name: 'AdMeNot 9.9.9' });
  expect(dialog.textContent).toContain('Błąd cofania');
});
