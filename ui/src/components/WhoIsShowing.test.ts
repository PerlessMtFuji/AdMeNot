import { fireEvent, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import { renderWith } from '../test-utils';
import WhoIsShowing from './WhoIsShowing.svelte';

const flush = () => new Promise((r) => setTimeout(r, 0));

test('who is showing: asks the phone and lists the packages literally', async () => {
  const ask = vi.fn().mockResolvedValue({
    resumed: { package: 'com.evil', name: '<b>Evil</b>' },
    overlays: [{ package: 'com.evil', name: '<b>Evil</b>' }], errors: [],
  });
  await renderWith(WhoIsShowing, 'empty', { ask });
  await fireEvent.click(screen.getByRole('button', { name: 'Kto to wyświetla?' }));
  expect(ask).toHaveBeenCalledOnce();
  expect((await screen.findAllByText('<b>Evil</b>', { exact: false })).length).toBeGreaterThan(0);
});

test('who is showing: an unread window list is unknown, never "no windows"', async () => {
  const ask = vi.fn().mockResolvedValue({ resumed: null, overlays: null, errors: ['windows: timeout'] });
  await renderWith(WhoIsShowing, 'empty', { ask });
  await fireEvent.click(screen.getByRole('button', { name: 'Kto to wyświetla?' }));
  expect(await screen.findByText('Nie udało się odczytać okien nad innymi aplikacjami.')).toBeTruthy();
  expect(screen.queryByText('Brak okien nad innymi aplikacjami.')).toBeNull();
  expect(screen.getByText('Nie udało się ustalić aplikacji na pierwszym planie.')).toBeTruthy();
});

test('offers the screen view and a screenshot with the description', async () => {
  const { s, bridge } = await renderWith(WhoIsShowing, 'empty', { ask: async () => ({ resumed: null, overlays: [], errors: [] }) });
  s.serial = 'R58T00TEST';
  await tick();
  await fireEvent.click(screen.getByRole('button', { name: 'Otwórz podgląd i poczekaj na reklamę' }));
  expect(bridge.calls.some((c) => c.method === 'mirror_start')).toBe(true);
  await fireEvent.click(screen.getByRole('button', { name: 'Kto to wyświetla?' }));
  await flush();
  await tick();
  await fireEvent.click(screen.getByRole('button', { name: 'Zapisz zrzut z tym opisem' }));
  await flush();
  expect(bridge.calls.some((c) => c.method === 'screenshot')).toBe(true);
});

test('a screenshot saved with the description is confirmed right under the button', async () => {
  const { s } = await renderWith(WhoIsShowing, 'empty', { ask: async () => ({ resumed: null, overlays: [], errors: [] }) });
  s.serial = 'R58T00TEST';
  await tick();
  await fireEvent.click(screen.getByRole('button', { name: 'Kto to wyświetla?' }));
  await flush();
  await tick();
  expect(screen.queryByText(/zrzut do protokołu/)).toBeNull();
  await fireEvent.click(screen.getByRole('button', { name: 'Zapisz zrzut z tym opisem' }));
  await flush();
  await tick();
  expect(screen.getByText('1 zrzut do protokołu')).toBeTruthy();
});

test('incident recording: mark the ad moment, then see who drew the window', async () => {
  const { s, bridge } = await renderWith(WhoIsShowing, 'empty', { ask: async () => null });
  s.device = { serial: 'S1' } as never;
  await tick();
  await fireEvent.click(screen.getByRole('button', { name: 'Nagraj zgłoszenie reklamy (2 min)' }));
  await flush();
  expect(bridge.calls.some((c) => c.method === 'start_incident' && c.args[0] === 120)).toBe(true);
  await fireEvent.click(await screen.findByRole('button', { name: 'Reklama jest teraz na ekranie' }));
  await flush();
  expect(bridge.calls.filter((c) => c.method === 'mark_incident')).toHaveLength(1);
  bridge.emit('incident:done', { marks: 1, hits: [
    { mark: 4, package: 'com.ads', name: 'Cleaner', kind: 'overlay', over: 'com.game', over_name: 'Game' },
  ] });
  await tick();
  expect(screen.getByText('Okno nad Game: Cleaner', { exact: false })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Reklama jest teraz na ekranie' })).toBeNull();
});

test('incident recording without a mark says nothing was attributed', async () => {
  const { s, bridge } = await renderWith(WhoIsShowing, 'empty', { ask: async () => null });
  s.device = { serial: 'S1' } as never;
  s.incident = { recording: true, marks: 0, result: null };
  await tick();
  bridge.emit('incident:done', { marks: 0, hits: [] });
  await tick();
  expect(screen.getByText('Nie zaznaczono chwili reklamy — nic nie przypisano.')).toBeTruthy();
});
