import { fireEvent, render, screen } from '@testing-library/svelte';
import { expect, test, vi } from 'vitest';
import WhoIsShowing from './WhoIsShowing.svelte';

test('who is showing: asks the phone and lists the packages literally', async () => {
  const ask = vi.fn().mockResolvedValue({
    resumed: { package: 'com.evil', name: '<b>Evil</b>' },
    overlays: [{ package: 'com.evil', name: '<b>Evil</b>' }], errors: [],
  });
  render(WhoIsShowing, { props: { ask } });
  await fireEvent.click(screen.getByRole('button', { name: 'Kto to wyświetla?' }));
  expect(ask).toHaveBeenCalledOnce();
  expect((await screen.findAllByText('<b>Evil</b>', { exact: false })).length).toBeGreaterThan(0);
});

test('who is showing: an unread window list is unknown, never "no windows"', async () => {
  const ask = vi.fn().mockResolvedValue({ resumed: null, overlays: null, errors: ['windows: timeout'] });
  render(WhoIsShowing, { props: { ask } });
  await fireEvent.click(screen.getByRole('button', { name: 'Kto to wyświetla?' }));
  expect(await screen.findByText('Nie udało się odczytać okien nad innymi aplikacjami.')).toBeTruthy();
  expect(screen.queryByText('Brak okien nad innymi aplikacjami.')).toBeNull();
  expect(screen.getByText('Nie udało się ustalić aplikacji na pierwszym planie.')).toBeTruthy();
});
