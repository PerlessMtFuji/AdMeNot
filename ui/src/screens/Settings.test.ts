import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import App from '../App.svelte';
import { i18n } from '../lib/i18n/index.svelte';
import { setupCtl } from '../test-utils';

test('settings: theme, language, mode, adb check, folder and save', async () => {
  const { ctl, s, bridge } = await setupCtl('empty');
  render(App, { props: { ctl } });
  await fireEvent.click(screen.getByRole('button', { name: 'Ustawienia' }));
  await tick();
  expect(screen.getByRole('group', { name: 'Motyw' })).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Ciemny' }));
  await vi.waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ theme: 'dark' }] });
  await fireEvent.click(screen.getByRole('button', { name: 'System' }));
  await vi.waitFor(() => expect(document.documentElement.dataset.theme).toBe('light'));
  await fireEvent.click(screen.getByRole('button', { name: 'Ekspercki' }));
  await vi.waitFor(() => expect(s.settings.mode).toBe('expert'));
  const adb = screen.getByLabelText('Ścieżka do adb.exe');
  await fireEvent.input(adb, { target: { value: 'C:\\pt\\adb.exe' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Sprawdź' }));
  expect(await screen.findByText(/Działa: Android Debug Bridge/)).toBeTruthy();
  expect(bridge.calls.at(-1)).toEqual({ method: 'check_adb', args: ['C:\\pt\\adb.exe'] });
  await fireEvent.click(screen.getByRole('button', { name: 'Wybierz…' }));
  await vi.waitFor(() => expect((screen.getByLabelText('Katalog kopii APK') as HTMLInputElement).value)
    .toBe('D:\\DeMalware\\kopie'));
  await fireEvent.click(screen.getByRole('button', { name: 'Zapisz' }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings',
    args: [{ adb_path: 'C:\\pt\\adb.exe', backups_dir: 'D:\\DeMalware\\kopie' }] });
  expect(await screen.findByText(/Zapisano/)).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'English' }));
  await vi.waitFor(() => expect(i18n.lang).toBe('en'));
  await tick();
  expect(screen.getByRole('heading', { name: 'Settings' })).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Polski' }));
  await vi.waitFor(() => expect(i18n.lang).toBe('pl'));
});
