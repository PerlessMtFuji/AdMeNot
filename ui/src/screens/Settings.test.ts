import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import ErrorCard from '../components/ErrorCard.svelte';
import { i18n } from '../lib/i18n/index.svelte';
import { renderWith, setupCtl } from '../test-utils';
import { CATEGORIES } from './settings/categories';
import Settings from './settings/Settings.svelte';

const NAMES = ['Ogólne', 'Naprawa', 'Przenoszenie danych', 'Eksplorator plików', 'Serwis i protokoły',
  'Prywatność i dane', 'Program'];

const nav = () => screen.getByRole('navigation', { name: 'Kategorie ustawień' });
const active = () => within(nav()).getAllByRole('button').find((b) => b.getAttribute('aria-current') === 'page');

async function search(value: string): Promise<HTMLInputElement> {
  const input = screen.getByRole('searchbox', { name: 'Szukaj ustawienia…' }) as HTMLInputElement;
  await fireEvent.input(input, { target: { value } });
  await tick();
  await tick();
  return input;
}

test('seven categories in spec order, „Ogólne” active with its header and lead', async () => {
  await renderWith(Settings);
  expect(CATEGORIES.map((c) => c.id)).toEqual(['general', 'repair', 'transfer', 'explorer', 'service', 'privacy', 'program']);
  const buttons = within(nav()).getAllByRole('button');
  expect(buttons.map((b) => b.textContent?.trim())).toEqual(NAMES);
  expect(active()?.textContent?.trim()).toBe('Ogólne');
  expect(screen.getByRole('heading', { level: 2, name: 'Ogólne' })).toBeTruthy();
  expect(screen.getByText('Wygląd programu i sposób pracy przy stanowisku.')).toBeTruthy();
});

test('clicking a category shows its header and is remembered for the session', async () => {
  const { s, ctl } = await renderWith(Settings);
  await fireEvent.click(within(nav()).getByRole('button', { name: 'Naprawa' }));
  expect(screen.getByRole('heading', { level: 2, name: 'Naprawa' })).toBeTruthy();
  expect(s.settingsCategory).toBe('repair');
  ctl.back();
  ctl.openSettings();
  expect(s.screen).toBe('settings');
  expect(s.settingsCategory).toBe('repair');
});

test('openSettings(category) switches the active category', async () => {
  const { ctl } = await renderWith(Settings);
  ctl.openSettings('program');
  await tick();
  expect(active()?.textContent?.trim()).toBe('Program');
  expect(screen.getByRole('heading', { level: 2, name: 'Program' })).toBeTruthy();
});

test('search shows matching rows under their category name, no hits shows one line, Esc clears', async () => {
  const { container } = await renderWith(Settings);
  const input = await search('adb.exe');
  const sections = [...container.querySelectorAll('[data-settings-section]')].filter((e) => !(e as HTMLElement).hidden);
  expect(sections.map((e) => e.getAttribute('data-settings-section'))).toEqual(['program']);
  expect(within(sections[0] as HTMLElement).getByRole('heading', { level: 2, name: 'Program' })).toBeTruthy();
  expect((container.querySelector('[data-setting-id="adb_path"]') as HTMLElement).hidden).toBe(false);
  await search('motyw');
  const shown = [...container.querySelectorAll('[data-settings-section]')].filter((e) => !(e as HTMLElement).hidden);
  expect(shown.map((e) => e.getAttribute('data-settings-section'))).toEqual(['general']);
  await search('zzz');
  expect(screen.getByText('Nic nie znaleziono')).toBeTruthy();
  await fireEvent.keyDown(input, { key: 'Escape' });
  await tick();
  expect(input.value).toBe('');
  expect(screen.queryByText('Nic nie znaleziono')).toBeNull();
  expect(screen.getByRole('heading', { level: 2, name: 'Ogólne' })).toBeTruthy();
});

test('a matching row that appears after an async load shows its category without another keystroke', async () => {
  const { container } = await renderWith(Settings);
  await search('limit');
  const repair = () => container.querySelector('[data-settings-section="repair"]') as HTMLElement;
  await vi.waitFor(() => expect(repair().hidden).toBe(false));
  expect(within(repair()).getByRole('heading', { level: 2, name: 'Naprawa' })).toBeTruthy();
  expect(screen.queryByText('Nic nie znaleziono')).toBeNull();
});

