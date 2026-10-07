import { fireEvent, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test } from 'vitest';
import { renderWith } from '../test-utils';
import ErrorCard from './ErrorCard.svelte';

test('error card: translated key, serial, log path, dismiss', async () => {
  const { s } = await renderWith(ErrorCard);
  s.error = { key: 'wrong_device', message: 'R58T', serial: 'R58T', device: 'Samsung Galaxy A14', imei: '356789012345678' };
  await tick();
  expect(screen.getByRole('alert').textContent).toContain('Podłącz telefon Samsung Galaxy A14 (IMEI 356789012345678),');
  s.error = { key: 'wrong_device', message: 'R58T', serial: 'R58T', device: 'Samsung Galaxy A14', imei: null };
  await tick();
  expect(screen.getByRole('alert').textContent).toContain('Podłącz telefon Samsung Galaxy A14 (R58T),');
  s.error = { key: 'wrong_device', message: 'R58T', serial: 'R58T', device: 'R58T' }; // bez nazwy: sam numer
  await tick();
  expect(screen.getByRole('alert').textContent).toContain('Podłącz telefon R58T,');
  s.error = { key: 'something_new', message: 'x', log: 'C:\\logs\\app.log' };
  await tick();
  expect(screen.getByRole('alert').textContent).toContain('Nieoczekiwany błąd programu');
  expect(screen.getByRole('alert').textContent).toContain('C:\\logs\\app.log');
  await fireEvent.click(screen.getByRole('button', { name: 'Zamknij' }));
  expect(s.error).toBeNull();
});

test('fatal error offers a restart', async () => {
  const { s } = await renderWith(ErrorCard, 'empty', { fatal: true });
  s.fatal = 'TypeError: boom';
  await tick();
  expect(screen.getByRole('alert').textContent).toContain('TypeError: boom');
  expect(screen.getByRole('button', { name: 'Wróć do początku' })).toBeTruthy();
});
