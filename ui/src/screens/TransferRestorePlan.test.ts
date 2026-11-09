import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { RECHECK_MS } from '../lib/recheck';
import { defaultUploadChoice } from '../lib/logic';
import type { AppsPlanItem, AppsPlanView, CopyView, RestoreApk, RestorePlanView, TelPlanView } from '../lib/types';
import { setupCtl } from '../test-utils';
import TransferRestorePlan from './TransferRestorePlan.svelte';

const GiB = 1024 ** 3;
const COPY: CopyView = { id: 'OLD/1', serial: 'OLD', model: 'SM-A145R', manufacturer: 'samsung', client: 'Anna K.',
  created: '2026-10-25T14:30:00', expires: '2026-11-01T14:30:00', days_left: 7, status: 'complete', bytes: 11 * GiB,
  counts: { files: 20, files_failed: 0, apps: 0, apps_failed: 0, unreadable: 0 }, restores: [] };
const apk = (name: string, outcome: RestoreApk['outcome'], default_on: boolean): RestoreApk => ({ remote: `/sdcard/Download/${name}`,
  name, group: 'downloads', bytes: 1000, action: 'push', outcome, level: outcome === 'malicious' ? 'ioc' : 'static', default_on });
const PLAN: RestorePlanView = {
  groups: { photos: { files: 10, bytes: 6 * GiB, exists: 3, rename: 1 }, videos: { files: 2, bytes: 5 * GiB, exists: 0, rename: 0 },
    downloads: { files: 4, bytes: 2000, exists: 0, rename: 0 } },
  others: [{ name: 'Music', files: 1, bytes: 400, exists: 0, rename: 0 }],
  apks: [apk('bank.apk', 'clean', true), apk('gra.apk', 'suspicious', false), apk('cleaner.apk', 'malicious', false),
    apk('paczka.xapk', 'unknown', true)],
  space: { free: 10 * GiB, total: 64 * GiB }, reserve: GiB, missing: 0,
};

const TEL: TelPlanView = {
  contacts: { write: 12, existing: 4, skipped_synced: [{ account: 'anna@gmail.com', count: 40 }], skipped_messenger: 5 },
  sms: { write: 300, existing: 0 }, mms: { write: 20, existing: 0 }, calls: null, phone_has_contacts: false,
  readable: { contacts: true, sms: true, calls: true },
};

const item = (name: string, over: Partial<AppsPlanItem> = {}): AppsPlanItem => ({ package: `com.test.${name.toLowerCase().replace(/\s/g, '')}`,
  name, bytes: 100 * 1024 ** 2, verdict: 'safe', default_on: true, skip: null, ...over });
const APPS: AppsPlanView = { block: null, bytes: 300 * 1024 ** 2, items: [
  item('Allegro'), item('Bolt'), item('Cleaner Max', { verdict: 'suspicious', default_on: false }),
  item('WhatsApp', { skip: 'installed' }), item('Gra XYZ', { skip: 'too_old' })] };

async function show(over: { plan?: Partial<RestorePlanView>; copy?: Partial<CopyView>; sameRecent?: boolean;
  tel?: TelPlanView | null; apps?: AppsPlanView | null; android?: string } = {}) {
  const env = await setupCtl('transfer_restore');
  env.s.phase = 'transfer_restore_plan';
  env.s.serial = 'R58W20NEW01';
  if (over.android) env.s.device = { serial: 'R58W20NEW01', name: 'Nowy', model: 'SM-A546B', android: over.android } as never;
  const plan = { ...PLAN, ...over.plan };
  const tel = over.tel === undefined ? TEL : over.tel;
  const apps = over.apps === undefined ? null : over.apps;
  Object.assign(env.s.transfer.restore, { plan, tel, apps, copy: { ...COPY, ...over.copy },
    choice: defaultUploadChoice(plan, tel, false, apps), sameRecent: over.sameRecent ?? false });
  const view = render(TransferRestorePlan, { context: new Map([['ctl', env.ctl]]) });
  await tick();
  return { ...env, ...view };
}
const openFold = (row: string) => fireEvent.click(screen.getByRole('button', { name: new RegExp(`^${row}: `) }));