test('openSettings(current category) ends an ongoing search', async () => {
  const { ctl } = await renderWith(Settings);
  ctl.openSettings('program');
  await tick();
  const input = await search('adb');
  expect(screen.queryByRole('heading', { level: 2, name: 'Program' })).toBeTruthy(); // nagłówek sekcji wyników
  expect(screen.queryByText('Wersja, aktualizacje i narzędzia dla zaawansowanych.')).toBeNull();
  ctl.openSettings('program');
  await tick();
  expect(input.value).toBe('');
  expect(screen.getByText('Wersja, aktualizacje i narzędzia dla zaawansowanych.')).toBeTruthy();
});

test('„Zapisano” bubble after a successful save, gone after 2 s; not after a failed one', async () => {
  const { ctl, bridge } = await renderWith(Settings);
  expect(screen.queryByRole('status')).toBeNull();
  bridge.failNext('save_settings', 'internal');
  expect(await ctl.saveSettings({ mirror_auto: true })).toBeNull();
  await tick();
  expect(screen.queryByText('Zapisano')).toBeNull();
  expect(await ctl.saveSettings({ mirror_auto: true })).not.toBeNull();
  await tick();
  expect(screen.getByRole('status').textContent).toContain('Zapisano');
  await vi.waitFor(() => expect(screen.queryByText('Zapisano')).toBeNull(), { timeout: 3000 });
});

test('a save made before opening Settings does not show the bubble', async () => {
  const { ctl } = await setupCtl('empty');
  await ctl.saveSettings({ mirror_auto: true });
  render(Settings, { context: new Map([['ctl', ctl]]) });
  await tick();
  expect(screen.queryByText('Zapisano')).toBeNull();
});

test('orange dot at „Serwis i protokoły” while the service name is empty', async () => {
  const { ctl, container } = await renderWith(Settings);
  await vi.waitFor(() => expect(container.querySelector('[data-category="service"] [data-dot]')).toBeTruthy());
  expect(container.querySelectorAll('[data-dot]')).toHaveLength(1);
  await ctl.saveService({ name: 'Serwis Ząb' });
  await tick();
  expect(container.querySelector('[data-dot]')).toBeNull();
});

test('„Otwórz ustawienia” on the adb_missing error card opens „Program”', async () => {
  const { s } = await renderWith(ErrorCard);
  s.error = { key: 'adb_missing', message: '' };
  await tick();
  await fireEvent.click(screen.getByRole('button', { name: 'Otwórz ustawienia' }));
  expect(s.screen).toBe('settings');
  expect(s.settingsCategory).toBe('program');
  expect(s.error).toBeNull();
});

async function open(name: string): Promise<void> {
  await fireEvent.click(within(nav()).getByRole('button', { name }));
  await tick();
}

test('Ogólne: theme, language and mode are saved at once; no long-operation group yet', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  expect(screen.queryByText('Gdy trwa długa operacja')).toBeNull();
  expect(screen.getByText(/Ekspercki pokazuje tabelę, konsolę ADB/)).toBeTruthy();
  const theme = () => within(screen.getByRole('group', { name: 'Motyw' }));
  await fireEvent.click(theme().getByRole('button', { name: 'Ciemny' }));
  await vi.waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ theme: 'dark' }] });
  await fireEvent.click(theme().getByRole('button', { name: 'System' }));
  await vi.waitFor(() => expect(document.documentElement.dataset.theme).toBe('light'));
  await fireEvent.click(screen.getByRole('button', { name: 'Ekspercki' }));
  await vi.waitFor(() => expect(s.settings.mode).toBe('expert'));
  await fireEvent.click(screen.getByRole('button', { name: 'English' }));
  await vi.waitFor(() => expect(i18n.lang).toBe('en'));
  await tick();
  expect(screen.getByRole('heading', { level: 2, name: 'General' })).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Polski' }));
  await vi.waitFor(() => expect(i18n.lang).toBe('pl'));
});

test('Naprawa: screen view toggle, action when selected and APK analysis are saved at once', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  await open('Naprawa');
  await fireEvent.click(screen.getByRole('switch', { name: 'Otwieraj podgląd ekranu po podłączeniu' }));
  await vi.waitFor(() => expect(s.settings.mirror_auto).toBe(true));
  expect(bridge.calls.some((c) => c.method === 'save_settings' && (c.args[0] as { mirror_auto?: boolean }).mirror_auto === true)).toBe(true);
  const level = screen.getByRole('group', { name: 'Akcja po zaznaczeniu' });
  expect(within(level).getByRole('button', { name: 'Wycisz' }).getAttribute('aria-pressed')).toBe('true');
  await fireEvent.click(within(level).getByRole('button', { name: 'Wyłącz' }));
  await vi.waitFor(() => expect(s.settings.select_level).toBe('disable'));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ select_level: 'disable' }] });
  const apk = screen.getByRole('group', { name: 'Analiza APK po skanie' });
  expect(within(apk).getByRole('button', { name: 'Zawsze pełna' }).getAttribute('aria-pressed')).toBe('true');
  await fireEvent.click(within(apk).getByRole('button', { name: 'Zawsze ręcznie' }));
  await vi.waitFor(() => expect(s.settings.apk_mode_default).toBe('manual'));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ apk_mode_default: 'manual' }] });
});

