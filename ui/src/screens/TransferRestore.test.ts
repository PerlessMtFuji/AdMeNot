import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test } from 'vitest';
import type { RestoreResultView } from '../lib/types';
import { setupCtl } from '../test-utils';
import TransferRestore from './TransferRestore.svelte';

function result(over: Partial<RestoreResultView> = {}): RestoreResultView {
  return { status: 'complete', target_serial: 'R58W20NEW01', files_done: 5, files_exists: 2, files_renamed: 1, files_denied: 0,
    files_failed: 0, files_unselected: 0, apk_skipped: 1, apk_suspicious_skipped: 1, bytes: 6704, seconds: 3, hashed: false,
    media_scan: 'done', files_missing: 0, ...over };
}

async function show(phase: 'transfer_restore' | 'transfer_restored' = 'transfer_restore', r?: RestoreResultView) {
  const env = await setupCtl('transfer_restore');
  env.s.phase = phase;
  env.s.serial = 'R58W20NEW01';
  if (r) env.s.transfer.restore.result = r;
  const view = render(TransferRestore, { context: new Map([['ctl', env.ctl]]) });
  await tick();
  return { ...env, ...view };
}

describe('TransferRestore', () => {
  test('progress shows files, size and the current file; a disconnect shows the banner', async () => {
    const { bridge } = await show();
    bridge.emit('transfer:restore_progress', { stage: 'files', done_files: 3, total_files: 10, done_bytes: 30, total_bytes: 100,
      current: '/sdcard/DCIM/Camera/a.jpg' });
    await tick();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('30');
    expect(screen.getByText(/3 z 10 plików/)).toBeTruthy();
    expect(screen.getByText('/sdcard/DCIM/Camera/a.jpg')).toBeTruthy();
    bridge.emit('transfer:waiting', {});
    await tick();
    expect(screen.getByText('Telefon odłączony — podłącz ponownie, wgrywanie będzie kontynuowane')).toBeTruthy();
  });

  test('stop asks the bridge to stop the upload', async () => {
    const { ctl, bridge } = await show();
    ctl.setJob('job-4', 'restore');
    await fireEvent.click(screen.getByRole('button', { name: 'Przerwij' }));
    expect(bridge.calls.at(-1)).toEqual({ method: 'stop', args: ['job-4'] });
  });

  test('everything uploaded: green banner, files saved beside and skipped harmful APK counted', async () => {
    await show('transfer_restored', result());
    expect(screen.getByText('Pliki wgrane')).toBeTruthy();
    expect(screen.getByText(/zapisano obok jako „\(z kopii\)”: 1/)).toBeTruthy();
    expect(screen.getByText('pominięto 1 plik oceniony jako szkodliwy')).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/usunięto/i);
    expect(screen.queryByText(/Uruchom ponownie telefon/)).toBeNull();
  });

  test('files refused by Android: yellow banner with the number, never the green one', async () => {
    await show('transfer_restored', result({ files_denied: 3, files_failed: 2 }));
    expect(screen.queryByText('Pliki wgrane')).toBeNull();
    expect(screen.getByText('Pliki wgrane, ale nie wszystko się udało')).toBeTruthy();
    expect(screen.getByText(/Android nie pozwolił zapisać: 3/)).toBeTruthy();
    expect(screen.getByText(/nie udało się wgrać: 2/)).toBeTruthy();
  });

  test('Android below 10: still green, plus a separate restart banner', async () => {
    await show('transfer_restored', result({ media_scan: 'restart' }));
    expect(screen.getByText('Pliki wgrane')).toBeTruthy();
    expect(screen.getByText('Uruchom ponownie telefon, żeby galeria zobaczyła pliki')).toBeTruthy();
    expect(screen.queryByText(/nie wszystko się udało/)).toBeNull();
  });

  test('a failed gallery scan gets its own text, not the generic failure', async () => {
    await show('transfer_restored', result({ media_scan: 'failed' }));
    expect(screen.getByText('Pliki wgrane, ale galeria może ich nie widzieć do restartu telefonu')).toBeTruthy();
    expect(screen.queryByText(/nie wszystko się udało/)).toBeNull();
    expect(screen.queryByText('Pliki wgrane')).toBeNull();
  });

  test('a stopped upload says so and does not ask for a restart', async () => {
    await show('transfer_restored', result({ status: 'stopped', media_scan: 'skipped' }));
    expect(screen.getByText('Wgrywanie przerwane')).toBeTruthy();
    expect(screen.queryByText(/Uruchom ponownie telefon/)).toBeNull();
  });
});
