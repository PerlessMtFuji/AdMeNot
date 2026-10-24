import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { CHECKS_SAMPLE } from '../lib/fakeBridge';
import type { CheckBrowser, DeviceCheck } from '../lib/types';
import { renderWith, setupCtl } from '../test-utils';
import DeviceChecks from './DeviceChecks.svelte';

const CHROME = CHECKS_SAMPLE.browsers[0];
const SAMSUNG = CHECKS_SAMPLE.browsers[1];
const FIREFOX = CHECKS_SAMPLE.browsers[2];
const check = (browsers: CheckBrowser[], state: DeviceCheck['state'] = 'review'): DeviceCheck =>
  ({ id: 'site_notifications', state, state_label: state === 'ok' ? 'W porządku' : 'Do sprawdzenia', browsers });

async function mounted(checks: DeviceCheck[]) {
  const env = await renderWith(DeviceChecks, 'adware', {}, { checks });
  await env.ctl.startScan();
  await vi.waitFor(() => expect(env.s.job).toBeNull());
  await tick();
  return env;
}

async function scannedWith(checks: DeviceCheck[]) {
  const env = await setupCtl('adware', { checks });
  await env.ctl.startScan();
  await vi.waitFor(() => expect(env.s.job).toBeNull());
  return env;
}

const rechecks = (env: { bridge: { calls: { method: string }[] } }) =>
  env.bridge.calls.filter((c) => c.method === 'recheck_site_notifications').length;

afterEach(() => vi.useRealTimers());

