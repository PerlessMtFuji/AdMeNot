import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test } from 'vitest';
import { renderWith, setupCtl } from '../test-utils';
import Connect from './Connect.svelte';

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('Connect', () => {
  test('no phone: title, waiting stage, open guide with maker tabs, no scan button', async () => {
    const { container } = await renderWith(Connect, 'empty');
    expect(screen.getByRole('heading', { name: 'Podłącz telefon' })).toBeTruthy();
    expect(container.querySelector('[data-state="wait"]')).toBeTruthy();
    const checks = screen.getByRole('list', { name: 'Stan połączenia' }).querySelectorAll('li');
    expect([...checks].map((li) => li.dataset.status)).toEqual(['on', 'todo', 'todo']);
    await fireEvent.click(screen.getByRole('button', { name: 'Xiaomi / Redmi / POCO' }));
    // Selektor `li`: ten sam termin jest też w miniaturce (podświetlenie) — wystarczy sprawdzić
    // widoczny krok instrukcji.
    expect(screen.getByText(/ustawienia zabezpieczeń/, { selector: 'li' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Skanuj' })).toBeNull();
  });

  test('a ready phone shows its marketing name and IMEI, not the model code and serial', async () => {
    const env = await setupCtl('clean');
    env.s.devices = [{ serial: 'R58T00TEST', state: 'device', model: 'SM_A145R', name: 'Samsung Galaxy A14', imei: '499001200000004' }];
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    await tick();
    expect(screen.getByText('Samsung Galaxy A14')).toBeTruthy();
    expect(screen.getByText('IMEI 499001200000004')).toBeTruthy();
    expect(screen.queryByText('R58T00TEST')).toBeNull();
    env.s.devices = [{ serial: 'R58T00TEST', state: 'device', model: 'SM_A145R', name: null, imei: null }];
    await tick();
    expect(screen.getByText('SM A145R')).toBeTruthy();
    expect(screen.getByText('R58T00TEST')).toBeTruthy();
  });

  test('unauthorized phone asks for the permission on the phone', async () => {
    const { container } = await renderWith(Connect, 'unauthorized');
    expect(screen.getByRole('heading', { name: 'Potwierdź na telefonie' })).toBeTruthy();
    expect(container.querySelector('[data-state="auth"]')).toBeTruthy();
    expect(screen.getByText('Jak włączyć debugowanie USB')).toBeTruthy();
  });

  test('a phone scanned before starts with the guide collapsed', async () => {
    const env = await setupCtl('unauthorized');
    env.s.knownSerials = ['R58T00TEST'];
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    expect(screen.queryByText('Jak włączyć debugowanie USB')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Pokaż, jak włączyć debugowanie USB' }));
    expect(screen.getByText('Jak włączyć debugowanie USB')).toBeTruthy();
  });

  test('the guide collapses once the phone turns out to be known (history arrives after the first render)', async () => {
    const env = await setupCtl('unauthorized');
    env.s.knownSerials = [];
    render(Connect, { context: new Map([['ctl', env.ctl]]) });
    expect(screen.getByText('Jak włączyć debugowanie USB')).toBeTruthy();
    env.s.knownSerials = ['R58T00TEST'];
    await tick();
    expect(screen.queryByText('Jak włączyć debugowanie USB')).toBeNull();
    expect(screen.getByRole('button', { name: 'Pokaż, jak włączyć debugowanie USB' })).toBeTruthy();
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

  test('several phones: the screenshot button for the second phone does not steal the selection', async () => {
    const { s, bridge } = await renderWith(Connect, 'many');
    const before = s.serial;
    const shotButtons = screen.getAllByRole('button', { name: 'Zrzut ekranu' });
    expect(shotButtons).toHaveLength(2);
    // Przyciski podglądu/zrzutu nie mogą być potomkami <label> (klik trafiałby do radia).
    for (const button of shotButtons) expect(button.closest('label')).toBeNull();
    await fireEvent.click(shotButtons[1]);
    await flush();
    await tick();
    expect(bridge.calls.at(-1)).toEqual({ method: 'screenshot', args: ['HT7A1B2C3'] });
    expect(s.serial).toBe(before);
    const radios = screen.getAllByRole('radio') as HTMLInputElement[];
    expect(radios.map((r) => r.checked)).toEqual([before === 'R58T00TEST', before === 'HT7A1B2C3']);
  });

  test('one ready phone: connected card with scan; adb missing points to settings', async () => {
    const { s, container } = await renderWith(Connect, 'adware');
    expect(screen.getByRole('heading', { name: 'Połączono' })).toBeTruthy();
    expect(container.querySelector('[data-state="ok"]')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Skanuj' }) as HTMLButtonElement).disabled).toBe(false);
    s.devicesError = 'adb_missing';
    s.devices = [];
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Otwórz ustawienia' }));
    expect(s.screen).toBe('settings');
  });
});
