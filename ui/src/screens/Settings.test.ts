import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import App from '../App.svelte';
import { i18n } from '../lib/i18n/index.svelte';
import { renderWith, setupCtl } from '../test-utils';
import Settings from './Settings.svelte';

const flush = () => new Promise((r) => setTimeout(r, 0));

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

test('settings: service details and logo', async () => {
  const { ctl, bridge } = await setupCtl('empty');
  render(App, { props: { ctl } });
  await fireEvent.click(screen.getByRole('button', { name: 'Ustawienia' }));
  const name = await screen.findByLabelText('Nazwa serwisu');
  await fireEvent.input(name, { target: { value: 'Serwis Ząb' } });
  await fireEvent.input(screen.getByLabelText('Telefon serwisu'), { target: { value: '600 000 000' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Wybierz logo…' }));
  await vi.waitFor(() => expect((screen.getByLabelText('Logo') as HTMLInputElement).value)
    .toBe('D:\\DeMalware\\logo.png'));
  await fireEvent.click(screen.getByRole('button', { name: 'Zapisz dane serwisu' }));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_service', args: [{
    name: 'Serwis Ząb', address: null, phone: '600 000 000', logo: 'D:\\DeMalware\\logo.png' }] });
  expect(await screen.findByText(/Zapisano/)).toBeTruthy();
});

test('screen view setting and adb source', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  const toggle = screen.getByRole('checkbox', { name: 'Otwieraj podgląd ekranu po podłączeniu telefonu' });
  await fireEvent.click(toggle);
  await flush();
  expect(s.settings.mirror_auto).toBe(true);
  expect(bridge.calls.some((c) => c.method === 'save_settings' && (c.args[0] as { mirror_auto?: boolean }).mirror_auto === true)).toBe(true);
  await fireEvent.click(screen.getByRole('button', { name: 'Sprawdź' }));
  await flush();
  expect(screen.getByText(/· dołączony$/)).toBeTruthy();
});

test('action when an app is selected', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  const group = screen.getByRole('group', { name: 'Akcja po zaznaczeniu' });
  expect(within(group).getByRole('button', { name: 'Wycisz' }).getAttribute('aria-pressed')).toBe('true');
  await fireEvent.click(within(group).getByRole('button', { name: 'Wyłącz' }));
  await flush();
  expect(s.settings.select_level).toBe('disable');
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ select_level: 'disable' }] });
});

test('settings: APK cache limit, status, clear after repair and clear now', async () => {
  const { ctl, bridge } = await setupCtl('empty');
  render(App, { props: { ctl } });
  await fireEvent.click(screen.getByRole('button', { name: 'Ustawienia' }));
  expect(await screen.findByText(/Zajęte: 3,4 GB · limit 10 GB · teraz zmieści się 5,4 GB/)).toBeTruthy();
  const limit = screen.getByLabelText('Limit (GB)');
  await fireEvent.input(limit, { target: { value: '200' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Zapisz limit' }));
  expect(await screen.findByText(/Limit nie może być większy niż dysk/)).toBeTruthy();
  await fireEvent.input(limit, { target: { value: '5' } });
  await fireEvent.click(screen.getByRole('button', { name: 'Zapisz limit' }));
  await vi.waitFor(() => expect(bridge.calls).toContainEqual({ method: 'save_settings', args: [{ apk_cache_limit_gb: 5 }] }));
  await fireEvent.click(screen.getByLabelText('Po zakończonej naprawie usuń pamięć podręczną APK'));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ apk_cache_clear_after_repair: true }] });
  await fireEvent.click(screen.getByRole('button', { name: 'Wyczyść teraz' }));
  expect(await screen.findByText(/Usunięto 3,4 GB/)).toBeTruthy();
});
