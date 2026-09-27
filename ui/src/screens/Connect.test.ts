import { fireEvent, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test } from 'vitest';
import { renderWith } from '../test-utils';
import Connect from './Connect.svelte';

describe('Connect', () => {
  test('no phone: waiting text and USB guide with tabs', async () => {
    await renderWith(Connect, 'empty');
    expect(screen.getByText(/Czekam na telefon/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Xiaomi / Redmi / POCO' }));
    expect(screen.getByText(/ustawienia zabezpieczeń/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Skanuj' }) as HTMLButtonElement).disabled).toBe(true);
  });

  test('unauthorized phone', async () => {
    await renderWith(Connect, 'unauthorized');
    expect(screen.getByText(/nieautoryzowany/)).toBeTruthy();
  });

  test('several phones: pick one, then scan', async () => {
    const { s, bridge } = await renderWith(Connect, 'many');
    const radios = screen.getAllByRole('radio');
    expect(radios).toHaveLength(2);
    await fireEvent.click(radios[1]);
    expect(s.serial).toBe('HT7A1B2C3');
    await fireEvent.input(screen.getByPlaceholderText('np. Anna K.'), { target: { value: 'Jan' } });
    expect(s.client).toBe('Jan');
    await fireEvent.click(screen.getByRole('button', { name: 'Skanuj' }));
    expect(bridge.calls.at(-1)).toEqual({ method: 'start_scan', args: ['HT7A1B2C3', 'Jan'] });
  });

  test('one ready phone is selected and adb missing points to settings', async () => {
    const { s } = await renderWith(Connect, 'adware');
    expect(screen.getByText(/Telefon gotowy/)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Skanuj' }) as HTMLButtonElement).disabled).toBe(false);
    s.devicesError = 'adb_missing';
    s.devices = [];
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Otwórz ustawienia' }));
    expect(s.screen).toBe('settings');
  });
});