describe('DeviceChecks', () => {
  test('stays folded while every check is ok, and opens on demand', async () => {
    await mounted([check([{ ...CHROME, sites: [CHROME.sites[2]] }], 'ok')]);
    const toggle = screen.getByRole('button', { name: /Powiadomienia z witryn/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.textContent).toContain('żadna strona nie może wysyłać powiadomień');
    expect(screen.queryByText('sklep.example')).toBeNull();
    await fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText(/Już wyłączone/)).toBeTruthy();
    expect(screen.getByText('sklep.example')).toBeTruthy();
  });

  test('is open when something needs a look; nothing is ticked up front', async () => {
    const { s } = await mounted([CHECKS_SAMPLE]);
    const toggle = screen.getByRole('button', { name: /Powiadomienia z witryn/ });
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    // Dwie witryny Chrome z poprawką i „wszystkie witryny” Samsung Internet.
    expect(toggle.textContent).toContain('3 do wyciszenia');
    for (const box of screen.getAllByRole('switch')) expect((box as HTMLInputElement).checked).toBe(false);
    expect(s.fixes.size).toBe(0);
  });

  test('an unreadable check shows nothing in the section', async () => {
    await mounted([{ id: 'site_notifications', state: 'unrecognized', state_label: 'Nie udało się odczytać', browsers: [] }]);
    expect(screen.queryByRole('region', { name: 'Stan telefonu' })).toBeNull();
  });

  test('one row per site to do, active first with its browser; already-off sites go to the footer', async () => {
    const [loud, quiet, off] = CHROME.sites;
    await mounted([check([{ ...CHROME, sites: [off, quiet, loud] }])]);
    const rows = screen.getAllByRole('listitem').map((li) => li.textContent ?? '');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toContain('tanie-bilety.example');
    expect(rows[0]).toContain('Chrome');
    expect(rows[0]).toContain('powiadomienie na ekranie');
    expect(rows[1]).toContain('wiadomosci.example');
    expect(rows[1]).toContain('może wysyłać powiadomienia');
    expect(screen.getAllByRole('switch')).toHaveLength(2);
    expect(screen.queryByRole('switch', { name: /sklep\.example/ })).toBeNull();
    expect(screen.getByText(/Już wyłączone/).parentElement!.textContent).toContain('sklep.example');
  });

  test('switching a site on adds its fix and the header counts it; off removes it', async () => {
    const { s } = await mounted([CHECKS_SAMPLE]);
    const box = screen.getByRole('switch', { name: 'Wycisz tanie-bilety.example' });
    await fireEvent.click(box);
    expect([...s.fixes]).toEqual([CHROME.sites[0].fix]);
    expect(screen.getByRole('button', { name: /Powiadomienia z witryn/ }).textContent).toContain('1 zaznaczona');
    await fireEvent.click(box);
    expect(s.fixes.size).toBe(0);
  });

  test('a shared-channel browser is one row: its on-screen sites, “silence all” and the “Blokuj” tip', async () => {
    const { s } = await mounted([check([SAMSUNG])]);
    const rows = screen.getAllByRole('listitem');
    expect(rows).toHaveLength(1);
    const row = rows[0];
    expect(within(row).getByText('Samsung Internet')).toBeTruthy();
    expect(row.textContent).toContain('Teraz na ekranie:');
    expect(within(row).getByText('reklamy.example')).toBeTruthy();
    expect(within(row).getByText(/dotknij „Blokuj”/)).toBeTruthy();
    const all = within(row).getByRole('switch', { name: 'Wszystkie witryny w Samsung Internet' });
    expect(row.textContent).toContain('Wycisz wszystkie');
    await fireEvent.click(all);
    expect([...s.fixes]).toEqual([SAMSUNG.all_fix]);
  });

  test('Firefox without debugging but with “silence all” stays a single row', async () => {
    const site = { host: 'push.example', origin: 'https://push.example', blocked: false, active: true, fix: null, fix_label: null };
    await mounted([check([{ ...FIREFOX, all_fix: 'site_all:org.mozilla.firefox', all_fix_label: 'x', sites: [site] }])]);
    const rows = screen.getAllByRole('listitem');
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain('push.example');
    expect(rows[0].textContent).toContain('Zdalne debugowanie przez USB');
    expect(within(rows[0]).getAllByRole('switch')).toHaveLength(1);
  });

  test('Firefox without remote debugging: its active sites get no “Blokuj” instruction', async () => {
    const site = { host: 'push.example', origin: 'https://push.example', blocked: false, active: true, fix: null, fix_label: null };
    await mounted([check([{ ...FIREFOX, mode: 'shared', read: 'partial', rdp_hint: true, sites: [site] }])]);
    expect(screen.getByText('push.example')).toBeTruthy();
    expect(screen.getByText(/Zdalne debugowanie przez USB/)).toBeTruthy();
    expect(screen.queryByText(/Blokuj/)).toBeNull();
    expect(screen.queryByText(/Na koniec wyłącz/)).toBeNull();
  });

  test('Firefox in rdp mode: a reminder to turn remote debugging off when done', async () => {
    const site = { host: 'push.example', origin: 'https://push.example', blocked: false, active: false,
      fix: 'site_perm:org.mozilla.firefox:https://push.example', fix_label: 'Blokada powiadomień: push.example (Firefox)' };
    await mounted([check([{ ...FIREFOX, mode: 'rdp', read: 'ok', rdp_hint: false, sites: [site] }])]);
    expect(screen.getByText('Na koniec wyłącz w Firefoxie „Zdalne debugowanie przez USB”')).toBeTruthy();
  });

  test('a browser the program cannot read gets a row with manual steps, not silence', async () => {
    const odd: CheckBrowser = { package: 'com.example.odd', name: 'Odd', mode: 'unknown', read: 'unsupported', rdp_hint: false,
      block_action: false, all_fix: null, all_fix_label: null, sites: [] };
    await mounted([check([odd])]);
    const row = screen.getByText('Odd').closest('li')!;
    expect(row.textContent).toContain('Ustawienia → Aplikacje → Odd → Powiadomienia');
    expect(row.textContent).toContain('sprawdź ręcznie');
    expect(within(row).queryByRole('switch')).toBeNull();
  });

  test('known browsers show a built-in icon, unknown ones an initial', async () => {
    const odd: CheckBrowser = { package: 'com.example.odd', name: 'Odd', mode: 'unknown', read: 'unsupported', rdp_hint: false,
      block_action: false, all_fix: null, all_fix_label: null, sites: [] };
    const { container } = await mounted([check([SAMSUNG, odd])]);
    const samsung = screen.getByText('Samsung Internet').closest('li')!;
    expect(samsung.querySelector('img[data-app-icon]')!.getAttribute('src')).toMatch(/samsung/);
    expect(screen.getByText('Odd').closest('li')!.querySelector('img')).toBeNull();
    expect(container.querySelectorAll('img[data-app-icon]').length).toBeGreaterThan(0);
  });

  test('origins and fix ids are never in the text; expert mode puts them in a tooltip', async () => {
    const { s } = await mounted([CHECKS_SAMPLE]);
    const host = screen.getByText('tanie-bilety.example');
    expect(screen.queryByText(CHROME.sites[0].origin)).toBeNull();
    expect(host.getAttribute('title')).toBeNull();
    s.settings = { ...s.settings, mode: 'expert' };
    await tick();
    expect(host.getAttribute('title')).toBe(`${CHROME.sites[0].origin} · ${CHROME.sites[0].fix}`);
    expect(screen.queryByText(CHROME.sites[0].fix!)).toBeNull();
  });

  test('Firefox without remote debugging: instruction, then quiet background re-reads until it is on', async () => {
    const env = await scannedWith([check([FIREFOX])]);
    vi.useFakeTimers();
    const view = render(DeviceChecks, { context: new Map([['ctl', env.ctl]]) });
    await tick();
    expect(screen.getByText(/Zdalne debugowanie przez USB/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Spróbuj|Ponów|Sprawdź ponownie/ })).toBeNull();
    expect(rechecks(env)).toBe(0);
    await vi.advanceTimersByTimeAsync(5000);
    expect(rechecks(env)).toBe(1);
    // w tle tylko tani odczyt gniazda debugowania
    expect(env.bridge.calls.filter((c) => c.method === 'recheck_site_notifications').at(-1)?.args).toEqual([true]);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(rechecks(env)).toBe(3);
    // Serwisant włączył debugowanie: następny odczyt oddaje witryny i polling się kończy.
    const site = { host: 'push.example', origin: 'https://push.example', blocked: false, active: false,
      fix: 'site_perm:org.mozilla.firefox:https://push.example', fix_label: 'Blokada powiadomień: push.example (Firefox)' };
    env.bridge.setChecks([check([{ ...FIREFOX, mode: 'rdp', read: 'ok', rdp_hint: false, sites: [site] }])]);
    await vi.advanceTimersByTimeAsync(5000);
    await tick();
    expect(env.s.scan!.device_checks[0].browsers[0].rdp_hint).toBe(false);
    expect(screen.getByText('push.example')).toBeTruthy();
    const after = rechecks(env);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(rechecks(env)).toBe(after);
    expect(screen.queryByText(/Bez debugowania widać/)).toBeNull();
    view.unmount();
  });

  test('polling stops when the section leaves the screen', async () => {
    const env = await scannedWith([check([FIREFOX])]);
    vi.useFakeTimers();
    const view = render(DeviceChecks, { context: new Map([['ctl', env.ctl]]) });
    await tick();
    await vi.advanceTimersByTimeAsync(5000);
    view.unmount();
    const before = rechecks(env);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(rechecks(env)).toBe(before);
  });

  test('no re-read while the plan or the client page is open: the fixes stay as previewed', async () => {
    const env = await scannedWith([check([FIREFOX, SAMSUNG])]);
    env.ctl.toggleFix(SAMSUNG.all_fix!);
    vi.useFakeTimers();
    const view = render(DeviceChecks, { context: new Map([['ctl', env.ctl]]) });
    // Firefox dostał zdalne debugowanie, a Samsung Internet nie oferuje już poprawki: odczyt zmieniłby plan.
    env.bridge.setChecks([check([{ ...FIREFOX, read: 'ok', rdp_hint: false }])]);
    env.s.plan = { apps: [], runnable: 1, code: 'K7F3' };
    await vi.advanceTimersByTimeAsync(15_000);
    expect(rechecks(env)).toBe(0);
    env.s.plan = null;
    env.s.share = { id: 'ui-1', code: 'K7F3', status: 'ready', url: 'https://x', mode: 'server', expires: null,
      upgraded: false, reason: null, offline: false };
    await vi.advanceTimersByTimeAsync(15_000);
    expect(rechecks(env)).toBe(0);
    expect([...env.s.fixes]).toEqual([SAMSUNG.all_fix]);
    env.s.share = null;
    await vi.advanceTimersByTimeAsync(5000);
    expect(rechecks(env)).toBe(1);
    expect(env.s.fixes.size).toBe(0);
    view.unmount();
  });

  test('a failed re-read stays silent: no error card, the next one is tried', async () => {
    const env = await scannedWith([check([FIREFOX])]);
    vi.useFakeTimers();
    const view = render(DeviceChecks, { context: new Map([['ctl', env.ctl]]) });
    env.bridge.failNext('recheck_site_notifications', 'busy');
    await vi.advanceTimersByTimeAsync(5000);
    expect(env.s.error).toBeNull();
    await vi.advanceTimersByTimeAsync(5000);
    expect(rechecks(env)).toBe(2);
    view.unmount();
  });
});
