import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test, vi } from 'vitest';
import App from '../App.svelte';
import { setupCtl } from '../test-utils';

const SERIAL = 'R58T00TEST';

/** Okno programu z telefonem ze scenariusza `explorer`, eksplorator otwarty przyciskiem „Pliki”. */
async function openExplorer() {
  const env = await setupCtl('explorer');
  render(App, { props: { ctl: env.ctl } });
  await fireEvent.click(screen.getByRole('button', { name: 'Pliki' }));
  await vi.waitFor(() => expect(screen.getByRole('listbox', { name: 'Pliki w folderze' })).toBeTruthy());
  return env;
}

const crumbs = () => within(screen.getByRole('navigation', { name: 'Ścieżka' }))
  .getAllByRole('button').map((b) => b.textContent?.trim());
const rows = () => within(screen.getByRole('listbox', { name: 'Pliki w folderze' })).getAllByRole('option');
const row = (name: string) => rows().find((r) => r.textContent?.includes(name))!;
const selected = () => rows().filter((r) => r.getAttribute('aria-selected') === 'true').length;

describe('Explorer', () => {
  test('"Files" opens the explorer at the first place; place counts arrive in the background', async () => {
    const { s, bridge } = await openExplorer();
    expect(bridge.calls.find((c) => c.method === 'explorer_open')?.args).toEqual([SERIAL]);
    expect(bridge.calls.find((c) => c.method === 'explorer_list')?.args).toEqual(['/sdcard/DCIM/Camera']);
    expect(s.screen).toBe('explorer');
    expect(crumbs()).toEqual(['samsung SM-A145R', 'DCIM', 'Camera']);
    expect(rows()).toHaveLength(40);
    expect(screen.getByText('40 plików · 27 KB')).toBeTruthy();
    const places = screen.getByRole('navigation', { name: 'Miejsca' });
    await vi.waitFor(() => expect(within(places).getByRole('button', { name: /Cała pamięć/ }).textContent).toContain('50'));
    expect(within(places).getByRole('button', { name: /Aparat/ }).textContent).toContain('40');
    expect(within(places).getByRole('button', { name: /Pobrane/ }).textContent).toContain('4');
    expect(within(places).getByRole('button', { name: /Aparat/ }).getAttribute('aria-current')).toBe('location');
  });

  test('entering a folder updates the breadcrumbs; Backspace and a breadcrumb go up', async () => {
    const { bridge } = await openExplorer();
    await fireEvent.click(screen.getByRole('button', { name: /Cała pamięć/ }));
    await vi.waitFor(() => expect(crumbs()).toEqual(['samsung SM-A145R']));
    expect(rows().map((r) => r.textContent?.match(/Android|DCIM|Download|Movies|Music/)?.[0]))
      .toEqual(['Android', 'DCIM', 'Download', 'Movies', 'Music']);
    await fireEvent.dblClick(row('DCIM'));
    await vi.waitFor(() => expect(crumbs()).toEqual(['samsung SM-A145R', 'DCIM']));
    await fireEvent.keyDown(row('Camera'), { key: 'Enter' });
    await vi.waitFor(() => expect(crumbs()).toEqual(['samsung SM-A145R', 'DCIM', 'Camera']));
    await fireEvent.keyDown(window, { key: 'Backspace' });
    await vi.waitFor(() => expect(crumbs()).toEqual(['samsung SM-A145R', 'DCIM']));
    await fireEvent.click(screen.getByRole('button', { name: 'samsung SM-A145R' }));
    await vi.waitFor(() => expect(crumbs()).toEqual(['samsung SM-A145R']));
    expect(bridge.calls.filter((c) => c.method === 'explorer_list').map((c) => c.args[0])).toEqual(
      ['/sdcard/DCIM/Camera', '/sdcard', '/sdcard/DCIM', '/sdcard/DCIM/Camera', '/sdcard/DCIM', '/sdcard']);
    // Backspace w polu wyszukiwania nie wychodzi z folderu
    const search = screen.getByRole('searchbox');
    await fireEvent.keyDown(search, { key: 'Backspace' });
    expect(bridge.calls.filter((c) => c.method === 'explorer_list')).toHaveLength(6);
  });

  test('a locked folder explains itself instead of an error', async () => {
    await openExplorer();
    await fireEvent.click(screen.getByRole('button', { name: /Cała pamięć/ }));
    await vi.waitFor(() => expect(row('Android')).toBeTruthy());
    await fireEvent.dblClick(row('Android'));
    await vi.waitFor(() => expect(crumbs()).toEqual(['samsung SM-A145R', 'Android']));
    expect(row('data').querySelector('[data-locked]')).toBeTruthy();
    await fireEvent.dblClick(row('data'));
    await vi.waitFor(() => expect(screen.getByText('Android nie pozwala zajrzeć do tego folderu')).toBeTruthy());
  });

  test('click, Ctrl+click and Shift+click select like in Windows; Ctrl+A selects everything', async () => {
    const { ctl } = await openExplorer();
    const list = () => rows();
    await fireEvent.click(list()[0]);
    expect(selected()).toBe(1);
    await fireEvent.click(list()[3], { shiftKey: true });
    expect(selected()).toBe(4);
    await fireEvent.click(list()[1], { ctrlKey: true });
    expect(selected()).toBe(3);
    await fireEvent.click(list()[5], { ctrlKey: true, shiftKey: true });  // zakres od kotwicy (2.), dopisany
    expect(selected()).toBe(6);
    await fireEvent.click(list()[2]);
    expect(selected()).toBe(1);
    expect([...ctl.explorer.state.selected]).toEqual([list()[2].dataset.path]);
    await fireEvent.keyDown(window, { key: 'a', ctrlKey: true });
    expect(selected()).toBe(40);
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(selected()).toBe(0);
  });

  test('sorting by a column header and the type filter change the list', async () => {
    await openExplorer();
    await fireEvent.click(screen.getByRole('button', { name: /Cała pamięć/ }));
    await vi.waitFor(() => expect(row('Download')).toBeTruthy());
    await fireEvent.dblClick(row('Download'));
    await vi.waitFor(() => expect(rows()).toHaveLength(4));
    await fireEvent.click(screen.getByRole('button', { name: /^Nazwa/ }));
    const names = () => rows().map((r) => r.dataset.path!.split('/').pop());
    expect(names()).toEqual(['aplikacja.apk', 'faktura.pdf', 'notatka.txt', 'umowa.docx']);
    await fireEvent.click(screen.getByRole('button', { name: /^Nazwa/ }));
    expect(names()).toEqual(['umowa.docx', 'notatka.txt', 'faktura.pdf', 'aplikacja.apk']);
    await fireEvent.change(screen.getByRole('combobox', { name: 'Pokaż' }), { target: { value: 'apk' } });
    expect(names()).toEqual(['aplikacja.apk']);
  });

  test('"Back" closes the explorer on the bridge and returns to Connect', async () => {
    const { s, bridge } = await openExplorer();
    await fireEvent.click(screen.getByRole('button', { name: 'Wróć' }));
    await vi.waitFor(() => expect(bridge.calls.some((c) => c.method === 'explorer_close')).toBe(true));
    expect(s.screen).toBe('main');
    expect(s.phase).toBe('connect');
    expect(screen.getByRole('heading', { name: 'Połączono' })).toBeTruthy();
  });

  test('a disconnected phone shows a banner; it comes back on its own and the folder refreshes', async () => {
    const { bridge } = await openExplorer();
    bridge.emit('explorer:offline', { serial: SERIAL });
    await tick();
    expect(screen.getByText('Telefon odłączony')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Ponów|Spróbuj/ })).toBeNull();  // most wznowi sam
    const lists = bridge.calls.filter((c) => c.method === 'explorer_list').length;
    bridge.emit('explorer:online', { serial: SERIAL });
    await vi.waitFor(() => expect(bridge.calls.filter((c) => c.method === 'explorer_list')).toHaveLength(lists + 1));
    expect(screen.queryByText('Telefon odłączony')).toBeNull();
  });

  test('another phone plugged in closes the explorer: back on Connect with a banner', async () => {
    const { s, bridge } = await openExplorer();
    bridge.emit('explorer:closed', { serial: SERIAL, reason: 'other_phone' });
    await tick();
    expect(s.screen).toBe('main');
    expect(screen.getByText(/Podłączono inny telefon — eksplorator został zamknięty/)).toBeTruthy();
    expect(bridge.calls.some((c) => c.method === 'explorer_close')).toBe(false);  // most już zamknął
  });

  test('history and settings keep the explorer open; their back button returns to it', async () => {
    const { s, bridge } = await openExplorer();
    await fireEvent.click(screen.getByRole('button', { name: 'Ustawienia' }));
    expect(s.screen).toBe('settings');
    await fireEvent.click(screen.getByRole('button', { name: 'Ustawienia' }));
    expect(s.screen).toBe('explorer');
    expect(bridge.calls.some((c) => c.method === 'explorer_close')).toBe(false);
  });
});
