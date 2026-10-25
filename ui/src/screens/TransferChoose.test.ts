import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test } from 'vitest';
import { defaultTransferSelection } from '../lib/logic';
import type { InventoryView } from '../lib/types';
import { setupCtl } from '../test-utils';
import TransferChoose from './TransferChoose.svelte';

const MB = 1024 ** 2;

function inventory(over: Partial<InventoryView> = {}): InventoryView {
  return {
    contacts: 412, sms: 820, mms: 10, mms_bytes: 150 * MB, calls: 980,
    categories: { media: { files: 14210, bytes: 2000 * MB }, downloads: { files: 312, bytes: 300 * MB },
      whatsapp: { files: 40, bytes: 400 * MB } },
    others: [{ name: '', files: 3, bytes: 2 * MB }, { name: 'Music', files: 20, bytes: 500 * MB }],
    apps: [
      { package: 'pl.bank', label: 'Bank', verdict: 'safe', default_on: true, bytes: null },
      { package: 'com.sus.app', label: 'Latarka Pro', verdict: 'suspicious', default_on: false, bytes: null },
    ],
    skipped_apps: [{ package: 'com.clean.pro.boost', label: 'Cleaner' }],
    whatsapp_backup: new Date().toISOString().slice(0, 19), storage: { used: 50e9, total: 128e9 },
    free_pc: 500e9, unreadable: 0, ...over,
  };
}

async function show(over: Partial<InventoryView> = {}) {
  const env = await setupCtl('transfer');
  const inv = inventory(over);
  env.s.phase = 'transfer_choose';
  env.s.transfer.inventory = inv;
  env.s.transfer.selection = defaultTransferSelection(inv);
  const view = render(TransferChoose, { context: new Map([['ctl', env.ctl]]) });
  await tick();
  return { ...env, ...view };
}

const panelSize = () => within(screen.getByRole('complementary')).getByTestId('transfer-size').textContent;

describe('TransferChoose', () => {
  test('clicking a row changes the total in the side panel', async () => {
    await show();
    const before = panelSize();
    await fireEvent.click(screen.getByRole('checkbox', { name: /Zdjęcia i filmy/ }));
    expect(panelSize()).not.toBe(before);
    expect((screen.getByRole('checkbox', { name: /Zdjęcia i filmy/ }) as HTMLInputElement).checked).toBe(false);
  });

  test('suspicious apps are listed but unticked, harmful ones skipped', async () => {
    await show();
    expect(screen.getByText('1 podejrzana — odznaczona')).toBeTruthy();
    expect(screen.getByText('1 pominięta: szkodliwa')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Pokaż listę' }));
    expect((screen.getByRole('checkbox', { name: /Latarka Pro/ }) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole('checkbox', { name: /Bank/ }) as HTMLInputElement).checked).toBe(true);
  });

  test('loose files in the main folder get a name', async () => {
    await show();
    expect(screen.getByRole('checkbox', { name: /Pliki w folderze głównym/ })).toBeTruthy();
  });

  test('the start button is disabled when nothing is selected', async () => {
    const { s } = await show();
    expect((screen.getByRole('button', { name: /Rozpocznij kopię/ }) as HTMLButtonElement).disabled).toBe(false);
    s.transfer.selection = { contacts: false, sms: false, mms: false, calls: false, categories: [], others: [], apps: [] };
    await tick();
    expect((screen.getByRole('button', { name: /Rozpocznij kopię/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  test('an old WhatsApp chat backup shows the warning with a re-check', async () => {
    await show({ whatsapp_backup: '2020-01-01T02:00:00' });
    expect(screen.getByText(/Utwórz kopię/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Sprawdź ponownie' })).toBeTruthy();
  });

  test('unreadable messages are unticked with the Xiaomi hint on a Xiaomi phone', async () => {
    const { s } = await show({ sms: null, mms: null });
    s.device = { serial: 'R58T00TEST', manufacturer: 'Xiaomi', brand: 'Redmi' } as never;
    await tick();
    expect((screen.getByRole('checkbox', { name: /SMS i MMS/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Telefon nie pozwolił odczytać tych danych.')).toBeTruthy();
    expect(screen.getByText(/Debugowanie USB \(ustawienia zabezpieczeń\)/)).toBeTruthy();
  });

  test('other brands get the plain unreadable notice without the Xiaomi hint', async () => {
    const { s } = await show({ sms: null, mms: null });
    s.device = { serial: 'R58T00TEST', manufacturer: 'samsung', brand: 'samsung' } as never;
    await tick();
    expect(screen.getByText('Telefon nie pozwolił odczytać tych danych.')).toBeTruthy();
    expect(screen.queryByText(/Debugowanie USB \(ustawienia zabezpieczeń\)/)).toBeNull();
  });

  test('a selection bigger than the free disk space cannot start', async () => {
    await show({ free_pc: 100 * MB });
    expect(screen.getByText('Za mało miejsca na dysku komputera na tę kopię.')).toBeTruthy();
    expect((screen.getByRole('button', { name: /Rozpocznij kopię/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  test('the side panel shows the serial of the phone being copied', async () => {
    const { s } = await show();
    s.serial = 'OTHER123';
    s.device = { serial: 'R58T00TEST', name: 'samsung SM-A145R', model: 'SM-A145R', android: '14', image: '' } as never;
    await tick();
    const panel = within(screen.getByRole('complementary'));
    expect(panel.getByText('R58T00TEST')).toBeTruthy();
    expect(panel.queryByText('OTHER123')).toBeNull();
  });

  test('a resumable copy offers to resume it', async () => {
    const { s, bridge } = await show();
    s.transfer.resumable = { id: 'S/1', model: 'SM-A145R', manufacturer: 'samsung', client: null, created: '2026-10-24T14:20:00',
      expires: '2026-10-31T14:20:00', days_left: 6, status: 'in_progress', bytes: 0, counts: {} };
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Wznów' }));
    expect(bridge.calls.some((c) => c.method === 'start_backup')).toBe(true);
  });

  test('resuming needs free space only for the part not copied yet', async () => {
    // wybór ~3 GB; 2 GB już na dysku (wolne miejsce zmalało właśnie o nie), wolne 1,5 GB
    const { s } = await show({ free_pc: 1500 * MB });

    expect((screen.getByRole('button', { name: /Rozpocznij kopię/ }) as HTMLButtonElement).disabled).toBe(true);
    s.transfer.resumable = { id: 'S/1', model: 'SM-A145R', manufacturer: 'samsung', client: null, created: '2026-10-24T14:20:00',
      expires: '2026-10-31T14:20:00', days_left: 6, status: 'in_progress', bytes: 2000 * MB, counts: { files: 14000 } };
    await tick();
    expect(screen.queryByText('Za mało miejsca na dysku komputera na tę kopię.')).toBeNull();
    expect((screen.getByRole('button', { name: 'Wznów' }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole('button', { name: /Rozpocznij kopię/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  test('files the scan could not read are announced before the copy', async () => {
    await show({ unreadable: 3 });
    expect(screen.getByText('3 plików lub folderów nie dało się odczytać — nie trafią do kopii')).toBeTruthy();
  });

  test('no unreadable notice when the scan read everything', async () => {
    await show();
    expect(screen.queryByText(/nie dało się odczytać/)).toBeNull();
  });
});

