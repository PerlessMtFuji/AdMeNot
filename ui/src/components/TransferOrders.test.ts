import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { RECHECK_MS } from '../lib/recheck';
import type { CopyView, TransferOrderView } from '../lib/types';
import { setupCtl } from '../test-utils';
import TransferOrders from './TransferOrders.svelte';

const OLD_IMEI = '351111111111111';
const NEW_IMEI = '862222222222222';

const COPY: CopyView = { id: 'OLD/1', serial: 'SERIALOLD1', model: 'SM-A525F', manufacturer: 'samsung', client: 'Anna K.',
  created: '2026-10-25T14:20:00', expires: '2026-11-01T14:20:00', days_left: 7, status: 'complete', bytes: 10, counts: {},
  order: 'ZS/2026/1025/02', restores: [] };

const RESTORED: TransferOrderView = { number: 'ZS/2026/1025/02', client: 'Anna K.', created_at: '2026-10-25T14:20:00',
  source: { name: 'Samsung A52', imei: OLD_IMEI }, target: { name: 'OPPO A54', imei: NEW_IMEI }, state: 'restored_notes', notes: 2,
  copy: { id: 'OLD/1', days_left: 7, deleted_at: null }, whatsapp_restored: false, apps_blocked: false,
  counts: { contacts: 312, sms: 1204, files_photos: 1530, apps: 14, apps_malicious: 2 } };
const READY: TransferOrderView = { ...RESTORED, number: 'ZS/2026/1025/01', client: 'Jan N.', created_at: '2026-10-25T10:05:00',
  source: { name: 'Xiaomi Redmi 12', imei: '333333333333333' }, target: null, state: 'copy_ready', notes: 0,
  copy: { id: 'OLD/0', days_left: 7, deleted_at: null }, counts: {} };
const DELETED: TransferOrderView = { ...RESTORED, number: 'ZS/2026/1012/03', client: 'Ewa M.', created_at: '2026-10-12T09:00:00',
  source: { name: 'Motorola g54', imei: '444444444444444' }, target: { name: 'Samsung A35', imei: '555555555555555' }, state: 'restored', notes: 0,
  copy: { id: 'OLD/9', days_left: 0, deleted_at: '2026-10-19T08:00:00' }, counts: {} };
const INTERRUPTED: CopyView = { ...COPY, id: 'OLD/7', serial: 'SERIALOLD7', model: 'Moto G54', manufacturer: 'motorola', client: 'Piotr S.',
  created: '2026-10-20T12:00:00', status: 'in_progress', order: null };

afterEach(() => { vi.useRealTimers(); });

async function show(orders: TransferOrderView[], copies: CopyView[], connected: { serial: string; imei: string | null } | null = null) {
  const env = await setupCtl('clean');
  env.s.transfer.orders = orders;
  env.s.transfer.copies = copies;
  env.s.devices = connected ? [{ serial: connected.serial, state: 'device', model: 'M', name: null, imei: connected.imei }] : [];
  env.s.serial = connected?.serial ?? null;
  render(TransferOrders, { context: new Map([['ctl', env.ctl]]) });
  await tick();
  return env;
}

const row = (number: string) => screen.getByRole('article', { name: new RegExp(number) });
async function openMenu(number: string) {
  await fireEvent.click(within(row(number)).getByRole('button', { name: /^Więcej działań/ }));
}

