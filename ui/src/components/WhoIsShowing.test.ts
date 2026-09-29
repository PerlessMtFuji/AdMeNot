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
