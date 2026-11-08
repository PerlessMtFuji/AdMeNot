import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { defaultTransferSelection } from '../lib/logic';
import { RECHECK_MS } from '../lib/recheck';
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
    free_pc: 500e9, unreadable: 0, denied: [], exports: {}, ...over,
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

  test('ticking an app adds its APK size to the apps row and the total', async () => {
    await show({ apps: [
      { package: 'pl.bank', label: 'Bank', verdict: 'safe', default_on: true, bytes: 80 * MB },
      { package: 'com.sus.app', label: 'Latarka Pro', verdict: 'suspicious', default_on: false, bytes: 15 * MB },
    ] });
    const group = screen.getByRole('checkbox', { name: /^Aplikacje/ }).closest('section') as HTMLElement;
    expect(within(group).getByText('80 MB')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: /^Aplikacje: Pokaż/ }));
    expect(within(group).getByText('15 MB')).toBeTruthy();  // rozmiar przy aplikacji na liście
    await fireEvent.click(screen.getByRole('checkbox', { name: /Latarka Pro/ }));
    expect(within(group).getByText('95 MB')).toBeTruthy();  // suma panelu: test transferTotals w logic.test
  });

  test('suspicious apps are listed but unticked, harmful ones skipped', async () => {
    await show();
    expect(screen.getByText('1 podejrzana odznaczona')).toBeTruthy();
    expect(screen.getByText('1 szkodliwa — pominę')).toBeTruthy();
    expect(screen.getByText('same aplikacje, bez danych i logowań')).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: /Latarka Pro/ })).toBeNull();  // lista zwinięta
    await fireEvent.click(screen.getByRole('button', { name: /^Aplikacje: Pokaż/ }));
    expect((screen.getByRole('checkbox', { name: /Latarka Pro/ }) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole('checkbox', { name: /Bank/ }) as HTMLInputElement).checked).toBe(true);
  });

  test('the rows sit in three groups in the agreed order', async () => {
    await show();
    const groups = screen.getAllByRole('region').map((g) => g.getAttribute('aria-label'));
    expect(groups).toEqual(['Kontakty i wiadomości', 'Pliki', 'Aplikacje']);
    const names = screen.getAllByRole('checkbox').map((c) => c.getAttribute('aria-label'));
    expect(names.slice(0, 8)).toEqual(['Kontakty', 'SMS i MMS', 'Historia połączeń', 'Zdjęcia i filmy', 'Pobrane i dokumenty',
      'WhatsApp', 'Inne foldery', 'Aplikacje']);
  });

  test('other folders are folded and unticked until opened', async () => {
    await show({ others: [{ name: 'Music', files: 20, bytes: 500 * MB }] });
    expect(screen.queryByRole('checkbox', { name: /Music/ })).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: /^Inne foldery: Pokaż/ }));
    expect(screen.getByRole('checkbox', { name: /Music/ })).toBeTruthy();
  });

  test('an empty category gets a grey line, not a row', async () => {
    await show({ calls: 0, categories: { media: { files: 14210, bytes: 2000 * MB }, downloads: { files: 0, bytes: 0 },
      whatsapp: { files: 0, bytes: 0 } }, others: [] });
    expect(screen.queryByRole('checkbox', { name: /Historia połączeń/ })).toBeNull();
    expect(screen.queryByRole('checkbox', { name: /WhatsApp/ })).toBeNull();
    expect(screen.getByText('Brak na telefonie: Historia połączeń')).toBeTruthy();
    expect(screen.getByText('Brak na telefonie: Pobrane i dokumenty, WhatsApp, Inne foldery')).toBeTruthy();
  });

  test('the non-category key apps_malicious is never rendered as a category', async () => {
    await show({ counts: { apps_malicious: 3 } } as never);
    expect(screen.queryByText(/apps_malicious/)).toBeNull();
  });

  test('loose files in the main folder get a name', async () => {
    await show();
    await fireEvent.click(screen.getByRole('button', { name: /^Inne foldery: Pokaż/ }));
    expect(screen.getByRole('checkbox', { name: /Pliki w folderze głównym/ })).toBeTruthy();
  });

  test('the start button is disabled when nothing is selected', async () => {
    const { s } = await show();
    expect((screen.getByRole('button', { name: /Rozpocznij kopię/ }) as HTMLButtonElement).disabled).toBe(false);
    s.transfer.selection = { contacts: false, sms: false, mms: false, calls: false, categories: [], others: [], apps: [] };
    await tick();
    expect((screen.getByRole('button', { name: /Rozpocznij kopię/ }) as HTMLButtonElement).disabled).toBe(true);
  });

