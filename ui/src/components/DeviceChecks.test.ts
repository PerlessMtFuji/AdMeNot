import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test, vi } from 'vitest';
import { CHECKS_SAMPLE } from '../lib/fakeBridge';
import { phoneBadge } from '../lib/logic';
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

describe('DeviceChecks', () => {
  test('the card is always open: a static h2 header, no collapse button; ok shows the ok_sub sentence', async () => {
    await mounted([check([{ ...CHROME, sites: [CHROME.sites[2]] }], 'ok')]);
    const head = screen.getByRole('heading', { level: 2, name: 'Powiadomienia z witryn' });
    expect(screen.queryByRole('button', { name: /Powiadomienia z witryn/ })).toBeNull();
    expect(head.closest('[aria-expanded]')).toBeNull();
    expect(head.parentElement!.textContent).toContain('W porządku');
    expect(screen.getByText('żadna strona nie może wysyłać powiadomień')).toBeTruthy();
    expect(screen.getByText(/Już wyłączone/)).toBeTruthy();
    expect(screen.getByText('sklep.example')).toBeTruthy();
  });

  test('with something to do: intro sentence and counter pill in the header; nothing is ticked up front', async () => {
    const { s } = await mounted([CHECKS_SAMPLE]);
    const head = screen.getByRole('heading', { level: 2, name: 'Powiadomienia z witryn' });
    // Dwie witryny Chrome, Samsung Internet i Firefox bez debugowania — tyle co w liczniku zakładki.
    expect(head.parentElement!.textContent).toContain('4 do sprawdzenia');
    expect(screen.getByText(/Strony, którym ktoś pozwolił/)).toBeTruthy();
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
    expect(screen.getByRole('heading', { name: 'Powiadomienia z witryn' }).parentElement!.textContent).toContain('1 zaznaczona');
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
    expect(within(row).queryByText(/dotknij „Blokuj”/)).toBeNull();
    expect(within(row).queryByText(/nie pokazuje listy stron/)).toBeNull();
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
    expect(rows[0].textContent).toContain('Włącz w Firefoksie zdalne debugowanie');
    expect(within(rows[0]).getAllByRole('switch')).toHaveLength(1);
  });

  test('Firefox without remote debugging: its active sites get no “Blokuj” instruction', async () => {
    const site = { host: 'push.example', origin: 'https://push.example', blocked: false, active: true, fix: null, fix_label: null };
    await mounted([check([{ ...FIREFOX, mode: 'shared', read: 'partial', rdp_hint: true, sites: [site] }])]);
    expect(screen.getByText('push.example')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'szczegóły: Firefox' }));
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

  test('a browser the program cannot read: name and pill, the steps fold under “jak sprawdzić”', async () => {
    const odd: CheckBrowser = { package: 'com.example.odd', name: 'Odd', mode: 'unknown', read: 'unsupported', rdp_hint: false,
      block_action: false, all_fix: null, all_fix_label: null, sites: [] };
    await mounted([check([odd])]);
    const row = screen.getByText('Odd').closest('li')!;
    expect(row.textContent).toContain('sprawdź ręcznie');
    expect(within(row).queryByRole('switch')).toBeNull();
    expect(screen.queryByText(/Ustawienia → Aplikacje → Odd → Powiadomienia/)).toBeNull();
    const how = within(row).getByRole('button', { name: 'jak sprawdzić: Odd' });
    expect(how.getAttribute('aria-expanded')).toBe('false');
    await fireEvent.click(how);
    expect(how.getAttribute('aria-expanded')).toBe('true');
    expect(how.textContent).toContain('ukryj');
    expect(row.textContent).toContain('Ustawienia → Aplikacje → Odd → Powiadomienia');
    await fireEvent.click(how);
    expect(screen.queryByText(/Ustawienia → Aplikacje → Odd → Powiadomienia/)).toBeNull();
  });

  test('a site row hides the “Blokuj” instruction under “szczegóły: host”', async () => {
    const site = { host: 'push.example', origin: 'https://push.example', blocked: false, active: true, fix: null, fix_label: null };
    await mounted([check([{ ...SAMSUNG, all_fix: null, all_fix_label: null, mode: 'per_site', sites: [site] }])]);
    expect(screen.queryByText(/dotknij „Blokuj”/)).toBeNull();
    const btn = screen.getByRole('button', { name: 'szczegóły: push.example' });
    expect(btn.getAttribute('aria-expanded')).toBe('false');
    await fireEvent.click(btn);
    expect(btn.getAttribute('aria-expanded')).toBe('true');
    expect(btn.textContent).toContain('ukryj');
    expect(screen.getByText(/dotknij „Blokuj”/)).toBeTruthy();
    await fireEvent.click(btn);
    expect(screen.queryByText(/dotknij „Blokuj”/)).toBeNull();
  });

  test('Samsung Internet: only name, on-screen sites and “silence all” up front; the rest under “szczegóły”', async () => {
    await mounted([check([SAMSUNG])]);
    const row = screen.getAllByRole('listitem')[0];
    expect(row.textContent).toContain('Teraz na ekranie:');
    expect(row.textContent).toContain('Wycisz wszystkie');
    expect(screen.queryByText(/nie pokazuje listy stron/)).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'szczegóły: Samsung Internet' }));
    expect(screen.getByText(/nie pokazuje listy stron/)).toBeTruthy();
    expect(screen.getByText(/dotknij „Blokuj”/)).toBeTruthy();
  });

  test('Firefox with the debugging hint: one short call to action and a spinner; the full path under “szczegóły”', async () => {
    const { container } = await mounted([check([FIREFOX])]);
    expect(screen.getByText('Włącz w Firefoksie zdalne debugowanie, żeby wyciszać każdą stronę osobno.')).toBeTruthy();
    expect(container.querySelector('.spin')).not.toBeNull();
    expect(screen.queryByText(/Zdalne debugowanie przez USB/)).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'szczegóły: Firefox' }));
    expect(screen.getByText(/Zdalne debugowanie przez USB/)).toBeTruthy();
  });

  test('the header pill counts rows like the tab badge', async () => {
    const odd: CheckBrowser = { package: 'com.example.odd', name: 'Odd', mode: 'unknown', read: 'unsupported', rdp_hint: false,
      block_action: false, all_fix: null, all_fix_label: null, sites: [] };
    const c = check([{ ...CHROME, sites: [CHROME.sites[0], CHROME.sites[1]] }, SAMSUNG, odd]);
    await mounted([c]);
    const head = screen.getByRole('heading', { level: 2, name: 'Powiadomienia z witryn' });
    expect(head.parentElement!.textContent).toContain('4 do sprawdzenia');
    expect(phoneBadge([c])).toEqual({ kind: 'count', count: 4 });
  });

  test('an empty list with only already-silenced sites still draws the footer separator', async () => {
    await mounted([check([{ ...CHROME, sites: [CHROME.sites[2]] }])]);
    const footer = screen.getByText(/Już wyłączone/).closest('div')!;
    expect(footer.className).toContain('mt-3');
    expect(footer.className).toContain('border-t');
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

  test('the section itself does not re-read Firefox: that is the repair screen’s job (spec §8a.5)', async () => {
    const env = await setupCtl('adware', { checks: [check([FIREFOX])] });
    await env.ctl.startScan();
    await vi.waitFor(() => expect(env.s.job).toBeNull());
    vi.useFakeTimers();
    try {
      render(DeviceChecks, { context: new Map([['ctl', env.ctl]]) });
      await tick();
      expect(screen.getByText(/zdalne debugowanie/)).toBeTruthy();
      await vi.advanceTimersByTimeAsync(15_000);
      expect(env.bridge.calls.filter((c) => c.method === 'recheck_site_notifications')).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
