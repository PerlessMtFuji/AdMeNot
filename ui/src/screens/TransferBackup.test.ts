import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test } from 'vitest';
import type { BackupResultView, CopyView } from '../lib/types';
import { setupCtl } from '../test-utils';
import TransferBackup from './TransferBackup.svelte';

const COPY: CopyView = { id: 'S/1', serial: 'R58T00TEST', model: 'SM-A145R', manufacturer: 'samsung', client: 'Anna K.', created: '2026-10-25T14:30:00',
  expires: '2026-11-01T14:30:00', days_left: 7, status: 'complete', bytes: 6715, counts: {} };

function result(over: Partial<BackupResultView> = {}): BackupResultView {
  return { status: 'complete', copy_id: 'S/1', files_done: 5, files_failed: 0, apps_done: 1, apps_failed: 0, bytes: 6715,
    seconds: 3, telephony: { contacts: { status: 'ok', count: 2 }, sms: { status: 'ok', count: 2 }, calls: { status: 'ok', count: 1 } },
    ...over };
}

async function show(phase: 'transfer_backup' | 'transfer_done' = 'transfer_backup') {
  const env = await setupCtl('transfer');
  env.s.phase = phase;
  const view = render(TransferBackup, { context: new Map([['ctl', env.ctl]]) });
  await tick();
  return { ...env, ...view };
}