test('an old WhatsApp chat backup is a short label; the instructions open only on click', async () => {
    await show({ whatsapp_backup: '2020-01-01T02:00:00' });
    expect(screen.getByText('brak świeżej kopii czatów')).toBeTruthy();
    expect(screen.queryByTestId('whatsapp-note')).toBeNull();
    expect(screen.queryByText(/Utwórz kopię/)).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: /^WhatsApp: jak zrobić\?/ }));
    const note = screen.getByTestId('whatsapp-note');
    expect(within(note).getByText(/^Kopia czatów z .* — starsza niż godzina$/)).toBeTruthy();
    expect(within(note).getByText(/Utwórz kopię/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Sprawdź ponownie/ })).toBeNull();
    expect(screen.queryByRole('status')).toBeNull();  // już nie osobny baner
  });

  test('no WhatsApp chat backup: same label, instruction on click only', async () => {
    await show({ whatsapp_backup: null });
    expect(screen.getByText('brak świeżej kopii czatów')).toBeTruthy();
    expect(screen.queryByTestId('whatsapp-note')).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: /^WhatsApp: jak zrobić\?/ }));
    expect(within(screen.getByTestId('whatsapp-note')).getByText(/^Na telefonie: WhatsApp → .* → Utwórz kopię$/)).toBeTruthy();
  });

  test('a fresh WhatsApp chat backup shows no label and no fold', async () => {
    const d = new Date();  // czas lokalny, jak w moście
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
    await show({ whatsapp_backup: local });
    expect(screen.queryByText('brak świeżej kopii czatów')).toBeNull();
    expect(screen.queryByRole('button', { name: /^WhatsApp:/ })).toBeNull();
  });

  describe('automatic re-check', () => {
    afterEach(() => { vi.useRealTimers(); });
    const rescans = (b: { calls: { method: string }[] }) => b.calls.filter((c) => c.method === 'transfer_rescan').length;
    const waChecks = (b: { calls: { method: string }[] }) => b.calls.filter((c) => c.method === 'transfer_whatsapp').length;

    test('with the WhatsApp fold open the bridge is asked every RECHECK_MS; with it closed, never', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge } = await show({ whatsapp_backup: null });
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      expect(waChecks(bridge)).toBe(0);  // rozwinięcie zamknięte
      await fireEvent.click(screen.getByRole('button', { name: /^WhatsApp: jak zrobić\?/ }));
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      expect(waChecks(bridge)).toBeGreaterThan(0);
    });

    test('with an export fold open the phone is re-read after RECHECK_MS; with it closed, never', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge } = await show({ contacts: null, denied: ['contacts'] });
      await vi.advanceTimersByTimeAsync(RECHECK_MS * 2 + 100);
      expect(rescans(bridge)).toBe(0);
      await fireEvent.click(screen.getByRole('button', { name: /^Kontakty: jak skopiować\?/ }));
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      expect(rescans(bridge)).toBeGreaterThan(0);
    });

    test('no re-check while another phone read is in progress', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { s, bridge } = await show({ contacts: null, denied: ['contacts'] });
      await fireEvent.click(screen.getByRole('button', { name: /^Kontakty: jak skopiować\?/ }));
      s.job = { id: 'job-9', kind: 'transfer_scan' } as never;
      await tick();
      await vi.advanceTimersByTimeAsync(RECHECK_MS * 2 + 100);
      expect(rescans(bridge)).toBe(0);
    });
  });