test('Naprawa: APK cache bar, limit list, clear after repair and clear now', async () => {
  const { bridge } = await renderWith(Settings, 'empty');
  await open('Naprawa');
  expect(await screen.findByText('3,4 GB z 10 GB')).toBeTruthy();
  expect(screen.getByText(/Zajęte: 3,4 GB · limit 10 GB · teraz zmieści się 5,4 GB/)).toBeTruthy();
  const bar = screen.getByRole('progressbar');
  expect(Number(bar.getAttribute('aria-valuenow'))).toBe(34);
  const limit = screen.getByLabelText('Limit (GB)') as HTMLSelectElement;
  expect(limit.value).toBe('10');
  await fireEvent.change(limit, { target: { value: '5' } });
  await vi.waitFor(() => expect(bridge.calls).toContainEqual({ method: 'save_settings', args: [{ apk_cache_limit_gb: 5 }] }));
  await fireEvent.click(screen.getByRole('switch', { name: 'Czyść po zakończonej naprawie' }));
  await vi.waitFor(() => expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ apk_cache_clear_after_repair: true }] }));
  await fireEvent.click(screen.getByRole('button', { name: 'Wyczyść teraz' }));
  expect(await screen.findByText(/Usunięto 3,4 GB/)).toBeTruthy();
});

test('Naprawa: clear now says how much stayed when some files could not be removed', async () => {
  const { ctl } = await renderWith(Settings, 'empty');
  await open('Naprawa');
  await screen.findByText('3,4 GB z 10 GB');
  vi.spyOn(ctl, 'clearApkCache').mockResolvedValue({ freed_bytes: 1.7 * 1024 ** 3, left_bytes: 3.5 * 1024 ** 3 });
  await fireEvent.click(screen.getByRole('button', { name: 'Wyczyść teraz' }));
  expect(await screen.findByText(/Usunięto 1,7 GB/)).toBeTruthy();
  expect(screen.getByText(/Zostało 3,5 GB, których nie dało się usunąć/)).toBeTruthy();
});

test('Naprawa: clear now without leftovers shows only the success notice', async () => {
  await renderWith(Settings, 'empty');
  await open('Naprawa');
  await fireEvent.click(await screen.findByRole('button', { name: 'Wyczyść teraz' }));
  expect(await screen.findByText(/Usunięto 3,4 GB/)).toBeTruthy();
  expect(screen.queryByText(/nie dało się usunąć/)).toBeNull();
});

test('Naprawa: a rejected cache limit shows the message at the row, not the error card, and the list goes back', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  await open('Naprawa');
  const limit = (await screen.findByLabelText('Limit (GB)')) as HTMLSelectElement;
  bridge.failNext('save_settings', 'bad_request', 'apk_cache_limit_gb');
  await fireEvent.change(limit, { target: { value: '5' } });
  expect(await screen.findByText(/Limit nie może być większy niż dysk/)).toBeTruthy();
  expect(s.error).toBeNull();
  await vi.waitFor(() => expect(limit.value).toBe('10'));
  await fireEvent.change(limit, { target: { value: '5' } });
  await vi.waitFor(() => expect(screen.queryByText(/Limit nie może być większy niż dysk/)).toBeNull());
});

test('Naprawa: the backups folder is chosen with the picker and saved', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  await open('Naprawa');
  expect(screen.getByText('%LOCALAPPDATA%\\AdMeNot\\backups')).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Zmień…' }));
  await vi.waitFor(() => expect(s.settings.backups_dir).toBe('D:\\AdMeNot\\kopie'));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ backups_dir: 'D:\\AdMeNot\\kopie' }] });
  await fireEvent.click(screen.getByRole('button', { name: 'Domyślny' }));
  await vi.waitFor(() => expect(s.settings.backups_dir).toBeNull());
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ backups_dir: null }] });
});