describe('TransferRestorePlan', () => {
  test('not enough space: warning and no upload; unticking videos makes it fit', async () => {
    await show();
    expect(screen.getByText('Brakuje 2,0 GB na nowym telefonie — odznacz część danych')).toBeTruthy();
    const upload = screen.getByRole('button', { name: /^Wgraj/ }) as HTMLButtonElement;
    expect(upload.disabled).toBe(true);
    await fireEvent.click(screen.getByRole('checkbox', { name: /Filmy/ }));
    expect(screen.queryByText(/Brakuje/)).toBeNull();
    expect(screen.getByText('zostanie 4,0 GB wolnego')).toBeTruthy();
    expect(upload.disabled).toBe(false);
  });

  test('groups show counts, files already on the phone and files saved beside; other folders are folded', async () => {
    await show();
    expect(screen.getByRole('checkbox', { name: /Zdjęcia/ })).toBeTruthy();
    expect(screen.getByText(/już na telefonie: 3/)).toBeTruthy();
    expect(screen.getByText(/zapisane obok: 1/)).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: /Music/ })).toBeNull();
    await openFold('Inne foldery');
    expect(screen.getByRole('checkbox', { name: /Music/ })).toBeTruthy();
  });

  test('APK files: pills on the Downloads row, the list is folded; a harmful one has no checkbox, a suspicious one can be ticked', async () => {
    const { s } = await show();
    expect(screen.getByText('1 APK szkodliwy — pominę')).toBeTruthy();
    expect(screen.getByText('1 APK podejrzany — odznaczony')).toBeTruthy();
    expect(screen.queryByText('pominięty jako szkodliwy')).toBeNull();  // lista jest zwinięta
    await openFold('Pobrane i dokumenty');
    expect(screen.getByText('pominięty jako szkodliwy')).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: /cleaner\.apk/ })).toBeNull();
    expect(screen.getByText('sprawdzony')).toBeTruthy();
    expect(screen.getByText('nie do oceny')).toBeTruthy();
    expect(screen.getByText('podejrzany — odznaczony')).toBeTruthy();
    await fireEvent.click(screen.getByRole('checkbox', { name: /gra\.apk/ }));
    expect(s.transfer.restore.choice.apks_on).toEqual(['/sdcard/Download/gra.apk']);
  });

  test('there is no "later in the program / next version" section', async () => {
    await show({ apps: APPS });
    expect(screen.queryByText(/Później w programie/)).toBeNull();
    expect(screen.queryByText(/w kolejnej wersji/)).toBeNull();
  });

  test('groups are calm cards: Contacts and messages, Files, Apps; an empty category is one grey line', async () => {
    await show({ apps: APPS });
    expect(screen.getByRole('region', { name: 'Kontakty i wiadomości' })).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Pliki' })).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Aplikacje' })).toBeTruthy();
    expect(screen.getByText('Brak w kopii: Historia połączeń')).toBeTruthy();
    expect(screen.getByText('Brak w kopii: WhatsApp')).toBeTruthy();
  });

  test('contacts and messages: counts, synced accounts, messenger contacts; a kind missing from the copy is hidden', async () => {
    const { s } = await show();
    const tel = screen.getByRole('region', { name: 'Kontakty i wiadomości' });
    expect(tel.textContent).toMatch(/Kontakty\s*12/);
    expect(tel.textContent).toMatch(/już na telefonie: 4/);
    expect(tel.textContent).toMatch(/SMS i MMS\s*320/);  // SMS z MMS
    expect(screen.getByText(/40 kontaktów przyjdzie z konta anna@gmail.com po synchronizacji/)).toBeTruthy();
    expect(screen.getByText(/pominięto 5 kontaktów z komunikatorów/)).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: /Historia połączeń/ })).toBeNull();
    expect(screen.queryByText(/możliwe duplikaty/)).toBeNull();
    expect(s.transfer.restore.choice.tel).toEqual(['contacts', 'sms']);
    await fireEvent.click(screen.getByRole('checkbox', { name: /SMS i MMS/ }));
    expect(s.transfer.restore.choice.tel).toEqual(['contacts']);
  });

  test('contacts already on the phone: a grey note in the row, not a banner', async () => {
    await show({ tel: { ...TEL, phone_has_contacts: true } });
    const note = screen.getByText(/możliwe duplikaty/);
    expect(note.closest('[role="alert"], [role="status"]')).toBeNull();
    expect(screen.getByRole('checkbox', { name: 'Kontakty' }).parentElement!.contains(note)).toBe(true);
  });

  test('only contacts and messages ticked: the upload can start without files', async () => {
    const { s } = await show({ plan: { groups: {}, others: [], apks: [] } });
    expect(s.transfer.restore.choice.groups).toEqual([]);
    expect((screen.getByRole('button', { name: /^Wgraj/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  test('a copy without telephony has no contacts and messages section', async () => {
    await show({ tel: null });
    expect(screen.queryByRole('region', { name: 'Kontakty i wiadomości' })).toBeNull();
  });

  test('the same phone as the copy, copied recently: a dialog with focus on "No"', async () => {
    await show({ sameRecent: true });
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(document.activeElement?.textContent?.trim()).toBe('Nie');
  });

  test('an incomplete copy warns with what is missing; files gone from the PC are counted', async () => {
    await show({ copy: { status: 'incomplete', counts: { files: 20, files_failed: 3, apps: 0, apps_failed: 1, unreadable: 0 } },
      plan: { missing: 2 } });
    expect(screen.getByText('Kopia jest niepełna')).toBeTruthy();
    expect(screen.getByText(/nieudane pliki: 3/)).toBeTruthy();
    expect(screen.getByText(/nie ma już 2 plików z kopii/)).toBeTruthy();
  });

  describe('apps', () => {
    afterEach(() => { vi.useRealTimers(); });
    const installChecks = (b: { calls: { method: string }[] }) => b.calls.filter((c) => c.method === 'install_check').length;
    const many = (n: number) => Array.from({ length: n }, (_, i) => item(`Appka ${String(i).padStart(3, '0')}`));
    const XIAOMI_APPS: AppsPlanView = { ...APPS, block: 'xiaomi' };
    const ONE_PHOTO = { groups: { photos: { files: 1, bytes: 1000, exists: 0, rename: 0 } }, others: [], apks: [] };

    test('the row says "N z M", suspicious unticked by default; skipped apps are not selectable', async () => {
      const { s } = await show({ apps: APPS });
      expect(screen.getByText('2 z 5')).toBeTruthy();
      expect(s.transfer.restore.choice.apps).toEqual(['com.test.allegro', 'com.test.bolt']);
      await openFold('Aplikacje');
      expect((screen.getByRole('checkbox', { name: /Allegro/ }) as HTMLInputElement).checked).toBe(true);
      expect((screen.getByRole('checkbox', { name: /Cleaner Max/ }) as HTMLInputElement).checked).toBe(false);
      expect(screen.queryByRole('checkbox', { name: /Gra XYZ/ })).toBeNull();
      expect(screen.queryByRole('checkbox', { name: /^WhatsApp$/ })).toBeNull();
      await fireEvent.click(screen.getByRole('checkbox', { name: /Cleaner Max/ }));
      expect(s.transfer.restore.choice.apps).toContain('com.test.cleanermax');
    });

    test('the skipped apps are one grey line at the bottom of the fold, with the target Android version', async () => {
      await show({ apps: APPS, android: '15' });
      expect(screen.queryByText(/Nie zainstaluję/)).toBeNull();
      await openFold('Aplikacje');
      expect(screen.getByText('Nie zainstaluję: WhatsApp — już jest · Gra XYZ — za stara dla Androida 15')).toBeTruthy();
    });

    test('too old without a known Android version still says something sensible', async () => {
      await show({ apps: APPS });
      await openFold('Aplikacje');
      expect(screen.getByText(/Gra XYZ — za stara dla tego Androida/)).toBeTruthy();
    });

    test('other skip reasons have their own wording', async () => {
      const apps = { ...APPS, items: [item('A', { skip: 'too_new' }), item('B', { skip: 'no_abi' }), item('C', { skip: 'incomplete' }), item('D')] };
      await show({ apps });
      await openFold('Aplikacje');
      expect(screen.getByText('Nie zainstaluję: A — wymaga nowszego Androida · B — brak wersji dla tego procesora · C — niepełna kopia')).toBeTruthy();
    });

    test('the apps size counts only the selected apps, in the row and in the panel', async () => {
      const { s } = await show({ apps: APPS, plan: { groups: {}, others: [], apks: [] } });
      const panel = screen.getByRole('complementary');
      expect(panel.textContent).toMatch(/Do wgrania\s*0,2 GB/);
      await openFold('Aplikacje');
      await fireEvent.click(screen.getByRole('checkbox', { name: /Cleaner Max/ }));
      expect(panel.textContent).toMatch(/Do wgrania\s*0,3 GB/);
      await fireEvent.click(screen.getByRole('checkbox', { name: /Bolt/ }));
      expect(panel.textContent).toMatch(/Do wgrania\s*0,2 GB/);
      expect(s.transfer.restore.choice.apps).toEqual(['com.test.allegro', 'com.test.cleanermax']);
    });

    test('selected apps count against the free space', async () => {
      const big: AppsPlanView = { ...APPS, items: [item('Gigant', { bytes: 12 * GiB })] };
      await show({ apps: big, plan: { groups: {}, others: [], apks: [] } });
      expect(screen.getByText(/Brakuje/)).toBeTruthy();
      expect((screen.getByRole('button', { name: /^Wgraj/ }) as HTMLButtonElement).disabled).toBe(true);
      await fireEvent.click(screen.getByRole('checkbox', { name: 'Aplikacje' }));
      expect(screen.queryByText(/Brakuje/)).toBeNull();
    });

    test('150 apps: the list is folded, after opening all of them are there', async () => {
      await show({ apps: { ...APPS, items: many(150) } });
      expect(screen.getByText('150 z 150')).toBeTruthy();
      expect(screen.queryByRole('checkbox', { name: /Appka 000/ })).toBeNull();
      await openFold('Aplikacje');
      expect(screen.getAllByRole('checkbox', { name: /^Appka / }).length).toBe(150);
    });

    test('Xiaomi: only a label in the row; the instruction appears after a click and goes away after another', async () => {
      await show({ apps: XIAOMI_APPS });
      const label = screen.getByRole('button', { name: /Xiaomi blokuje instalację · jak włączyć\?/ });
      expect(screen.queryByText(/Instaluj przez USB/)).toBeNull();
      expect(label.getAttribute('aria-expanded')).toBe('false');
      await fireEvent.click(label);
      expect(screen.getByText(/Instaluj przez USB/)).toBeTruthy();
      expect(label.getAttribute('aria-expanded')).toBe('true');
      await fireEvent.click(label);
      expect(screen.queryByText(/Instaluj przez USB/)).toBeNull();
    });

    test('Xiaomi block does not stop the upload', async () => {
      await show({ apps: XIAOMI_APPS, plan: ONE_PHOTO });
      expect((screen.getByRole('button', { name: /^Wgraj/ }) as HTMLButtonElement).disabled).toBe(false);
    });

    test('install_check runs every RECHECK_MS only while the block lasts; unblocked removes the label', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge, s } = await show({ apps: XIAOMI_APPS });
      bridge.answerNext('install_check', { blocked: true });
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);
      expect(installChecks(bridge)).toBe(1);
      expect(screen.getByRole('button', { name: /Xiaomi blokuje instalację/ })).toBeTruthy();
      await vi.advanceTimersByTimeAsync(RECHECK_MS + 100);  // fałszywy most odpowiada teraz „odblokowane”
      expect(installChecks(bridge)).toBe(2);
      expect(screen.queryByRole('button', { name: /Xiaomi blokuje instalację/ })).toBeNull();
      expect(s.transfer.restore.apps?.block).toBeNull();
      await vi.advanceTimersByTimeAsync(RECHECK_MS * 3);
      expect(installChecks(bridge)).toBe(2);
    });

    test('no install_check without a block', async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const { bridge } = await show({ apps: APPS });
      await vi.advanceTimersByTimeAsync(RECHECK_MS * 3);
      expect(installChecks(bridge)).toBe(0);
    });

    test('start sends the chosen packages as apps', async () => {
      const { bridge } = await show({ apps: APPS, plan: ONE_PHOTO });
      await fireEvent.click(screen.getByRole('button', { name: /^Wgraj/ }));
      const call = bridge.calls.find((c) => c.method === 'start_restore')!;
      expect((call.args[0] as { apps: string[] }).apps).toEqual(['com.test.allegro', 'com.test.bolt']);
    });

    test('the panel shows the size with a time estimate and one line about the safety copy', async () => {
      await show({ apps: APPS, plan: ONE_PHOTO });
      expect(screen.getByRole('button', { name: /^Wgraj/ }).textContent).toMatch(/0,2 GB · ok\. \d+ min/);
      expect(screen.getByText(/kopię bezpieczeństwa/)).toBeTruthy();
    });

    test('no telephony chosen: no promise of a safety copy', async () => {
      const { s } = await show({ apps: APPS, plan: ONE_PHOTO, tel: null });
      expect(s.transfer.restore.choice.tel).toEqual([]);
      expect(screen.queryByText(/kopię bezpieczeństwa/)).toBeNull();
    });

    test('unticking every telephony kind hides the safety copy line', async () => {
      await show({ apps: APPS, plan: ONE_PHOTO });
      expect(screen.getByText(/kopię bezpieczeństwa/)).toBeTruthy();
      await fireEvent.click(screen.getByRole('checkbox', { name: 'Kontakty' }));
      await fireEvent.click(screen.getByRole('checkbox', { name: /SMS i MMS/ }));
      expect(screen.queryByText(/kopię bezpieczeństwa/)).toBeNull();
    });
  });
});