const XIAOMI = { serial: 'R58T00TEST', manufacturer: 'Xiaomi', brand: 'Redmi' } as never;
  const vcf = (name: string, count: number | null, mtime: string, size = 2000) =>
    ({ remote: `/sdcard/Kopia/${name}`, name, size, mtime, count });
  const THREE = [vcf('kontakty_2026-10-27.vcf', 3, '2026-10-27T20:41:00'), vcf('contacts.vcf', 214, '2025-03-12T10:00:00'),
    vcf('00001.vcf', 198, '2024-01-03T09:00:00')];

  async function onXiaomi(over: Partial<InventoryView>) {
    const env = await show(over);
    env.s.device = XIAOMI;
    await tick();
    return env;
  }
  const meta = (name: RegExp) => screen.getByRole('checkbox', { name }).parentElement!.textContent!;
  const openFold = (row: string) => fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${row}: `) }));

  test('unreadable export data: a short label, no instructions and no re-check button until clicked', async () => {
    await show({ contacts: null, denied: ['contacts'] });
    expect(screen.getByText('telefon nie pozwala odczytać')).toBeTruthy();
    expect(screen.queryByTestId('export-note-contacts')).toBeNull();
    expect(screen.queryByText(/Wyeksportuj kontakty/)).toBeNull();
    expect(screen.queryByRole('button', { name: /Sprawdź ponownie/ })).toBeNull();
    await openFold('Kontakty');
    expect(screen.getByText(/^Wyeksportuj kontakty do pliku \.vcf w aplikacji Kontakty/)).toBeTruthy();
    expect(screen.getByText(/Sprawdzam sam co kilka sekund/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Sprawdź ponownie/ })).toBeNull();
  });

  test('denied contacts on a Xiaomi use the newest export file; picking another changes the count', async () => {
    const { s } = await onXiaomi({ contacts: null, denied: ['contacts'], exports: { contacts: THREE } });
    const box = screen.getByRole('checkbox', { name: /Kontakty/ }) as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(box.disabled).toBe(false);
    expect(meta(/Kontakty/)).toContain('3 z pliku eksportu');
    expect(screen.queryByText('telefon nie pozwala odczytać')).toBeNull();  // plik jest, wiersz nie jest już problemem
    await openFold('Kontakty');
    const note = screen.getByTestId('export-note-contacts');
    expect(within(note).getByRole('radiogroup', { name: 'Pliki eksportu na telefonie · Kontakty' })).toBeTruthy();
    // instrukcja (z dopiskiem o Xiaomi) zwinięta, gdy jest z czego wybierać
    const howto = within(note).getByText('Brak aktualnego pliku? Jak go zrobić').closest('details')!;
    expect(howto.open).toBe(false);
    expect(within(howto).getByText(/Xiaomi wpuszcza do tych danych tylko z opcją/)).toBeTruthy();
    expect(screen.queryByText('Na nowym telefonie otworzy się import — wybierzesz konto Google.')).toBeNull();
    const radios = within(screen.getByRole('radiogroup')).getAllByRole('radio') as HTMLInputElement[];
    expect(radios).toHaveLength(3);
    expect(radios[0].checked).toBe(true);
    expect(radios[0].closest('label')!.textContent).toContain('najnowszy');
    expect(radios[1].closest('label')!.textContent).not.toContain('najnowszy');

    await fireEvent.click(radios[1]);
    expect(s.transfer.selection.exports?.contacts).toBe('/sdcard/Kopia/contacts.vcf');
    expect(meta(/Kontakty/)).toContain('214 z pliku eksportu');
  });

  test('a file too big to count shows its size in the list and no count in the row', async () => {
    await onXiaomi({ contacts: null, denied: ['contacts'],
      exports: { contacts: [vcf('duzy.vcf', null, '2026-10-27T20:41:00', 2.4 * MB)] } });
    expect(meta(/Kontakty/)).toContain('z pliku eksportu');
    expect(meta(/Kontakty/)).not.toMatch(/\d+ z pliku eksportu/);
    await openFold('Kontakty');
    expect(within(screen.getByRole('radiogroup')).getByText('2 MB')).toBeTruthy();
  });

  test('an export file without a usable date is listed without one', async () => {
    await onXiaomi({ contacts: null, denied: ['contacts'],
      exports: { contacts: [{ ...vcf('stary.vcf', 5, ''), mtime: null }] } });
    await openFold('Kontakty');
    const radio = within(screen.getByRole('radiogroup')).getByRole('radio');
    expect(radio.closest('label')!.textContent).toContain('stary.vcf');
    expect(radio.closest('label')!.textContent).not.toMatch(/1970|Invalid/);  // nie data z null (epoka)
  });

  test('no export file: the row stays unavailable and the fold says how to make one', async () => {
    await onXiaomi({ contacts: null, denied: ['contacts'] });
    const box = screen.getByRole('checkbox', { name: /Kontakty/ }) as HTMLInputElement;
    expect(box.disabled).toBe(true);
    expect(meta(/Kontakty/)).toContain('telefon nie pozwala odczytać');
    await openFold('Kontakty');
    expect(screen.getByText(/^Bez niej wyeksportuj kontakty do pliku \.vcf w aplikacji Kontakty/)).toBeTruthy();
    expect(screen.queryByRole('radiogroup')).toBeNull();
  });

  test('denied contacts and messages get a row label each', async () => {
    await onXiaomi({ contacts: null, sms: null, mms: null, denied: ['contacts', 'sms'],
      exports: { contacts: THREE, sms: [{ remote: '/sdcard/Backup/sms.xml', name: 'sms.xml', size: 147, mtime: '2026-10-27T20:00:00', count: 60 }] } });
    await openFold('Kontakty');
    await openFold('SMS i MMS');
    expect(within(screen.getByTestId('export-note-contacts')).getByRole('radiogroup')).toBeTruthy();
    expect(within(screen.getByTestId('export-note-sms')).getByRole('radiogroup')).toBeTruthy();
    expect(screen.getAllByRole('radiogroup')).toHaveLength(2);
    expect(meta(/SMS i MMS/)).toContain('60 z pliku eksportu');
  });

  test('a read error that is not a refusal gets its own label and no Xiaomi sentence', async () => {
    await onXiaomi({ sms: null, mms: null });
    expect((screen.getByRole('checkbox', { name: /SMS i MMS/ }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText('nie udało się odczytać')).toBeTruthy();
    await openFold('SMS i MMS');
    expect(screen.queryByText(/Xiaomi wpuszcza/)).toBeNull();
  });

  test('other brands get no Xiaomi sentence even when refused', async () => {
    const { s } = await show({ contacts: null, denied: ['contacts'] });
    s.device = { serial: 'R58T00TEST', manufacturer: 'samsung', brand: 'samsung' } as never;
    await tick();
    await openFold('Kontakty');
    expect(screen.queryByText(/Xiaomi wpuszcza/)).toBeNull();
    expect(screen.getByText(/^Wyeksportuj kontakty do pliku \.vcf/)).toBeTruthy();
    expect(screen.queryByText(/Bez niej/)).toBeNull();
  });

  test('a read error that is not a refusal explains the export without "Bez niej", even on a Xiaomi', async () => {
    await onXiaomi({ contacts: null });
    await openFold('Kontakty');
    expect(screen.getByText(/^Wyeksportuj kontakty do pliku \.vcf/)).toBeTruthy();
    expect(screen.queryByText(/Bez niej/)).toBeNull();
  });

  test('each row explains only its own export: contacts from Contacts, messages and calls from SMS Backup & Restore', async () => {
    await show({ contacts: null, sms: null, mms: null, calls: null, denied: ['contacts', 'sms', 'calls'] });
    for (const r of ['Kontakty', 'SMS i MMS', 'Historia połączeń']) await openFold(r);
    const howto = (k: string) => within(screen.getByTestId(`export-note-${k}`)).getByText(/^Wyeksportuj/).textContent!;
    expect(howto('contacts')).toMatch(/^Wyeksportuj kontakty do pliku \.vcf w aplikacji Kontakty/);
    expect(howto('contacts')).not.toContain('SMS Backup');
    expect(howto('sms')).toMatch(/^Wyeksportuj wiadomości do pliku aplikacją typu SMS Backup & Restore/);
    expect(howto('sms')).not.toContain('Kontakty');
    expect(howto('calls')).toMatch(/^Wyeksportuj historię połączeń do pliku aplikacją typu SMS Backup & Restore/);
    for (const k of ['contacts', 'sms', 'calls']) expect(howto(k)).not.toContain('Sprawdź ponownie');
  });

test('unticking the row sends no export file', async () => {
    const { bridge } = await onXiaomi({ contacts: null, denied: ['contacts'], exports: { contacts: THREE } });
    await fireEvent.click(screen.getByRole('checkbox', { name: /Kontakty/ }));
    await fireEvent.click(screen.getByRole('button', { name: /Rozpocznij kopię/ }));
    const sent = bridge.calls.find((c) => c.method === 'start_backup')?.args[0] as Record<string, unknown>;
    expect(sent.contacts).toBe(false);
    expect((sent.exports as Record<string, string> | undefined)?.contacts).toBeUndefined();
  });

  test('a selection bigger than the free disk space cannot start', async () => {
    await show({ free_pc: 100 * MB });
    expect(screen.getByText('Za mało miejsca na dysku komputera na tę kopię.')).toBeTruthy();
    expect((screen.getByRole('button', { name: /Rozpocznij kopię/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  test('the privacy note names the retention from settings', async () => {
    const { s } = await show();
    expect(screen.getByText(/Usunę ją automatycznie po 7 dniach/)).toBeTruthy();
    s.settings = { ...s.settings, transfer_keep_days: 14 };
    await tick();
    expect(screen.getByText(/Usunę ją automatycznie po 14 dniach/)).toBeTruthy();
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
    s.transfer.resumable = { id: 'S/1', serial: 'R58T00TEST', model: 'SM-A145R', manufacturer: 'samsung', client: null, created: '2026-10-24T14:20:00',
      expires: '2026-10-31T14:20:00', days_left: 6, status: 'in_progress', bytes: 0, counts: {} };
    await tick();
    await fireEvent.click(screen.getByRole('button', { name: 'Wznów' }));
    expect(bridge.calls.some((c) => c.method === 'start_backup')).toBe(true);
  });

  test('resuming needs free space only for the part not copied yet', async () => {
    // wybór ~3 GB; 2 GB już na dysku (wolne miejsce zmalało właśnie o nie), wolne 1,5 GB
    const { s } = await show({ free_pc: 1500 * MB });

    expect((screen.getByRole('button', { name: /Rozpocznij kopię/ }) as HTMLButtonElement).disabled).toBe(true);
    s.transfer.resumable = { id: 'S/1', serial: 'R58T00TEST', model: 'SM-A145R', manufacturer: 'samsung', client: null, created: '2026-10-24T14:20:00',
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