test('Program: version and update state, check_updates toggle with its hint', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  s.settings.last_run_version = '0.9.5';
  s.update = { available: null, dismissed: false, retired: null, updated_to: null, updated_notes: null, installable: true };
  await open('Program');
  expect(screen.getByText('AdMeNot 0.9.5')).toBeTruthy();
  expect(screen.getByText('Masz najnowszą wersję')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Co nowego' })).toBeNull();
  s.update = { available: { version: '9.9.9', notes: 'Poprawki.', size: 1 }, dismissed: false, retired: null,
    updated_to: null, updated_notes: null, installable: true };
  await tick();
  expect(screen.getByText('Dostępna wersja 9.9.9')).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Co nowego' }));
  expect(s.updateDialog).toBe(true);
  const box = screen.getByRole('switch', { name: 'Sprawdzaj aktualizacje automatycznie' });
  expect(box.getAttribute('aria-checked')).toBe('true');
  await fireEvent.click(box);
  await vi.waitFor(() => expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ check_updates: false }] }));
  expect(screen.getByText(/nie dowie się o nowej ani o wycofanej wersji/)).toBeTruthy();
});

test('Program: support button opens the page, the reminders switch saves and goes back after an error', async () => {
  const { bridge, s } = await renderWith(Settings, 'empty');
  await open('Program');
  await fireEvent.click(screen.getByRole('button', { name: 'Wesprzyj projekt' }));
  await vi.waitFor(() => expect(bridge.calls.at(-1)).toEqual({ method: 'open_donate', args: [] }));
  const box = screen.getByRole('switch', { name: 'Przypominaj o wsparciu' });
  expect(box.getAttribute('aria-checked')).toBe('true');
  await fireEvent.click(box);
  await vi.waitFor(() => expect(s.settings.donate_reminders).toBe(false));
  expect(box.getAttribute('aria-checked')).toBe('false');
  bridge.failNext('set_donate_reminders', 'internal');
  await fireEvent.click(box);
  await vi.waitFor(() => expect(bridge.calls.at(-1)?.method).toBe('set_donate_reminders'));
  await vi.waitFor(() => expect(box.getAttribute('aria-checked')).toBe('false'));
});

test('Program: adb.exe pill shows source and version, change picks a file, check shows the result, default clears it', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  await open('Program');
  expect(await screen.findByText('dołączony · 1.0.41')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Domyślny' })).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Zmień…' }));
  await vi.waitFor(() => expect(s.settings.adb_path).toBe('C:\\pt\\adb.exe'));
  expect(bridge.calls.some((c) => c.method === 'pick_adb')).toBe(true);
  expect(bridge.calls).toContainEqual({ method: 'save_settings', args: [{ adb_path: 'C:\\pt\\adb.exe' }] });
  await fireEvent.click(screen.getByRole('button', { name: 'Sprawdź' }));
  expect(await screen.findByText(/Działa: Android Debug Bridge/)).toBeTruthy();
  expect(bridge.calls.at(-1)).toEqual({ method: 'check_adb', args: ['C:\\pt\\adb.exe'] });
  expect(screen.getByText(/· dołączony$/)).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Domyślny' }));
  await vi.waitFor(() => expect(s.settings.adb_path).toBeNull());
  expect(bridge.calls).toContainEqual({ method: 'save_settings', args: [{ adb_path: null }] });
});

test('Przenoszenie: folder is picked and reset to default (null), a bad folder shows the message at the row', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  await open('Przenoszenie danych');
  expect(screen.getByText('%LOCALAPPDATA%\\AdMeNot\\transfers')).toBeTruthy();
  await fireEvent.click(screen.getByRole('button', { name: 'Zmień…' }));
  await vi.waitFor(() => expect(s.settings.transfers_dir).toBe('D:\\AdMeNot\\kopie'));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ transfers_dir: 'D:\\AdMeNot\\kopie' }] });
  await fireEvent.click(screen.getByRole('button', { name: 'Domyślny' }));
  await vi.waitFor(() => expect(s.settings.transfers_dir).toBeNull());
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ transfers_dir: null }] });
  bridge.failNext('save_settings', 'bad_request', 'transfers_dir');
  await fireEvent.click(screen.getByRole('button', { name: 'Zmień…' }));
  expect(await screen.findByText(/Nie można użyć tego folderu\. Wybierz folder poza katalogiem danych programu\./)).toBeTruthy();
  expect(s.error).toBeNull();
  expect(s.settings.transfers_dir).toBeNull();
});

test('Przenoszenie: keep days list, preselect-apps and verify toggles are saved at once', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  await open('Przenoszenie danych');
  const days = screen.getByLabelText('Trzymaj kopie przez') as HTMLSelectElement;
  expect([...days.options].map((o) => o.textContent)).toEqual(['3 dni', '7 dni', '14 dni', '30 dni']);
  expect(days.value).toBe('7');
  await fireEvent.change(days, { target: { value: '30' } });
  await vi.waitFor(() => expect(s.settings.transfer_keep_days).toBe(30));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ transfer_keep_days: 30 }] });
  await fireEvent.click(screen.getByRole('switch', { name: 'Zaznaczaj aplikacje do przeniesienia' }));
  await vi.waitFor(() => expect(s.settings.transfer_apps_default).toBe(false));
  await fireEvent.click(screen.getByRole('switch', { name: 'Sprawdzaj bajt po bajcie' }));
  await vi.waitFor(() => expect(s.settings.verify_copies).toBe(true));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ verify_copies: true }] });
});

