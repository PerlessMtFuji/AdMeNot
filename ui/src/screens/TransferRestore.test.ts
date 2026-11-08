import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { RECHECK_MS } from '../lib/recheck';
import type { AppsResultView, RestoreResultView, TelKindResultView, TelResultView, WhatsappView } from '../lib/types';
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
    s.transfer.restore.choice = { groups: ['photos'], apks_on: [], verify_hash: false, tel: ['contacts', 'sms', 'calls'], apps: [] };
    bridge.emit('transfer:tel_progress', { kind: 'sms', done: 40, total: 200, path: 'companion' });
    await tick();
    const stages = screen.getByRole('list', { name: 'Etapy wgrywania' });
    expect([...stages.querySelectorAll('li')].map((li) => [li.textContent?.trim(), li.dataset.state])).toEqual([
      ['Pliki', 'done'], ['Kontakty', 'done'], ['Wiadomości', 'current'], ['Połączenia', 'todo']]);
    expect(screen.getByText('40 z 200')).toBeTruthy();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('20');
  });

  test('safety backup of the new phone gets its own stage label and no counter', async () => {
    const { s, bridge } = await show();
    s.transfer.restore.choice = { groups: ['photos'], apks_on: [], verify_hash: false, tel: ['contacts', 'sms'], apps: [] };
    bridge.emit('transfer:tel_progress', { kind: 'safety', done: 0, total: 0, path: 'none' });
    await tick();
    expect(screen.getByText('Etap: Kopia bezpieczeństwa nowego telefonu')).toBeTruthy();
    expect(screen.queryByText(/0 z 0/)).toBeNull();
    // osobny bieżący etap (nie „Kontakty”) i pasek bez procentów zamiast 0 % przez minuty eksportu
    const stages = screen.getByRole('list', { name: 'Etapy wgrywania' });
    expect([...stages.querySelectorAll('li')].map((li) => [li.textContent?.trim(), li.dataset.state])).toEqual([
      ['Pliki', 'done'], ['Kopia bezpieczeństwa nowego telefonu', 'current'], ['Kontakty', 'todo'], ['Wiadomości', 'todo']]);
    const bar = screen.getByRole('progressbar');
    expect(bar.getAttribute('aria-valuenow')).toBeNull();
    expect(bar.hasAttribute('data-indeterminate')).toBe(true);
    bridge.emit('transfer:tel_progress', { kind: 'contacts', done: 1, total: 4, path: 'app_process' });
    await tick();
    expect([...stages.querySelectorAll('li')].map((li) => [li.textContent?.trim(), li.dataset.state])).toEqual([
      ['Pliki', 'done'], ['Kontakty', 'current'], ['Wiadomości', 'todo']]);
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('25');
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

  test('apps stage: its own stage, a counter, the consent hint and the current app', async () => {
    const { s, bridge } = await show();
    s.transfer.restore.choice = { groups: ['photos'], apks_on: [], verify_hash: false, tel: ['contacts'], apps: ['com.a', 'com.b'] };
    bridge.emit('transfer:tel_progress', { kind: 'contacts', done: 4, total: 4, path: 'app_process' });
    await tick();
    expect(screen.queryByText('Jeśli telefon pyta o zgodę — potwierdź')).toBeNull();
    bridge.emit('transfer:apps_progress', { stage: 'apps', done: 3, total: 12, current: 'Pilot TV' });
    await tick();
    const stages = screen.getByRole('list', { name: 'Etapy wgrywania' });
    expect([...stages.querySelectorAll('li')].map((li) => [li.textContent?.trim(), li.dataset.state])).toEqual([
      ['Pliki', 'done'], ['Kontakty', 'done'], ['Aplikacje', 'current']]);
    expect(screen.getByText('Etap: Aplikacje')).toBeTruthy();
    expect(screen.getByText('3 z 12')).toBeTruthy();
    expect(screen.getByText('Pilot TV')).toBeTruthy();
    expect(screen.getByText('Jeśli telefon pyta o zgodę — potwierdź')).toBeTruthy();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('25');
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
});

// --- Wynik: „Dane przeniesione” ------------------------------------------------------------------------------------

const ORDER = 'ZS/2026/0926/01';
const rowOf = (name: string): HTMLElement => {
  const label = screen.getByText(name, { selector: 'span.font-bold' });
  let el: HTMLElement | null = label;
  while (el && !(el.parentElement?.classList.contains('divide-y'))) el = el.parentElement;
  return el!;
};

function appsView(over: Partial<AppsResultView> = {}): AppsResultView {
  return { selected: 3, installed: 2, exists: 1, skipped: {}, failed: {}, codes: {}, blocked: false, stopped: false,
    rows: [{ package: 'com.a', label: 'Alfa', status: 'installed', reason: null },
      { package: 'com.b', label: 'Beta', status: 'installed', reason: null },
      { package: 'com.c', label: 'Gamma', status: 'exists', reason: null }], play_installer: true, ...over };
}

const BLOCKED = appsView({ selected: 3, installed: 0, exists: 1, skipped: { user_restricted: 2 }, blocked: true,
  rows: [{ package: 'com.a', label: 'Alfa', status: 'skipped', reason: 'user_restricted' },
    { package: 'com.b', label: 'Beta', status: 'skipped', reason: 'user_restricted' },
    { package: 'com.c', label: 'Gamma', status: 'exists', reason: null }] });

async function finished(r: RestoreResultView, extra: {
  tel?: TelResultView | null; telError?: string | null; apps?: AppsResultView | null; appsError?: string | null;
  order?: string | null; whatsapp?: WhatsappView | null; groups?: string[]; connected?: boolean } = {}) {
  const env = await show('transfer_restored', r);
  const restore = env.s.transfer.restore;
  restore.choice = { ...restore.choice, groups: extra.groups ?? ['photos'], tel: extra.tel ? ['contacts', 'sms'] : [] };
  Object.assign(restore, { telResult: extra.tel ?? null, telError: extra.telError ?? null, appsResult: extra.apps ?? null,
    appsError: extra.appsError ?? null, order: extra.order === undefined ? ORDER : extra.order, whatsapp: extra.whatsapp ?? null });
  const phone = { serial: 'R58W20NEW01', state: 'device', model: 'SM_A145R' };
  env.bridge.emit('devices', { devices: extra.connected === false ? [] : [phone], error: null });
  await tick();
  return env;
}

describe('TransferRestore result', () => {
  test('everything fine: one green result, one card with a row per category, no table', async () => {
    await finished(result({ files_renamed: 0, apk_skipped: 0, apk_suspicious_skipped: 0, files_exists: 0 }), { tel: tel(), apps: appsView() });
    expect(screen.getByRole('heading', { level: 1, name: 'Dane przeniesione' })).toBeTruthy();
    expect(screen.getByText('Wszystko wgrane')).toBeTruthy();
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByText('Już były')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(rowOf('Kontakty').textContent).toMatch(/✓ 3/);  // 2 wgrane + 1 już był
    expect(rowOf('SMS i MMS').textContent).toMatch(/✓ 3/);
    expect(rowOf('Pliki').textContent).toMatch(/✓ 5/);
    expect(rowOf('Aplikacje').textContent).toMatch(/✓ 3/);
    // żadnych starych banerów wyniku
    expect(screen.queryByText('Pliki wgrane')).toBeNull();
    expect(screen.queryByText('Kontakty i wiadomości wgrane')).toBeNull();
  });

  test('call history left to import: a yellow pill, the instruction visible at once, other folds collapsed', async () => {
    await finished(result(), {
      tel: tel({ kinds: { contacts: kind(), sms: kind({ path: 'companion' }), calls: kind({ written: 0, existed: 0, manual: 980, path: 'file' }) },
        manual: [{ kind: 'calls', name: 'admenot-polaczenia-20261025.xml' }], status: 'incomplete' }),
      apps: appsView() });
    const calls = rowOf('Historia połączeń');
    expect(calls.textContent).toMatch(/do importu/);
    expect(calls.textContent).toMatch(/980/);
    expect(calls.textContent).toMatch(/przygotowałem plik do importu/);
    expect(screen.getByText(/Na telefonie:/)).toBeTruthy();
    expect(screen.getByText(/zainstaluj SMS Backup & Restore, Przywróć, wybierz plik admenot-polaczenia-20261025\.xml z Pobranych/)).toBeTruthy();
    expect(screen.getByText('Prawie wszystko gotowe')).toBeTruthy();
    expect(screen.getByText(/Do zaimportowania na telefonie: historia połączeń/)).toBeTruthy();
    for (const b of screen.getAllByRole('button', { name: /(Szczegóły|Lista|Pokaż)/ })) expect(b.getAttribute('aria-expanded')).toBe('false');
  });

  test('contacts to import get their own instruction; messages ask to be checked in the Messages app', async () => {
    await finished(result(), {
      tel: tel({ kinds: { contacts: kind({ manual: 2, path: 'file' }), sms: kind({ visible_warning: true }) },
        manual: [{ kind: 'contacts', name: 'admenot-kontakty.vcf' }] }) });
    expect(screen.getByText(/otwórz Kontakty → Importuj, wybierz plik admenot-kontakty/)).toBeTruthy();
    expect(rowOf('SMS i MMS').textContent).toMatch(/sprawdź w aplikacji Wiadomości/);
  });

  test('a category with failures shows the yellow "x z y"', async () => {
    await finished(result(), { tel: tel({ kinds: { contacts: kind({ written: 8, existed: 0, failed: 2 }), sms: kind() } }) });
    expect(rowOf('Kontakty').textContent).toMatch(/8 z 10/);
    expect(rowOf('Kontakty').textContent).toMatch(/nie udało się wgrać: 2/);
  });

  test('file details sit under "Szczegóły" and are collapsed by default', async () => {
    await finished(result(), { tel: null });
    expect(screen.queryByText(/zapisano obok jako „\(z kopii\)”: 1/)).toBeNull();
    const toggle = screen.getByRole('button', { name: 'Pliki: Szczegóły ▾' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    await fireEvent.click(toggle);
    expect(screen.getByText(/zapisano obok jako „\(z kopii\)”: 1/)).toBeTruthy();
    expect(screen.getByText('pominięto 1 plik oceniony jako szkodliwy')).toBeTruthy();
    expect(screen.getByText('sprawdzono rozmiar')).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/usunięto/i);
  });

  test('files refused by Android: a yellow result with the count, never the green one', async () => {
    await finished(result({ files_denied: 3, files_failed: 2 }), { tel: null });
    expect(screen.queryByText('Wszystko wgrane')).toBeNull();
    expect(screen.getByText('Prawie wszystko gotowe')).toBeTruthy();
    expect(screen.getByText(/5 plików nie zostało wgranych/)).toBeTruthy();
    expect(rowOf('Pliki').textContent).toMatch(/7 z 12/);
    await fireEvent.click(screen.getByRole('button', { name: 'Pliki: Szczegóły ▾' }));
    expect(screen.getByText(/Android nie pozwolił zapisać: 3/)).toBeTruthy();
    expect(screen.getByText(/nie udało się wgrać: 2/)).toBeTruthy();
  });

  test('Android below 10: the restart request sits in the Files row and turns the result yellow, in the panel too', async () => {
    await finished(result({ media_scan: 'restart' }), { tel: null });
    expect(screen.queryByText('Wszystko wgrane')).toBeNull();
    expect(screen.getByText('Prawie wszystko gotowe')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toMatch(/Uruchom ponownie telefon, żeby galeria zobaczyła pliki/);
    expect(rowOf('Pliki').textContent).toMatch(/uruchom ponownie telefon, żeby galeria zobaczyła pliki/);
    const panel = screen.getByRole('complementary', { name: 'Przedmiot zlecenia' });
    expect(within(panel).getByRole('list', { name: 'Etapy wgrywania' }).textContent).toMatch(/restart galerii/);
  });

  test('never green when something needs attention: Messages check, incomplete status, failed safety backup', async () => {
    await finished(result({ status: 'incomplete' }), { tel: tel({ kinds: { contacts: kind(), sms: kind({ visible_warning: true }) },
      safety: { contacts: true, sms: false } }) });
    expect(screen.queryByText('Wszystko wgrane')).toBeNull();
    const hero = screen.getByRole('status').textContent ?? '';
    expect(hero).toMatch(/nie wszystkie pliki zostały wgrane/i);
    expect(hero).toMatch(/sprawdź w aplikacji Wiadomości/);
    expect(hero).toMatch(/kopia bezpieczeństwa nowego telefonu się nie udała/);
    const panel = screen.getByRole('complementary', { name: 'Przedmiot zlecenia' });
    const text = within(panel).getByRole('list', { name: 'Etapy wgrywania' }).textContent ?? '';
    expect(text).toMatch(/Kopia bezpieczeństwa nowego telefonu — nieudana/);
    expect(text).toMatch(/Wiadomości — sprawdź w Wiadomościach/);
  });

  test('a failed gallery scan is a yellow remark, not the generic failure', async () => {
    await finished(result({ media_scan: 'failed' }), { tel: null });
    expect(screen.getByText('Prawie wszystko gotowe')).toBeTruthy();
    expect(screen.getAllByText(/galeria może nie widzieć plików do restartu telefonu/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/5 plików nie zostało/)).toBeNull();
  });

  test('a stopped upload says so and does not ask for a restart', async () => {
    await finished(result({ status: 'stopped', media_scan: 'skipped' }), { tel: null });
    expect(screen.getByText('Wgrywanie przerwane')).toBeTruthy();
    expect(screen.queryByText(/uruchom ponownie telefon/i)).toBeNull();
  });

  test('the phone was not cleaned up: one red result with the manual steps', async () => {
    await finished(result(), { tel: tel({ cleanup: { ...CLEAN, role_ok: false, ok: false }, status: 'incomplete' }) });
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toMatch(/Telefon nie wrócił do swoich ustawień/);
    expect(alert.textContent).toMatch(/odinstaluj AdMeNot Helper/);
    expect(screen.getAllByRole('alert')).toHaveLength(1);
  });

  test('a telephony error is a red line in its row, not a banner', async () => {
    await finished(result(), { telError: 'disconnected' });
    expect(screen.queryByRole('alert')).toBeNull();
    const r = rowOf('Kontakty i wiadomości');
    expect(r.textContent).toMatch(/nie wgrano/);
    expect(r.querySelector('.text-bad')).toBeTruthy();
    expect(screen.getByText(/Nie udało się wgrać kontaktów i wiadomości|nie udało się wgrać kontaktów i wiadomości/)).toBeTruthy();
    expect(rowOf('Pliki').textContent).toMatch(/✓ 7/);  // 5 wgranych + 2 już na telefonie
  });

  test('apps: failures with reasons in the line, the whole list under "Lista"', async () => {
    const apps = appsView({ selected: 4, installed: 1, exists: 1, failed: { failed: 1 }, skipped: { no_abi: 1 },
      rows: [{ package: 'com.a', label: 'Alfa', status: 'installed', reason: null },
        { package: 'com.c', label: 'Gamma', status: 'exists', reason: null },
        { package: 'com.t', label: 'Pilot TV', status: 'failed', reason: 'failed' },
        { package: 'com.k', label: 'Kalkulator Pro', status: 'skipped', reason: 'no_abi' }] });
    await finished(result(), { apps });
    const r = rowOf('Aplikacje');
    expect(r.textContent).toMatch(/2 z 4/);
    expect(r.textContent).toMatch(/Pilot TV — telefon odrzucił instalację/);
    expect(r.textContent).toMatch(/Kalkulator Pro — brak wersji dla tego procesora/);
    expect(screen.getByText(/2 aplikacje się nie zainstalowały/i)).toBeTruthy();
    expect(screen.queryByText('Alfa')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Aplikacje: Lista ▾' }));
    expect(screen.getByText('Alfa')).toBeTruthy();
    expect(screen.getByText('Gamma')).toBeTruthy();
  });

  test('an apps error is a red line in the Apps row', async () => {
    await finished(result(), { appsError: 'disconnected' });
    expect(screen.queryByRole('alert')).toBeNull();
    const r = rowOf('Aplikacje');
    expect(r.textContent).toMatch(/nie wgrano/);
    expect(r.querySelector('.text-bad')).toBeTruthy();
  });

  test('right panel: stages with ticks and exclamation marks, the phone, the order and the customer', async () => {
    const env = await finished(result(), {
      tel: tel({ kinds: { contacts: kind(), sms: kind(), calls: kind({ written: 0, existed: 0, manual: 9, path: 'file' }) },
        manual: [{ kind: 'calls', name: 'x.xml' }], safety: { contacts: true, sms: true, calls: true } }),
      apps: appsView({ selected: 4, installed: 1, exists: 1, failed: { failed: 2 },
        rows: [{ package: 'a', label: 'A', status: 'failed', reason: 'failed' }, { package: 'b', label: 'B', status: 'failed', reason: 'failed' },
          { package: 'c', label: 'C', status: 'installed', reason: null }, { package: 'd', label: 'D', status: 'exists', reason: null }] }) });
    env.s.client = 'Anna K.';
    await tick();
    const panel = screen.getByRole('complementary', { name: 'Przedmiot zlecenia' });
    expect(panel.textContent).toMatch(/ZS\/2026\/0926\/01 · Anna K\./);
    const stages = within(panel).getByRole('list', { name: 'Etapy wgrywania' });
    expect([...stages.querySelectorAll('li')].map((li) => [li.dataset.state, li.textContent?.replace(/\s+/g, ' ').trim()])).toEqual([
      ['ok', 'gotowe Pliki'], ['ok', 'gotowe Kopia bezpieczeństwa nowego telefonu'], ['ok', 'gotowe Kontakty'], ['ok', 'gotowe Wiadomości'],
      ['warn', 'wymaga uwagi Połączenia — plik do importu'], ['warn', 'wymaga uwagi Aplikacje — nieudane: 2']]);
  });

  test('the main button is the protocol and calls report(order); the second one finishes without it', async () => {
    const { bridge, s } = await finished(result(), { tel: null });
    await fireEvent.click(screen.getByRole('button', { name: /^Protokół/ }));
    await vi.waitFor(() => expect(bridge.calls.find((c) => c.method === 'report')?.args).toEqual([ORDER]));
    // po protokole drugi przycisk to zwykłe „Zakończ”
    await vi.waitFor(() => expect(screen.queryByRole('button', { name: 'Zakończ bez protokołu' })).toBeNull());
    await fireEvent.click(screen.getByRole('button', { name: 'Zakończ' }));
    expect(s.phase).toBe('connect');
  });

  test('without the protocol the second button reads "Zakończ bez protokołu" and leaves', async () => {
    const { s, bridge } = await finished(result(), { tel: null });
    await fireEvent.click(screen.getByRole('button', { name: 'Zakończ bez protokołu' }));
    expect(s.phase).toBe('connect');
    expect(bridge.calls.some((c) => c.method === 'report')).toBe(false);
  });

  test('no order: no protocol button, a plain "Zakończ"', async () => {
    await finished(result(), { tel: null, order: null });
    expect(screen.queryByRole('button', { name: /Protokół/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Zakończ bez protokołu' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Zakończ' })).toBeTruthy();
  });

  describe('WhatsApp box', () => {
    test('none without the files', async () => {
      await finished(result(), { tel: null, whatsapp: null });
      expect(screen.queryByRole('checkbox', { name: /Czaty przywrócone/ })).toBeNull();
    });

    test('installed: open WhatsApp; ticking calls set_whatsapp_restored(order, true) and unticking sends false', async () => {
      const { bridge } = await finished(result(), { tel: null, whatsapp: { files: true, app: 'installed' } });
      expect(screen.getByText('opcjonalnie, z klientem')).toBeTruthy();
      expect(screen.getByText(/Otwórz WhatsApp, zaloguj numerem klienta i wybierz „Przywróć”/)).toBeTruthy();
      const box = screen.getByRole('checkbox', { name: 'Czaty przywrócone — wpisz to do protokołu' }) as HTMLInputElement;
      await fireEvent.click(box);
      await vi.waitFor(() => expect(bridge.calls.find((c) => c.method === 'set_whatsapp_restored')?.args).toEqual([ORDER, true]));
      await vi.waitFor(() => expect(box.checked).toBe(true));
      await fireEvent.click(box);
      await vi.waitFor(() => expect(bridge.calls.filter((c) => c.method === 'set_whatsapp_restored').at(-1)?.args).toEqual([ORDER, false]));
    });

    test('missing: install it from Google Play; pre-installed: the re-install note', async () => {
      const first = await finished(result(), { tel: null, whatsapp: { files: true, app: 'missing' } });
      expect(screen.getByText(/Zainstaluj WhatsApp ze Sklepu Play/)).toBeTruthy();
      first.s.transfer.restore.whatsapp = { files: true, app: 'pre_installed' };
      await tick();
      expect(screen.getByText(/Otwórz WhatsApp/)).toBeTruthy();
      expect(screen.getByText(/WhatsApp był już na telefonie — jeśli był uruchomiony, przywrócenie może wymagać jego ponownej instalacji/)).toBeTruthy();
    });

    test('without an order the box has no checkbox (nothing to save to)', async () => {
      await finished(result(), { tel: null, order: null, whatsapp: { files: true, app: 'installed' } });
      expect(screen.queryByRole('checkbox')).toBeNull();
    });
  });

  describe('Xiaomi block after the upload', () => {
    const calls = (b: { calls: { method: string }[] }, m: string) => b.calls.filter((c) => c.method === m).length;

    afterEach(() => vi.useRealTimers());

    test('the Apps row keeps the label and opens the instruction only on click', async () => {
      await finished(result(), { apps: BLOCKED });
      const label = screen.getByRole('button', { name: /Xiaomi blokuje instalację · jak włączyć\?/ });
      expect(label.getAttribute('aria-expanded')).toBe('false');
      expect(screen.queryByText(/Instaluj przez USB/)).toBeNull();
      await fireEvent.click(label);
      expect(screen.getByText(/Instaluj przez USB/)).toBeTruthy();
      expect(screen.getByText(/doinstaluję pominięte aplikacje/)).toBeTruthy();
      expect(rowOf('Aplikacje').textContent).toMatch(/1 z 3/);
    });

    test('still blocked: install_check keeps asking, nothing is installed', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge } = await finished(result(), { apps: BLOCKED });
      bridge.answerNext('install_check', { blocked: true });
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      expect(calls(bridge, 'install_check')).toBe(1);
      expect(calls(bridge, 'install_remaining_apps')).toBe(0);
    });

    test('unblocked: install_remaining_apps(order) runs exactly once, whatever happens next', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge, s } = await finished(result(), { apps: BLOCKED });
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);  // fałszywy most odpowiada „odblokowane”
      expect(bridge.calls.find((c) => c.method === 'install_remaining_apps')?.args).toEqual([ORDER]);
      expect(s.job?.kind).toBe('restore_apps');
      await vi.advanceTimersByTimeAsync(RECHECK_MS * 4);
      expect(calls(bridge, 'install_remaining_apps')).toBe(1);
      expect(calls(bridge, 'install_check')).toBe(1);
    });

    test('progress shows in the row; apps_done replaces the result in place', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge, s } = await finished(result(), { apps: BLOCKED });
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      bridge.emit('transfer:apps_progress', { stage: 'apps', done: 1, total: 2, current: 'Alfa' });
      await tick();
      expect(rowOf('Aplikacje').textContent).toMatch(/1 z 2/);
      expect(screen.queryByRole('button', { name: /Xiaomi blokuje instalację/ })).toBeNull();
      expect(screen.getByText('Prawie wszystko gotowe')).toBeTruthy();  // jeszcze nie „Wszystko wgrane”
      expect(screen.getByText(/Trwa instalacja pominiętych aplikacji/)).toBeTruthy();
      bridge.emit('transfer:apps_done', { order: ORDER, apps: appsView({ installed: 2, exists: 1 }) });
      s.job = null;
      await tick();
      expect(rowOf('Aplikacje').textContent).toMatch(/✓ 3/);
      expect(screen.getByText('Wszystko wgrane')).toBeTruthy();
      expect(screen.queryByRole('button', { name: /Xiaomi blokuje instalację/ })).toBeNull();
    });

    const err = (kindName: string, key: string) => ({ job_id: 'job-apps', kind: kindName, key, message: '' });

    test('a transient job error is not a global error: a note in the row, the promise stays and the next unblock retries', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge, s } = await finished(result(), { apps: BLOCKED });
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      expect(calls(bridge, 'install_remaining_apps')).toBe(1);
      bridge.emit('job:error', err('restore_apps', 'disconnected') as never);
      bridge.emit('job:end', { job_id: 'job-apps', kind: 'restore_apps' } as never);
      await tick();
      expect(s.error).toBeNull();
      expect(screen.queryByRole('alert')).toBeNull();
      expect(rowOf('Aplikacje').textContent).toMatch(/Telefon został odłączony/);
      expect(screen.getByRole('button', { name: /Xiaomi blokuje instalację/ })).toBeTruthy();
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      expect(calls(bridge, 'install_remaining_apps')).toBe(2);
    });

    test('a permanent job error drops the promise, shows the reason and never retries', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge, s } = await finished(result(), { apps: BLOCKED });
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      bridge.emit('job:error', err('restore_apps', 'transfer_failed') as never);
      bridge.emit('job:end', { job_id: 'job-apps', kind: 'restore_apps' } as never);
      await tick();
      expect(s.error).toBeNull();
      expect(screen.queryByRole('button', { name: /Xiaomi blokuje instalację/ })).toBeNull();
      expect(rowOf('Aplikacje').textContent).toMatch(/Wgrywanie nie powiodło się/);
      await vi.advanceTimersByTimeAsync(RECHECK_MS * 4);
      expect(calls(bridge, 'install_remaining_apps')).toBe(1);
    });

    test('install_remaining_apps refused for good (copy deleted): reason in the row, no promise, no retry', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge, s } = await finished(result(), { apps: BLOCKED });
      bridge.failNext('install_remaining_apps', 'transfer_copy_missing');
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      await vi.advanceTimersByTimeAsync(RECHECK_MS * 3);
      expect(calls(bridge, 'install_remaining_apps')).toBe(1);
      expect(s.error).toBeNull();
      expect(screen.queryByRole('button', { name: /Xiaomi blokuje instalację/ })).toBeNull();
      expect(rowOf('Aplikacje').textContent).toMatch(/Tej kopii nie ma już na komputerze/);
    });

    test.each(['busy', 'transfer_no_phone'])('install_remaining_apps refused with %s is tried again', async (key) => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge } = await finished(result(), { apps: BLOCKED });
      bridge.failNext('install_remaining_apps', key);
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      expect(calls(bridge, 'install_remaining_apps')).toBe(2);
    });

    test('apps_done that is still blocked re-arms the next unblock', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge, s } = await finished(result(), { apps: BLOCKED });
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      bridge.emit('transfer:apps_done', { order: ORDER, apps: BLOCKED });
      bridge.emit('job:end', { job_id: 'job-apps', kind: 'restore_apps' } as never);
      s.job = null;
      await tick();
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      expect(calls(bridge, 'install_remaining_apps')).toBe(2);
    });

    test('the checks stop when the screen is closed', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge, unmount } = await finished(result(), { apps: BLOCKED });
      unmount();
      await vi.advanceTimersByTimeAsync(RECHECK_MS * 3);
      expect(calls(bridge, 'install_check')).toBe(0);
    });

    test('a different order in apps_done changes nothing', async () => {
      const { bridge, s } = await finished(result(), { apps: BLOCKED });
      bridge.emit('transfer:apps_done', { order: 'ZS/2020/0101/09', apps: appsView() });
      await tick();
      expect(s.transfer.restore.appsResult?.blocked).toBe(true);
    });

    test('a failed install_check is silent: no error card, no install', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge, s } = await finished(result(), { apps: BLOCKED });
      bridge.failNext('install_check', 'internal', 'boom');
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      expect(s.error).toBeNull();
      expect(calls(bridge, 'install_remaining_apps')).toBe(0);
    });

    test('target phone not connected: no check at all', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge } = await finished(result(), { apps: BLOCKED, connected: false });
      await vi.advanceTimersByTimeAsync(RECHECK_MS * 3);
      expect(calls(bridge, 'install_check')).toBe(0);
    });

    test('no block: no checks', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge } = await finished(result(), { apps: appsView() });
      await vi.advanceTimersByTimeAsync(RECHECK_MS * 3);
      expect(calls(bridge, 'install_check')).toBe(0);
    });
  });
});
