import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import ErrorCard from '../components/ErrorCard.svelte';
import { renderWith, setupCtl } from '../test-utils';
import { CATEGORIES } from './settings/categories';
import Settings from './settings/Settings.svelte';

// Kategorie z wierszami do wyszukiwania; pozostałe zostają zaślepkami (wypełniają je kolejne zadania).
vi.mock('./settings/General.svelte', async () => ({ default: (await import('./settings/GeneralRows.test.svelte')).default }));
vi.mock('./settings/Program.svelte', async () => ({ default: (await import('./settings/ProgramRows.test.svelte')).default }));
vi.mock('./settings/Repair.svelte', async () => ({ default: (await import('./settings/AsyncRows.test.svelte')).default }));

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
  const input = await search('ADB');
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