test('Eksplorator: view (Automatyczny = null), peek and hidden files are saved', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  await open('Eksplorator plików');
  const group = screen.getByRole('group', { name: 'Widok' });
  expect(within(group).getByRole('button', { name: 'Automatyczny' }).getAttribute('aria-pressed')).toBe('true');
  await fireEvent.click(within(group).getByRole('button', { name: 'Siatka' }));
  await vi.waitFor(() => expect(s.settings.explorer_view).toBe('grid'));
  await fireEvent.click(within(group).getByRole('button', { name: 'Automatyczny' }));
  await vi.waitFor(() => expect(s.settings.explorer_view).toBeNull());
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ explorer_view: null }] });
  await fireEvent.click(screen.getByRole('switch', { name: 'Podgląd pliku w dymku po najechaniu' }));
  await vi.waitFor(() => expect(s.settings.explorer_peek).toBe(false));
  await fireEvent.click(screen.getByRole('switch', { name: 'Pokazuj ukryte pliki i foldery' }));
  await vi.waitFor(() => expect(s.settings.explorer_hidden).toBe(true));
});

test('Eksplorator: Stały without a path opens the picker, cancel keeps the mode, the fixed row follows the mode', async () => {
  const { s, bridge, container } = await renderWith(Settings, 'empty');
  await open('Eksplorator plików');
  const group = screen.getByRole('group', { name: 'Folder docelowy' });
  expect(container.querySelector('[data-setting-id="explorer_dest_fixed"]')).toBeNull();
  bridge.answerNext('pick_folder', { path: null });
  await fireEvent.click(within(group).getByRole('button', { name: 'Stały' }));
  await tick();
  await tick();
  expect(s.settings.explorer_dest_mode).toBe('last');
  expect(bridge.calls.some((c) => c.method === 'save_settings')).toBe(false);
  await fireEvent.click(within(group).getByRole('button', { name: 'Stały' }));
  await vi.waitFor(() => expect(s.settings.explorer_dest_mode).toBe('fixed'));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ explorer_dest_mode: 'fixed', explorer_dest_fixed: 'D:\\AdMeNot\\kopie' }] });
  expect(container.querySelector('[data-setting-id="explorer_dest_fixed"]')).not.toBeNull();
  await fireEvent.click(within(group).getByRole('button', { name: 'Pytaj zawsze' }));
  await vi.waitFor(() => expect(s.settings.explorer_dest_mode).toBe('ask'));
  expect(container.querySelector('[data-setting-id="explorer_dest_fixed"]')).toBeNull();
});

test('Eksplorator: Stały folder is found by search only while the mode is fixed', async () => {
  const { ctl, container } = await renderWith(Settings, 'empty');
  await search('stały folder');
  const visible = () => [...container.querySelectorAll('[data-setting-id="explorer_dest_fixed"]')].filter((e) => !(e as HTMLElement).hidden);
  expect(visible()).toHaveLength(0);
  await ctl.saveSettings({ explorer_dest_mode: 'fixed', explorer_dest_fixed: 'D:\\Klienci' });
  await search('stały folder');
  expect(visible()).toHaveLength(1);
});

test('verify_copies is one setting: toggled in Przenoszenie, seen in Eksplorator', async () => {
  const { s } = await renderWith(Settings, 'empty');
  await open('Przenoszenie danych');
  await fireEvent.click(screen.getByRole('switch', { name: 'Sprawdzaj bajt po bajcie' }));
  await vi.waitFor(() => expect(s.settings.verify_copies).toBe(true));
  await open('Eksplorator plików');
  expect(screen.getByRole('switch', { name: 'Sprawdzaj bajt po bajcie' }).getAttribute('aria-checked')).toBe('true');
});

test('Eksplorator: recent phones use the Polish plural and Wyczyść clears them; at 0 the button is off', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  await open('Eksplorator plików');
  expect(screen.getByText('Nic nie zapamiętano')).toBeTruthy();
  expect((screen.getByRole('button', { name: 'Wyczyść' }) as HTMLButtonElement).disabled).toBe(true);
  for (const [n, text] of [[1, 'Pamiętane dla 1 telefonu'], [2, 'Pamiętane dla 2 telefonów'], [5, 'Pamiętane dla 5 telefonów'], [22, 'Pamiętane dla 22 telefonów']] as const) {
    s.settings = { ...s.settings, explorer_recent_phones: n };
    await tick();
    expect(screen.getByText(new RegExp(`^${text} `))).toBeTruthy();
  }
  await fireEvent.click(screen.getByRole('button', { name: 'Wyczyść' }));
  await vi.waitFor(() => expect(s.settings.explorer_recent_phones).toBe(0));
  expect(bridge.calls.at(-1)).toEqual({ method: 'explorer_clear_recents', args: [] });
  expect(screen.getByText('Nic nie zapamiętano')).toBeTruthy();
});