describe('TransferOrders', () => {
  test('a restored order has Protokół on top and Przedłuż only in the menu', async () => {
    const env = await show([RESTORED], [COPY]);
    const r = row(RESTORED.number);
    expect(r.textContent).toContain('Samsung A52');
    expect(r.textContent).toContain('OPPO A54');
    expect(r.textContent).toContain('wgrano · 2 uwagi');
    expect(r.textContent).toContain('kopia jeszcze 7 dni');
    expect(within(r).getByRole('button', { name: 'Protokół' })).toBeTruthy();
    expect(within(r).queryByRole('button', { name: 'Przedłuż' })).toBeNull();
    expect(within(r).queryByRole('menuitem', { name: 'Przedłuż' })).toBeNull();
    await openMenu(RESTORED.number);
    expect(within(r).getByRole('menuitem', { name: 'Przedłuż' })).toBeTruthy();
    expect(within(r).getByRole('menuitem', { name: 'Usuń kopię' })).toBeTruthy();
    expect(within(r).queryByRole('menuitem', { name: 'Protokół' })).toBeNull();  // jest już na wierzchu
    await fireEvent.click(within(r).getByRole('menuitem', { name: 'Przedłuż' }));
    await vi.waitFor(() => expect(env.bridge.calls.some((c) => c.method === 'extend_transfer')).toBe(true));
  });

  test('the report button asks for the report of that order', async () => {
    const env = await show([RESTORED], [COPY]);
    await fireEvent.click(within(row(RESTORED.number)).getByRole('button', { name: 'Protokół' }));
    expect(env.bridge.calls.find((c) => c.method === 'report')?.args).toEqual([RESTORED.number]);
  });

  test('a row with a deleted copy says so and still has the report', async () => {
    await show([DELETED], []);
    const r = row(DELETED.number);
    expect(r.textContent).toContain('kopia usunięta 19.10');
    expect(r.textContent).not.toContain('kopia jeszcze');
    expect(within(r).getByRole('button', { name: 'Protokół' })).toBeTruthy();
    expect(within(r).queryByRole('button', { name: /^Więcej działań/ })).toBeNull();  // nie ma czego wyświetlić w menu
  });

  test('with a deleted copy the menu keeps only what still makes sense', async () => {
    await show([{ ...DELETED, counts: { files_whatsapp: 3 } }], []);
    await openMenu(DELETED.number);
    const r = row(DELETED.number);
    expect(within(r).getByRole('menuitemcheckbox', { name: 'Czaty WhatsApp przywrócone' })).toBeTruthy();
    expect(within(r).queryByRole('menuitem', { name: 'Przedłuż' })).toBeNull();
    expect(within(r).queryByRole('menuitem', { name: 'Usuń kopię' })).toBeNull();
  });

  test('rows name phones, never serial numbers; IMEI shows when the row is expanded', async () => {
    await show([RESTORED, READY], [COPY, { ...COPY, id: 'OLD/0', order: READY.number }]);
    expect(row(READY.number).textContent).toContain('Xiaomi Redmi 12');
    expect(row(READY.number).textContent).toContain('nowy telefon');
    expect(document.body.textContent).not.toContain('SERIALOLD1');
    expect(row(RESTORED.number).textContent).not.toContain(OLD_IMEI);
    await fireEvent.click(within(row(RESTORED.number)).getByRole('button', { name: 'Pokaż szczegóły' }));
    expect(row(RESTORED.number).textContent).toContain(`IMEI ${OLD_IMEI}`);
    expect(row(RESTORED.number).textContent).toContain(`IMEI ${NEW_IMEI}`);
    expect(document.body.textContent).not.toContain('SERIALOLD1');
  });

  test('expanding shows category counts, without malicious apps as a category', async () => {
    await show([RESTORED], [COPY]);
    await fireEvent.click(within(row(RESTORED.number)).getByRole('button', { name: 'Pokaż szczegóły' }));
    const items = [...screen.getByTestId('copy-contents').children].map((e) => e.textContent?.trim());
    expect(items).toEqual(['Kontakty 312', 'SMS 1204', 'Zdjęcia 1530', 'Aplikacje 14']);
    await fireEvent.click(within(row(RESTORED.number)).getByRole('button', { name: 'Ukryj szczegóły' }));
    expect(screen.queryByTestId('copy-contents')).toBeNull();
  });

  test('a copy ready offers upload to another connected phone; none connected or the same phone: no button', async () => {
    const copy = { ...COPY, id: 'OLD/0', order: READY.number };
    const env = await show([READY], [copy], { serial: 'NEW9', imei: NEW_IMEI });
    const plan = vi.spyOn(env.ctl, 'planRestore').mockResolvedValue();
    const r = row(READY.number);
    expect(within(r).queryByRole('button', { name: 'Protokół' })).toBeNull();
    expect(r.textContent).toContain('kopia gotowa');
    await fireEvent.click(within(r).getByRole('button', { name: 'Wgraj na podłączony' }));
    expect(plan).toHaveBeenCalledWith('OLD/0');
    env.s.devices = [{ serial: 'OLD9', state: 'device', model: 'M', name: null, imei: '333333333333333' }];
    env.s.serial = 'OLD9';
    await tick();
    expect(within(r).queryByRole('button', { name: 'Wgraj na podłączony' })).toBeNull();
    env.s.devices = [];
    env.s.serial = null;
    await tick();
    expect(within(r).queryByRole('button', { name: 'Wgraj na podłączony' })).toBeNull();
  });

  test('a copy without an order is a row of its own: interrupted, resume when the phone is connected', async () => {
    await show([RESTORED], [COPY, INTERRUPTED]);
    const r = screen.getByRole('article', { name: /motorola Moto G54/ });
    expect(r.textContent).toContain('kopia przerwana — wznów przy podłączeniu');
    expect(r.textContent).toContain('Piotr S.');
    expect(within(r).queryByRole('button', { name: 'Protokół' })).toBeNull();
    expect(within(r).queryByRole('button', { name: 'Wgraj na podłączony' })).toBeNull();
    await fireEvent.click(within(r).getByRole('button', { name: /^Więcej działań/ }));
    expect(within(r).getByRole('menuitem', { name: 'Usuń kopię' })).toBeTruthy();
    expect(screen.getAllByRole('article')).toHaveLength(2);  // kopia ze zleceniem nie jest osobnym wierszem
  });

  test('deleting asks first, then deletes that copy and keeps the row', async () => {
    const env = await show([RESTORED], [COPY]);
    const del = vi.spyOn(env.ctl, 'deleteTransfer').mockResolvedValue();
    await openMenu(RESTORED.number);
    await fireEvent.click(within(row(RESTORED.number)).getByRole('menuitem', { name: 'Usuń kopię' }));
    expect(del).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole('button', { name: 'Usuń' }));
    expect(del).toHaveBeenCalledWith('OLD/1');
  });

  test('WhatsApp: ticking in the menu saves it in the order', async () => {
    const withChats = { ...RESTORED, counts: { ...RESTORED.counts, files_whatsapp: 40 } };
    const env = await show([withChats], [COPY]);
    env.bridge.setOrders([withChats]);
    await openMenu(RESTORED.number);
    const item = within(row(RESTORED.number)).getByRole('menuitemcheckbox', { name: 'Czaty WhatsApp przywrócone' });
    expect(item.getAttribute('aria-checked')).toBe('false');
    await fireEvent.click(item);
    await vi.waitFor(() => expect(env.s.transfer.orders[0].whatsapp_restored).toBe(true));
    expect(env.bridge.calls.find((c) => c.method === 'set_whatsapp_restored')?.args).toEqual([RESTORED.number, true]);
  });

  test('without WhatsApp files the menu has no WhatsApp item', async () => {
    await show([RESTORED], [COPY]);
    await openMenu(RESTORED.number);
    expect(within(row(RESTORED.number)).queryByRole('menuitemcheckbox')).toBeNull();
  });

  test('blocked apps: the menu offers installing them only while the target phone is connected', async () => {
    const blocked = { ...RESTORED, apps_blocked: true };
    const env = await show([blocked], [COPY]);
    expect(row(RESTORED.number).textContent).toContain('aplikacje czekają na odblokowanie instalacji');
    await openMenu(RESTORED.number);
    expect(within(row(RESTORED.number)).queryByRole('menuitem', { name: 'Doinstaluj aplikacje' })).toBeNull();
    env.s.devices = [{ serial: 'NEW9', state: 'device', model: 'M', name: null, imei: NEW_IMEI }];
    await tick();
    await fireEvent.click(within(row(RESTORED.number)).getByRole('menuitem', { name: 'Doinstaluj aplikacje' }));
    await vi.waitFor(() => expect(env.bridge.calls.find((c) => c.method === 'install_remaining_apps')?.args).toEqual([RESTORED.number]));
    expect(env.s.transfer.appsBusy).toBe(RESTORED.number);
  });

  test('a refused reinstall is a short note in the row, not a banner', async () => {
    const blocked = { ...RESTORED, apps_blocked: true };
    const env = await show([blocked], [COPY], { serial: 'NEW9', imei: NEW_IMEI });
    env.bridge.failNext('install_remaining_apps', 'transfer_no_phone', 'NEW9');
    await openMenu(RESTORED.number);
    await fireEvent.click(within(row(RESTORED.number)).getByRole('menuitem', { name: 'Doinstaluj aplikacje' }));
    await vi.waitFor(() => expect(row(RESTORED.number).textContent).toContain('telefon nie jest podłączony'));
    expect(env.s.error).toBeNull();
  });

  test('a note can be added from the menu', async () => {
    const env = await show([RESTORED], [{ ...COPY, note: null }]);
    env.bridge.setCopies([{ ...COPY, note: null }]);
    await openMenu(RESTORED.number);
    await fireEvent.click(within(row(RESTORED.number)).getByRole('menuitem', { name: 'Notatka' }));
    const area = await screen.findByRole('textbox', { name: 'Notatka serwisanta' });
    await fireEvent.input(area, { target: { value: '  Tylko zdjęcia z 2025.  ' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Zapisz' }));
    await vi.waitFor(() => expect(screen.getByTestId('copy-note').textContent).toBe('Tylko zdjęcia z 2025.'));
    expect(env.bridge.calls.filter((c) => c.method === 'set_transfer_note').map((c) => c.args)).toEqual([['OLD/1', 'Tylko zdjęcia z 2025.']]);
  });

  test('the menu closes on Escape and on a click elsewhere', async () => {
    await show([RESTORED], [COPY]);
    await openMenu(RESTORED.number);
    expect(screen.queryByRole('menu')).toBeTruthy();
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    await openMenu(RESTORED.number);
    await fireEvent.click(document.body);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  test('a restored order offers its copy to another connected phone from the menu; the top action stays the report', async () => {
    const env = await show([RESTORED], [COPY], { serial: 'NEW9', imei: '123456789012345' });
    const plan = vi.spyOn(env.ctl, 'planRestore').mockResolvedValue();
    const r = row(RESTORED.number);
    expect(within(r).getByRole('button', { name: 'Protokół' })).toBeTruthy();
    expect(within(r).queryByRole('button', { name: 'Wgraj na podłączony' })).toBeNull();
    await openMenu(RESTORED.number);
    await fireEvent.click(within(r).getByRole('menuitem', { name: 'Wgraj na podłączony' }));
    expect(plan).toHaveBeenCalledWith('OLD/1');
  });

  test('never offered to the source phone itself: by IMEI, and by serial when the IMEI is missing', async () => {
    const env = await show([RESTORED], [COPY], { serial: 'X', imei: OLD_IMEI });
    await openMenu(RESTORED.number);
    expect(within(row(RESTORED.number)).queryByRole('menuitem', { name: 'Wgraj na podłączony' })).toBeNull();
    env.s.devices = [{ serial: 'SERIALOLD1', state: 'device', model: 'M', name: null, imei: null }];
    env.s.serial = 'SERIALOLD1';
    await tick();
    expect(within(row(RESTORED.number)).queryByRole('menuitem', { name: 'Wgraj na podłączony' })).toBeNull();
    // kopia bez zlecenia (źródło bez IMEI) — ta sama zasada
    env.s.transfer.copies = [{ ...COPY, id: 'OLD/8', order: null, status: 'complete' as const }];
    env.s.transfer.orders = [];
    await tick();
    expect(screen.queryByRole('button', { name: 'Wgraj na podłączony' })).toBeNull();
    env.s.devices = [{ serial: 'ELSE', state: 'device', model: 'M', name: null, imei: null }];
    env.s.serial = 'ELSE';
    await tick();
    expect(screen.getByRole('button', { name: 'Wgraj na podłączony' })).toBeTruthy();
  });

  test('the target phone is matched by serial when it has no IMEI (serial is never shown)', async () => {
    await show([{ ...RESTORED, apps_blocked: true, target: { name: 'OPPO A54', imei: null }, target_serial: 'TGT1' }], [COPY],
      { serial: 'TGT1', imei: null });
    await openMenu(RESTORED.number);
    expect(within(row(RESTORED.number)).getByRole('menuitem', { name: 'Doinstaluj aplikacje' })).toBeTruthy();
    expect(document.body.textContent).not.toContain('TGT1');
  });

  test('menu focus: opens on the first item, arrows move, Escape and a choice return to the dots button', async () => {
    await show([RESTORED], [COPY]);
    const dots = within(row(RESTORED.number)).getByRole('button', { name: /^Więcej działań/ });
    await fireEvent.click(dots);
    const items = within(row(RESTORED.number)).getAllByRole('menuitem');
    await vi.waitFor(() => expect(document.activeElement).toBe(items[0]));
    const menu = screen.getByRole('menu');
    await fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(items[1]);
    await fireEvent.keyDown(menu, { key: 'ArrowUp' });
    await fireEvent.keyDown(menu, { key: 'ArrowUp' });
    expect(document.activeElement).toBe(items.at(-1));
    await fireEvent.keyDown(menu, { key: 'Home' });
    expect(document.activeElement).toBe(items[0]);
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(dots);
    await fireEvent.click(dots);
    await fireEvent.click(within(row(RESTORED.number)).getByRole('menuitem', { name: 'Przedłuż' }));
    expect(document.activeElement).toBe(dots);
  });

  describe('automatic reinstall of blocked apps', () => {
    const blocked = { ...RESTORED, apps_blocked: true };
    async function armed(checks: (boolean | null)[]) {
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      const env = await setupCtl('clean');
      env.bridge.setInstallChecks(checks);
      env.s.transfer.orders = [blocked];
      env.s.transfer.copies = [COPY];
      env.s.devices = [{ serial: 'NEW9', state: 'device', model: 'M', name: null, imei: NEW_IMEI }];
      const view = render(TransferOrders, { context: new Map([['ctl', env.ctl]]) });
      await tick();
      const calls = (m: string) => env.bridge.calls.filter((c) => c.method === m);
      return { env, view, calls };
    }
    const step = async () => { await vi.advanceTimersByTimeAsync(RECHECK_MS + 10); };

    test('checks the order silently and installs once when the block is gone', async () => {
      const { env, calls } = await armed([true, false]);
      await step();
      expect(calls('install_check')[0].args).toEqual([RESTORED.number]);
      expect(calls('install_remaining_apps')).toHaveLength(0);  // jeszcze zablokowane
      await step();
      expect(calls('install_remaining_apps')).toHaveLength(1);
      expect(calls('install_remaining_apps')[0].args).toEqual([RESTORED.number]);
      expect(env.s.error).toBeNull();
    });

    test('not repeated while the reading stays unblocked and the job runs', async () => {
      const { env, calls } = await armed([false]);
      await step();
      expect(calls('install_remaining_apps')).toHaveLength(1);
      expect(env.s.job?.kind).toBe('restore_apps');
      await step();
      await step();
      expect(calls('install_remaining_apps')).toHaveLength(1);
    });

    test('an unknown reading does nothing; unmounting stops the checking', async () => {
      const { view, calls } = await armed([null]);
      await step();
      expect(calls('install_check')).toHaveLength(1);
      expect(calls('install_remaining_apps')).toHaveLength(0);
      view.unmount();
      await step();
      await step();
      expect(calls('install_check')).toHaveLength(1);
    });

    test('a deleted copy: no reinstall in the menu and no checking (nothing to install from)', async () => {
      const { env, calls } = await armed([false]);
      env.s.transfer.orders = [{ ...blocked, copy: { id: 'OLD/1', days_left: 0, deleted_at: '2026-10-30T08:00:00' } }];
      env.s.transfer.copies = [];
      await tick();
      await step();
      await step();
      expect(calls('install_check')).toHaveLength(0);
      expect(calls('install_remaining_apps')).toHaveLength(0);
      // jedyną pozycją menu byłoby doinstalowanie: bez kopii menu ⋯ w ogóle nie ma
      expect(within(row(RESTORED.number)).queryByRole('button', { name: /^Więcej działań/ })).toBeNull();
      expect(within(row(RESTORED.number)).queryByRole('menuitem', { name: 'Doinstaluj aplikacje' })).toBeNull();
    });

    test('no checking while the target phone is not connected', async () => {
      const { env, calls } = await armed([false]);
      env.s.devices = [];
      await step();
      expect(calls('install_check')).toHaveLength(0);
    });
  });

  test('failed and expired orders have their own pills', async () => {
    await show([{ ...DELETED, state: 'failed', number: 'ZS/F/1' }, { ...DELETED, state: 'expired', number: 'ZS/E/1', created_at: '2026-10-01T09:00:00' }], []);
    expect(row('ZS/F/1').textContent).toContain('nie wgrano');
    expect(row('ZS/E/1').textContent).toContain('kopia wygasła');
  });

  test('a failed order that restored a part says "przerwane", not "nie wgrano"', async () => {
    await show([{ ...DELETED, state: 'failed', number: 'ZS/P/1', partial: true }], []);
    expect(row('ZS/P/1').textContent).toContain('przerwane');
    expect(row('ZS/P/1').textContent).not.toContain('nie wgrano');
  });
});
