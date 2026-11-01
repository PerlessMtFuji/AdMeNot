import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test } from 'vitest';
import type { RestoreResultView, TelKindResultView, TelResultView } from '../lib/types';
import { setupCtl } from '../test-utils';
import TransferRestore from './TransferRestore.svelte';

function result(over: Partial<RestoreResultView> = {}): RestoreResultView {
  return { status: 'complete', target_serial: 'R58W20NEW01', files_done: 5, files_exists: 2, files_renamed: 1, files_denied: 0,
    files_failed: 0, files_unselected: 0, apk_skipped: 1, apk_suspicious_skipped: 1, bytes: 6704, seconds: 3, hashed: false,
    media_scan: 'done', files_missing: 0, ...over };
}

const kind = (over: Partial<TelKindResultView> = {}): TelKindResultView => ({ written: 2, existed: 1, skipped_synced: 0,
  skipped_messenger: 0, failed: 0, manual: 0, path: 'app_process', visible_warning: false, ...over });
const CLEAN = { role_ok: true, appop_ok: true, companion_removed: true, helper_removed: true, ok: true };
function tel(over: Partial<TelResultView> = {}): TelResultView {
  return { kinds: { contacts: kind(), sms: kind({ path: 'companion' }) }, safety: {}, manual: [], cleanup: CLEAN,
    synced_accounts: [], seconds: 1, stopped: false, status: 'complete', ...over };
}

async function show(phase: 'transfer_restore' | 'transfer_restored' = 'transfer_restore', r?: RestoreResultView) {
  const env = await setupCtl('transfer_restore');
  env.s.phase = phase;
  env.s.serial = 'R58W20NEW01';
  if (r) env.s.transfer.restore.result = r;
  env.s.transfer.restore.choice = { ...env.s.transfer.restore.choice, groups: ['photos'] };
  const view = render(TransferRestore, { context: new Map([['ctl', env.ctl]]) });
  await tick();
  return { ...env, ...view };
}

describe('TransferRestore', () => {
  test('stages follow the chosen data; telephony progress shows its own count', async () => {
    const { s, bridge } = await show();
    s.transfer.restore.choice = { groups: ['photos'], apks_on: [], verify_hash: false, tel: ['contacts', 'sms', 'calls'] };
    bridge.emit('transfer:tel_progress', { kind: 'sms', done: 40, total: 200, path: 'companion' });
    await tick();
    const stages = screen.getByRole('list', { name: 'Etapy wgrywania' });
    expect([...stages.querySelectorAll('li')].map((li) => [li.textContent?.trim(), li.dataset.state])).toEqual([
      ['Pliki', 'done'], ['Kontakty', 'done'], ['Wiadomości', 'current'], ['Połączenia', 'todo']]);
    expect(screen.getByText('40 z 200')).toBeTruthy();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('20');
  });

  test('asking for the SMS role: a warning with "Skip" that calls the bridge', async () => {
    const { bridge } = await show();
    bridge.emit('transfer:tap', { request: 'sms_role_grant', package: 'com.google.android.apps.messaging' });
    await tick();
    expect(screen.getByText('Na telefonie: potwierdź AdMeNot jako aplikację SMS na czas wgrywania')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Pomiń (zostawię plik do importu)' }));
    expect(bridge.calls.at(-1)).toEqual({ method: 'skip_tap', args: [] });
  });

  test('giving the SMS role back: a red banner with the previous app and no "Skip"', async () => {
    const { bridge } = await show();
    bridge.emit('transfer:tap', { request: 'sms_role_restore', package: 'com.google.android.apps.messaging' });
    await tick();
    expect(screen.getByText('Na telefonie: wybierz Wiadomości Google jako domyślną aplikację SMS')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Pomiń/ })).toBeNull();
    bridge.emit('transfer:tap', { request: 'sms_role_restore', package: 'org.example.sms' });
    await tick();
    expect(screen.getByText('Na telefonie: wybierz org.example.sms jako domyślną aplikację SMS')).toBeTruthy();
    bridge.emit('transfer:tap', { request: 'sms_role_restore', package: null });
    await tick();
    expect(screen.getByText('Na telefonie: wybierz poprzednią aplikację SMS jako domyślną aplikację SMS')).toBeTruthy();
  });

  test('result: a table per category and the SMS Backup & Restore step with the file name', async () => {
    const { s } = await show('transfer_restored', result());
    s.transfer.restore.telResult = tel({ kinds: { contacts: kind(), sms: kind({ written: 0, manual: 300, path: 'file' }) },
      manual: [{ kind: 'sms', name: 'admenot-sms-20260926-143100.xml' }], status: 'incomplete' });
    await tick();
    expect(screen.getByText('Kontakty i wiadomości wgrane, ale nie wszystko się udało')).toBeTruthy();
    const table = screen.getByRole('table');
    expect([...table.querySelectorAll('th')].map((th) => th.textContent?.trim())).toEqual(
      ['Kategoria', 'Wgrano', 'Już były', 'Pominięte', 'Błędy', 'Do importu', 'Sposób']);
    expect(table.textContent).toMatch(/plik do importu/);
    const smsCells = [...screen.getByText('SMS', { selector: 'td' }).closest('tr')!.querySelectorAll('td')]
      .map((td) => td.textContent?.trim());
    expect(smsCells.slice(0, 6)).toEqual(['SMS', '0', '1', '0', '0', '300']);  // rekordy z pliku do importu widać w wierszu
    expect(screen.getByText('Do zrobienia na telefonie')).toBeTruthy();
    expect(screen.getByText(/zainstaluj SMS Backup & Restore, Przywróć, wybierz plik admenot-sms-20260926-143100\.xml z Pobranych/))
      .toBeTruthy();
    expect(screen.getByText('Pliki wgrane')).toBeTruthy();  // wynik plików zostaje
  });

  test('result: contacts left to import and messages to check in the Messages app', async () => {
    const { s } = await show('transfer_restored', result());
    s.transfer.restore.telResult = tel({ kinds: { contacts: kind({ manual: 2, path: 'file' }), sms: kind({ visible_warning: true }) },
      manual: [{ kind: 'contacts', name: 'admenot-kontakty.vcf' }] });
    await tick();
    expect(screen.getByText(/otwórz Kontakty → Importuj, wybierz plik admenot-kontakty/)).toBeTruthy();
    expect(screen.getByText(/sprawdź w aplikacji Wiadomości/)).toBeTruthy();
  });

  test('everything uploaded: a green telephony banner', async () => {
    const { s } = await show('transfer_restored', result());
    s.transfer.restore.telResult = tel();
    await tick();
    expect(screen.getByText('Kontakty i wiadomości wgrane')).toBeTruthy();
  });

  test('the phone was not cleaned up: a red banner with the manual steps', async () => {
    const { s } = await show('transfer_restored', result());
    s.transfer.restore.telResult = tel({ cleanup: { ...CLEAN, role_ok: false, ok: false }, status: 'incomplete' });
    await tick();
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toMatch(/Telefon nie wrócił do swoich ustawień/);
    expect(alert.textContent).toMatch(/odinstaluj AdMeNot Helper/);
  });

  test('a telephony error: a visible error banner next to the files result', async () => {
    const { s } = await show('transfer_restored', result());
    s.transfer.restore.telError = 'disconnected';
    await tick();
    expect(screen.getByRole('alert').textContent).toMatch(/Nie udało się wgrać kontaktów i wiadomości/);
    expect(screen.getByText('Pliki wgrane')).toBeTruthy();
  });

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