test('Eksplorator: folders remembered while browsing (after start) show up when the category opens', async () => {
  const { ctl, s, bridge } = await setupCtl('empty');
  expect(s.settings.explorer_recent_phones).toBe(0);
  // most zapisał „Ostatnio” przy `explorer_list`, UI nic o tym nie wie
  bridge.answerNext('get_settings', { ...s.settings, explorer_recent_phones: 2, theme: 'dark' });
  render(Settings, { context: new Map([['ctl', ctl]]) });
  await open('Eksplorator plików');
  expect(await screen.findByText(/^Pamiętane dla 2 telefonów /)).toBeTruthy();
  expect((screen.getByRole('button', { name: 'Wyczyść' }) as HTMLButtonElement).disabled).toBe(false);
  expect(s.settings.theme).toBe('system');  // odświeżamy tylko licznik, nie resztę ustawień
});

const saves = (bridge: { calls: { method: string; args: unknown[] }[] }) =>
  bridge.calls.filter((c) => c.method === 'save_service');

test('Serwis: a field is saved on blur only when changed, one call with that one key', async () => {
  const { bridge } = await renderWith(Settings, 'empty');
  await open('Serwis i protokoły');
  const name = await screen.findByLabelText('Nazwa serwisu');
  await fireEvent.blur(name);
  expect(saves(bridge)).toHaveLength(0);
  await fireEvent.input(name, { target: { value: 'Serwis Ząb' } });
  expect(saves(bridge)).toHaveLength(0);
  await fireEvent.blur(name);
  await vi.waitFor(() => expect(saves(bridge)).toHaveLength(1));
  expect(saves(bridge)[0].args).toEqual([{ name: 'Serwis Ząb' }]);
  await fireEvent.blur(name);
  expect(saves(bridge)).toHaveLength(1);
  const cases: [string, string, string][] = [['Adres serwisu', 'address', 'ul. Długa 1'], ['Telefon serwisu', 'phone', '600 000 000'],
    ['E-mail serwisu', 'email', 'a@b.pl'], ['NIP serwisu', 'nip', '123'], ['Strona serwisu', 'website', 'b.pl'],
    ['Serwisant na tym komputerze', 'technician', 'Jan'], ['Stopka protokołu', 'footer', 'Gwarancja\n30 dni']];
  for (const [label, key, value] of cases) {
    const field = screen.getByLabelText(label);
    await fireEvent.input(field, { target: { value } });
    await fireEvent.blur(field);
    await vi.waitFor(() => expect(saves(bridge).at(-1)?.args).toEqual([{ [key]: value }]));
  }
  expect(await screen.findByText('Zapisano')).toBeTruthy();
});

test('Serwis: logo is picked and saved; a logo error shows at the logo row, not on the error card', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  await open('Serwis i protokoły');
  const logoBtn = () => within(document.querySelector('[data-setting-id="service_logo"]') as HTMLElement).getByRole('button', { name: 'Zmień…' });
  await fireEvent.click(await vi.waitFor(logoBtn));
  await vi.waitFor(() => expect(saves(bridge).at(-1)?.args).toEqual([{ logo: 'D:\\AdMeNot\\logo.png' }]));
  bridge.failNext('save_service', 'logo_type', 'D:\\AdMeNot\\logo.png');
  await fireEvent.click(logoBtn());
  expect(await screen.findByText('Logo musi być plikiem PNG, JPG, WebP albo SVG.')).toBeTruthy();
  expect(s.error).toBeNull();
});

