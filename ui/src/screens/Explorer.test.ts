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

  test('double-clicking "Files" opens the explorer once', async () => {
    const env = await setupCtl('explorer');
    render(App, { props: { ctl: env.ctl } });
    const files = screen.getByRole('button', { name: 'Pliki' });
    // drugi klik, zanim most odpowie na pierwszy
    void fireEvent.click(files);
    void fireEvent.click(files);
    await vi.waitFor(() => expect(env.s.screen).toBe('explorer'));
    expect(env.bridge.calls.filter((c) => c.method === 'explorer_open')).toHaveLength(1);
  });

  test('"Upload" from the history closes the explorer first, so the phone is free', async () => {
    const { ctl, bridge } = await openExplorer();
    await ctl.planRestore('OLD/20261031-173908');
    const methods = bridge.calls.map((c) => c.method);
    expect(methods.indexOf('explorer_close')).toBeGreaterThan(-1);
    expect(methods.indexOf('explorer_close')).toBeLessThan(methods.indexOf('restore_plan'));
    expect(ctl.explorer.state.open).toBe(false);
  });

  test('the selection bar copies to the remembered PC folder; the first copy asks for the folder', async () => {
    const { bridge, ctl } = await openExplorer();
    await fireEvent.click(rows()[0]);
    await fireEvent.click(rows()[1], { ctrlKey: true });
    const bar = await screen.findByRole('region', { name: 'Zaznaczenie' });
    expect(bar.textContent).toContain('2 zaznaczone');
    expect(within(bar).getByRole('button', { name: /Wybierz folder na komputerze/ })).toBeTruthy();
    await fireEvent.click(within(bar).getByRole('button', { name: 'Kopiuj' }));
    await vi.waitFor(() => expect(bridge.calls.some((c) => c.method === 'explorer_copy')).toBe(true));
    const methods = bridge.calls.map((c) => c.method);
    expect(methods.indexOf('explorer_pick_dest')).toBeLessThan(methods.indexOf('explorer_copy'));
    const copy = bridge.calls.find((c) => c.method === 'explorer_copy')!;
    expect(copy.args[1]).toBe('D:\\Serwis\\Kowalska');
    expect(copy.args[2]).toBe(false);
    expect((copy.args[0] as string[]).length).toBe(2);
    await vi.waitFor(() => expect(screen.getByText('Kopiowanie na komputer')).toBeTruthy());
    // druga kopia: folder zapamiętany, „Sprawdź co do bajtu” z menu „⋯”
    await fireEvent.click(rows()[2]);
    const bar2 = await screen.findByRole('region', { name: 'Zaznaczenie' });
    expect(within(bar2).getByRole('button', { name: /Kowalska/ })).toBeTruthy();
    await fireEvent.click(within(bar2).getByRole('button', { name: 'Więcej' }));
    await fireEvent.click(screen.getByRole('menuitem', { name: /Sprawdź co do bajtu/ }));
    await vi.waitFor(() => expect(bridge.calls.filter((c) => c.method === 'explorer_copy')).toHaveLength(2));
    expect(bridge.calls.filter((c) => c.method === 'explorer_copy')[1].args.slice(1)).toEqual(['D:\\Serwis\\Kowalska', true]);
    expect(bridge.calls.filter((c) => c.method === 'explorer_pick_dest')).toHaveLength(1);
    expect(ctl.explorer.state.tasks).toHaveLength(2);
  });

  test('Ctrl+V uploads the Windows clipboard to the current folder; not inside the search box', async () => {
    const { bridge } = await openExplorer();
    await fireEvent.keyDown(screen.getByRole('searchbox'), { key: 'v', ctrlKey: true });
    expect(bridge.calls.some((c) => c.method === 'explorer_clipboard')).toBe(false);
    await fireEvent.keyDown(window, { key: 'v', ctrlKey: true });
    await vi.waitFor(() => expect(bridge.calls.some((c) => c.method === 'explorer_upload')).toBe(true));
    expect(bridge.calls.find((c) => c.method === 'explorer_upload')?.args)
      .toEqual([['C:\\Users\\serwis\\Documents\\faktura.pdf'], '/sdcard/DCIM/Camera']);
  });

  test('"Upload here" picks files or a folder and uploads them to the current folder', async () => {
    const { bridge } = await openExplorer();
    await fireEvent.click(screen.getByRole('button', { name: 'Wgraj tutaj' }));
    await fireEvent.click(screen.getByRole('menuitem', { name: /Folder/ }));
    await vi.waitFor(() => expect(bridge.calls.some((c) => c.method === 'explorer_upload')).toBe(true));
    expect(bridge.calls.find((c) => c.method === 'explorer_pick_upload')?.args).toEqual(['folder']);
    expect(bridge.calls.find((c) => c.method === 'explorer_upload')?.args)
      .toEqual([['C:\\Users\\serwis\\Desktop\\Faktury_2026'], '/sdcard/DCIM/Camera']);
  });

  test('problems before the start open a dialog with the concrete reason; nothing starts', async () => {
    const { bridge, ctl } = await openExplorer();
    bridge.answerNext('explorer_upload', { problems: [{ key: 'no_space',
      detail: { need: 3 * 1024 ** 3, free: 1.8 * 1024 ** 3, missing: 1.2 * 1024 ** 3 } }] });
    await fireEvent.keyDown(window, { key: 'v', ctrlKey: true });
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('brakuje 1,2 GB');
    expect(ctl.explorer.state.tasks).toHaveLength(0);
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Zamknij' }));
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  test('FAT32: the dialog lists files over 4 GB and can unselect them', async () => {
    const { bridge, ctl } = await openExplorer();
    const ex = ctl.explorer;
    ex.state.dest = 'E:\\';
    const [a, b] = rows().map((r) => r.dataset.path!);
    ex.select(a);
    ex.select(b, { ctrl: true });
    const big = a.split('/').pop()!;
    bridge.answerNext('explorer_copy', { problems: [{ key: 'fat32_big', detail: { names: [big], max: 4294967295 } }] });
    await ex.copySelected();
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('FAT32');
    expect(within(dialog).getByText(big)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /mimo/i })).toBeNull();
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Odznacz te pliki' }));
    expect([...ex.state.selected]).toEqual([b]);
  });

  test('"New" creates a folder and a text file; a taken name is shown in the dialog', async () => {
    const { bridge } = await openExplorer();
    const create = async (item: RegExp) => {
      await fireEvent.click(screen.getByRole('button', { name: /^Nowy/ }));
      await fireEvent.click(screen.getByRole('menuitem', { name: item }));
      return screen.findByRole('dialog');
    };
    let dialog = await create(/^Folder/);
    const name = within(dialog).getByRole('textbox', { name: 'Nazwa' }) as HTMLInputElement;
    expect(name.value).toBe('Nowy folder');
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Utwórz' }));
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(bridge.calls.find((c) => c.method === 'explorer_mkdir')?.args).toEqual(['/sdcard/DCIM/Camera', 'Nowy folder']);

    dialog = await create(/Plik tekstowy/);
    await fireEvent.input(within(dialog).getByRole('textbox', { name: 'Nazwa' }), { target: { value: 'Lista zakupów' } });
    await fireEvent.input(within(dialog).getByRole('textbox', { name: 'Treść' }), { target: { value: 'mleko\nchleb' } });
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Utwórz' }));
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(bridge.calls.find((c) => c.method === 'explorer_new_text')?.args)
      .toEqual(['/sdcard/DCIM/Camera', 'Lista zakupów', 'mleko\nchleb']);

    dialog = await create(/^Folder/);
    await fireEvent.click(within(dialog).getByRole('button', { name: 'Utwórz' }));
    await vi.waitFor(() => expect(within(dialog).getByText('Plik albo folder o tej nazwie już tu jest.')).toBeTruthy());
    expect(screen.getByRole('dialog')).toBeTruthy();
  });

  test('files dropped from Windows show the drop zone and are uploaded to the current folder', async () => {
    const { bridge } = await openExplorer();
    const section = screen.getByRole('region', { name: 'Camera' });
    await fireEvent.dragEnter(section, { dataTransfer: { types: ['Files'], items: [{}, {}] } });
    expect(screen.getByText('Upuść, żeby wgrać do Camera')).toBeTruthy();
    bridge.emit('explorer:drop', { paths: ['C:\\Faktury_2026'], count: 660, bytes: 1.2 * 1024 ** 3 });
    await vi.waitFor(() => expect(bridge.calls.find((c) => c.method === 'explorer_upload')?.args)
      .toEqual([['C:\\Faktury_2026'], '/sdcard/DCIM/Camera']));
    await vi.waitFor(() => expect(screen.queryByText('Upuść, żeby wgrać do Camera')).toBeNull());
  });

  test('a finished upload to the current folder refreshes it once', async () => {
    const { bridge, ctl } = await openExplorer();
    await ctl.explorer.uploadPaths(['C:\\a.jpg']);
    const task = ctl.explorer.state.tasks[0];
    const lists = () => bridge.calls.filter((c) => c.method === 'explorer_list').length;
    const before = lists();
    bridge.emit('explorer:task', { task: { ...task, status: 'running' } });
    bridge.emit('explorer:task', { task: { ...task, status: 'done', done_files: 2 } });
    await vi.waitFor(() => expect(lists()).toBe(before + 1));
    bridge.emit('explorer:task', { task: { ...task, status: 'done', done_files: 2 } });
    await tick();
    expect(lists()).toBe(before + 1);
  });
});