describe('TransferBackup', () => {
  test('a note can be written while copying, once the bridge announces the copy', async () => {
    const { bridge } = await show();
    expect(screen.queryByRole('button', { name: 'Dodaj notatkę' })).toBeNull();
    bridge.emit('transfer:copy', { copy: { ...COPY, status: 'in_progress', note: 'Z poprzedniej próby' } });
    await tick();
    expect(screen.getByRole('region', { name: 'Notatka serwisanta' })).toBeTruthy();
    expect(screen.getByTestId('copy-note').textContent).toBe('Z poprzedniej próby');
  });

  test('progress shows files, size, stage and the current file', async () => {
    const { bridge } = await show();
    bridge.emit('transfer:progress', { stage: 'files', done_files: 3, total_files: 10, done_bytes: 30, total_bytes: 100,
      current: 'DCIM/Camera/a.jpg', done_apps: 0, total_apps: 0 });
    await tick();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('30');
    expect(screen.getByText(/3 z 10 plików/)).toBeTruthy();
    expect(screen.queryByText(/aplikacji/)).toBeNull();
    expect(screen.getByText('DCIM/Camera/a.jpg')).toBeTruthy();
    expect(screen.getByText(/Pliki/)).toBeTruthy();
  });

  test('with apps selected, all files copied is not the end: apps are counted and the bar is not full', async () => {
    const { bridge } = await show();
    bridge.emit('transfer:progress', { stage: 'apps', done_files: 10, total_files: 10, done_bytes: 100, total_bytes: 100,
      current: 'com.example', done_apps: 4, total_apps: 35 });
    await tick();
    expect(screen.getByText(/10 z 10 plików/)).toBeTruthy();
    expect(screen.getByText(/4 z 35 aplikacji/)).toBeTruthy();
    expect(Number(screen.getByRole('progressbar').getAttribute('aria-valuenow'))).toBeLessThan(100);
  });

  test('transfer:waiting shows the reconnect banner', async () => {
    const { bridge } = await show();
    expect(screen.queryByText(/Telefon odłączony/)).toBeNull();
    bridge.emit('transfer:waiting', {});
    await tick();
    expect(screen.getByText('Telefon odłączony — podłącz ponownie, kopia będzie kontynuowana')).toBeTruthy();
  });

  test('stop asks the bridge to stop', async () => {
    const { ctl, bridge } = await show();
    ctl.setJob('job-2', 'backup');
    await fireEvent.click(screen.getByRole('button', { name: 'Przerwij' }));
    expect(bridge.calls.at(-1)).toEqual({ method: 'stop', args: ['job-2'] });
  });

  test('a complete copy is ready and checked', async () => {
    const { s } = await show('transfer_done');
    s.transfer.result = result();
    s.transfer.copy = COPY;
    await tick();
    expect(screen.getByText('Kopia gotowa i sprawdzona — możesz odłączyć stary telefon')).toBeTruthy();
  });

  test('missing phone data is a warning with the Xiaomi hint, never the green banner', async () => {
    const { s } = await show('transfer_done');
    s.device = { manufacturer: 'Xiaomi' } as never;
    s.transfer.result = result({ telephony: { contacts: { status: 'ok', count: 2 }, sms: { status: 'unavailable', count: 0 },
      mms: { status: 'failed', count: 4, error: 'addresses_missing:3' } } });
    s.transfer.copy = { ...COPY, manufacturer: 'Xiaomi' };
    await tick();
    expect(screen.queryByText('Kopia gotowa i sprawdzona — możesz odłączyć stary telefon')).toBeNull();
    expect(screen.getByText(/Debugowanie USB \(ustawienia zabezpieczeń\)/)).toBeTruthy();
    expect(screen.getByText(/bez adresów: 3/)).toBeTruthy();
  });

  test('unavailable data on another brand: plain notice, no Xiaomi hint', async () => {
    const { s } = await show('transfer_done');
    s.device = { manufacturer: 'samsung', brand: 'samsung' } as never;
    s.transfer.result = result({ telephony: { sms: { status: 'unavailable', count: 0 } } });
    s.transfer.copy = COPY;
    await tick();
    expect(screen.getByText('Telefon nie pozwolił odczytać tych danych.')).toBeTruthy();
    expect(screen.queryByText(/Debugowanie USB/)).toBeNull();
  });

  test('data copied from an export file says so instead of the Xiaomi hint', async () => {
    const { s } = await show('transfer_done');
    s.device = { manufacturer: 'Xiaomi' } as never;
    s.transfer.result = result({ telephony: { contacts: { status: 'ok', count: 3, error: null, source: 'export' },
      sms: { status: 'failed', count: 0, error: 'export_changed', source: 'export' } } });
    s.transfer.copy = COPY;
    await tick();
    expect(screen.getByText('3 · z pliku eksportu')).toBeTruthy();
    expect(screen.getByText(/plik eksportu zmienił się od skanu/)).toBeTruthy();
    expect(screen.queryByText(/Debugowanie USB/)).toBeNull();
  });

  test('a stopped copy says so and can be resumed later', async () => {
    const { s } = await show('transfer_done');
    s.transfer.result = result({ status: 'stopped' });
    s.transfer.copy = { ...COPY, status: 'in_progress' };
    await tick();
    expect(screen.queryByText('Kopia gotowa i sprawdzona — możesz odłączyć stary telefon')).toBeNull();
    expect(screen.getByText('Kopia przerwana')).toBeTruthy();
  });

  test('files the scan could not read turn a complete copy into a warning', async () => {
    const { s } = await show('transfer_done');
    s.transfer.result = result();
    s.transfer.copy = { ...COPY, counts: { files: 5, unreadable: 1 } };
    await tick();
    expect(screen.queryByText('Kopia gotowa i sprawdzona — możesz odłączyć stary telefon')).toBeNull();
    expect(screen.getByText('Kopia gotowa, ale nie wszystko udało się skopiować')).toBeTruthy();
    expect(screen.getByText('1 pliku lub folderu nie dało się odczytać — nie trafi do kopii')).toBeTruthy();
  });

  test('the Xiaomi hint does not send the technician to copy everything again', async () => {
    const { s } = await show('transfer_done');
    s.device = { manufacturer: 'Xiaomi' } as never;
    s.transfer.result = result({ telephony: { sms: { status: 'unavailable', count: 0 } } });
    s.transfer.copy = COPY;
    await tick();
    expect(screen.getByText(/zaznacz tylko brakujące dane/)).toBeTruthy();
  });

  test('progress after reconnecting hides the disconnected banner', async () => {
    const { bridge } = await show();
    bridge.emit('transfer:waiting', {});
    await tick();
    bridge.emit('transfer:progress', { stage: 'telephony', done_files: 0, total_files: 0, done_bytes: 0, total_bytes: 0, current: '' });
    await tick();
    expect(screen.queryByText(/Telefon odłączony/)).toBeNull();
  });
});