test('Serwis: the preview follows typing before save; empty name shows the missing-name notice', async () => {
  const { container } = await renderWith(Settings, 'empty');
  await open('Serwis i protokoły');
  const preview = await vi.waitFor(() => {
    const el = container.querySelector('[data-protocol-preview]') as HTMLElement;
    expect(el).toBeTruthy();
    return el;
  });
  expect(within(preview).getByText('Brak nazwy serwisu')).toBeTruthy();
  await fireEvent.input(screen.getByLabelText('Nazwa serwisu'), { target: { value: 'Serwis Ząb' } });
  await fireEvent.input(screen.getByLabelText('E-mail serwisu'), { target: { value: 'a@b.pl' } });
  await fireEvent.input(screen.getByLabelText('Serwisant na tym komputerze'), { target: { value: 'Jan Kowalski' } });
  await fireEvent.input(screen.getByLabelText('Stopka protokołu'), { target: { value: '<b>Gwarancja</b>\n30 dni' } });
  await tick();
  expect(within(preview).getByText('Serwis Ząb')).toBeTruthy();
  expect(within(preview).getByText(/a@b\.pl/)).toBeTruthy();
  expect(within(preview).getByText('Jan Kowalski')).toBeTruthy();
  expect(within(preview).queryByText('Brak nazwy serwisu')).toBeNull();
  expect(preview.querySelector('b')?.textContent).toBe('Serwis Ząb'); // HTML ze stopki jest tekstem, nie znacznikiem
  expect(preview.textContent).toContain('<b>Gwarancja</b>');
});

test('Serwis: a footer over 500 characters turns the counter red and is not saved', async () => {
  const { bridge } = await renderWith(Settings, 'empty');
  await open('Serwis i protokoły');
  const footer = await screen.findByLabelText('Stopka protokołu');
  await fireEvent.input(footer, { target: { value: 'x'.repeat(501) } });
  await tick();
  const counter = screen.getByText('501/500');
  expect(counter.className).toContain('text-bad');
  expect(screen.getByText(/Stopka jest za długa \(maks\. 500 znaków\) — nie zapisano/)).toBeTruthy();
  expect(document.querySelector('[data-protocol-preview]')?.textContent).not.toContain('xxxxx');
  await fireEvent.blur(footer);
  expect(saves(bridge)).toHaveLength(0);
  await fireEvent.input(footer, { target: { value: 'x'.repeat(500) } });
  await tick();
  expect(screen.getByText('500/500').className).not.toContain('text-bad');
  expect(screen.queryByText(/Stopka jest za długa/)).toBeNull();
  await fireEvent.blur(footer);
  await vi.waitFor(() => expect(saves(bridge)).toHaveLength(1));
});

test('Serwis: form fields are found by search', async () => {
  const { container } = await renderWith(Settings, 'empty');
  await search('nip');
  const rows = [...container.querySelectorAll('[data-setting-id]')].filter((e) => !(e as HTMLElement).hidden);
  expect(rows.map((e) => e.getAttribute('data-setting-id'))).toEqual(['service_nip']);
});

test('Serwis: PDF folder is picked, a bad folder shows the message at the row, report_open toggles', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  await open('Serwis i protokoły');
  expect(screen.queryByText('Język protokołu')).toBeNull();
  const row = () => document.querySelector('[data-setting-id="report_pdf_dir"]') as HTMLElement;
  await fireEvent.click(within(row()).getByRole('button', { name: 'Zmień…' }));
  await vi.waitFor(() => expect(s.settings.report_pdf_dir).toBe('D:\\AdMeNot\\kopie'));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ report_pdf_dir: 'D:\\AdMeNot\\kopie' }] });
  await fireEvent.click(within(row()).getByRole('button', { name: 'Domyślny' }));
  await vi.waitFor(() => expect(s.settings.report_pdf_dir).toBeNull());
  bridge.failNext('save_settings', 'bad_request', 'report_pdf_dir');
  await fireEvent.click(within(row()).getByRole('button', { name: 'Zmień…' }));
  expect(await screen.findByText(/Podaj pełną ścieżkę folderu/)).toBeTruthy();
  expect(s.error).toBeNull();
  const toggle = screen.getByRole('switch', { name: 'Otwieraj protokół po utworzeniu' });
  expect(toggle.getAttribute('aria-checked')).toBe('true');
  await fireEvent.click(toggle);
  await vi.waitFor(() => expect(s.settings.report_open).toBe(false));
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ report_open: false }] });
});

test('Serwis: the form is a two-column grid with each field still its own row', async () => {
  const { container } = await renderWith(Settings, 'empty');
  await open('Serwis i protokoły');
  const grid = (await vi.waitFor(() => {
    const g = container.querySelector('[data-setting-id="service_nip"]')?.parentElement as HTMLElement;
    expect(g).toBeTruthy();
    return g;
  }));
  expect(grid.className).toContain('grid-cols-2');
  const ids = [...grid.querySelectorAll(':scope > [data-setting-id]')].map((e) => e.getAttribute('data-setting-id'));
  expect(ids).toEqual(['service_name', 'service_address', 'service_phone', 'service_email', 'service_nip',
    'service_website', 'service_technician', 'service_logo', 'service_footer']);
  expect(grid.querySelector('[data-setting-id="service_address"]')?.className).toContain('col-span-2');
});

const PRIVACY_ID = '3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b';

test('Prywatność: retention list has „nie usuwaj” and 30…365 and saves at once', async () => {
  const { s, bridge } = await renderWith(Settings, 'empty');
  await open('Prywatność i dane');
  const select = screen.getByRole('combobox', { name: 'Usuwaj zlecenia starsze niż' }) as HTMLSelectElement;
  expect([...select.options].map((o) => o.textContent?.trim())).toEqual(
    ['nie usuwaj', '30 dni', '60 dni', '90 dni', '180 dni', '365 dni']);
  expect(select.value).toBe('60');
  await fireEvent.change(select, { target: { value: '' } });
  await vi.waitFor(() => expect(s.settings.retention_days).toBeNull());
  expect(bridge.calls.at(-1)).toEqual({ method: 'save_settings', args: [{ retention_days: null }] });
  await fireEvent.change(select, { target: { value: '365' } });
  await vi.waitFor(() => expect(s.settings.retention_days).toBe(365));
  expect(screen.queryByText(/Miejsce na dysku/)).toBeNull();
});

test('Prywatność: consent shows the ID, withdrawing shows the pending deletion; packages row follows', async () => {
  const { bridge } = await renderWith(Settings, 'empty');
  await open('Prywatność i dane');
  const stats = screen.getByRole('switch', { name: 'Wysyłaj anonimowe statystyki użycia' });
  const pkgs = screen.getByRole('switch', { name: /Dołącz nazwy pakietów/ }) as HTMLButtonElement;
  expect(pkgs.disabled).toBe(true);
  expect(pkgs.closest('[data-setting-id]')?.className).toContain('bg-surface-2');
  await fireEvent.click(stats);
  await screen.findByText(PRIVACY_ID);
  expect(pkgs.disabled).toBe(false);
  await fireEvent.click(stats);
  await screen.findByText('Usuwanie danych z serwera czeka na połączenie z internetem.');
  expect(screen.queryByText(PRIVACY_ID)).toBeNull();
  expect(bridge.calls.filter((c) => c.method === 'set_telemetry').map((c) => c.args)).toEqual([[true, false], [false, false]]);
});

test('Prywatność: a failed consent save puts the switch back', async () => {
  const { bridge } = await renderWith(Settings, 'empty');
  await open('Prywatność i dane');
  bridge.failNext('set_telemetry', 'internal');
  const stats = screen.getByRole('switch', { name: 'Wysyłaj anonimowe statystyki użycia' });
  await fireEvent.click(stats);
  await vi.waitFor(() => expect(bridge.calls.some((c) => c.method === 'set_telemetry')).toBe(true));
  await vi.waitFor(() => expect(stats.getAttribute('aria-checked')).toBe('false'));
});

test('Prywatność: Skopiuj copies the ID; a refused clipboard raises no unhandled rejection', async () => {
  const { s } = await renderWith(Settings, 'empty');
  s.settings.telemetry = true;
  s.settings.telemetry_id = PRIVACY_ID;
  await open('Prywatność i dane');
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
  await fireEvent.click(screen.getByRole('button', { name: 'Skopiuj' }));
  expect(writeText).toHaveBeenCalledWith(PRIVACY_ID);
  expect((await screen.findByText('Skopiowano')).getAttribute('role')).toBe('status');
  const seen = vi.fn();
  window.addEventListener('unhandledrejection', seen);
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: () => Promise.reject(new Error('denied')) } });
  await fireEvent.click(screen.getByRole('button', { name: 'Skopiuj' }));
  await new Promise((r) => setTimeout(r, 20));
  window.removeEventListener('unhandledrejection', seen);
  vi.unstubAllGlobals();
  expect(seen).not.toHaveBeenCalled();
});

test('Prywatność: the delete-pending notice is a banner shown only while pending', async () => {
  const { s } = await renderWith(Settings, 'empty');
  await open('Prywatność i dane');
  expect(screen.queryByText('Usuwanie danych z serwera czeka na połączenie z internetem.')).toBeNull();
  s.settings.telemetry_delete_pending = true;
  await tick();
  expect(screen.getByText('Usuwanie danych z serwera czeka na połączenie z internetem.')).toBeTruthy();
});

test('Prywatność: „Pokaż ostrzeżenie o ryzyku” opens the warning dialog', async () => {
  await renderWith(Settings, 'empty');
  await open('Prywatność i dane');
  await fireEvent.click(screen.getByRole('button', { name: 'Pokaż ostrzeżenie o ryzyku' }));
  await screen.findByText('AdMeNot jest w wersji beta i może zawierać błędy.');
});
