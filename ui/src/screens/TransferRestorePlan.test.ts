import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test } from 'vitest';
import { defaultUploadChoice } from '../lib/logic';
import type { CopyView, RestoreApk, RestorePlanView, TelPlanView } from '../lib/types';
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

async function show(over: { plan?: Partial<RestorePlanView>; copy?: Partial<CopyView>; sameRecent?: boolean;
  tel?: TelPlanView | null } = {}) {
  const env = await setupCtl('transfer_restore');
  env.s.phase = 'transfer_restore_plan';
  env.s.serial = 'R58W20NEW01';
  const plan = { ...PLAN, ...over.plan };
  const tel = over.tel === undefined ? TEL : over.tel;
  Object.assign(env.s.transfer.restore, { plan, tel, copy: { ...COPY, ...over.copy }, choice: defaultUploadChoice(plan, tel),
    sameRecent: over.sameRecent ?? false });
  const view = render(TransferRestorePlan, { context: new Map([['ctl', env.ctl]]) });
  await tick();
  return { ...env, ...view };
}

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

  test('groups show counts, files already on the phone and files saved beside', async () => {
    await show();
    expect(screen.getByRole('checkbox', { name: /Zdjęcia/ })).toBeTruthy();
    expect(screen.getByText(/już na telefonie: 3/)).toBeTruthy();
    expect(screen.getByText(/zapisane obok: 1/)).toBeTruthy();
    expect(screen.getByRole('checkbox', { name: /Music/ })).toBeTruthy();
  });

  test('APK files: a harmful one has no checkbox, a suspicious one can be ticked', async () => {
    const { s } = await show();
    expect(screen.getByText('pominięty jako szkodliwy')).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: /cleaner\.apk/ })).toBeNull();
    expect(screen.getByText('sprawdzony')).toBeTruthy();
    expect(screen.getByText('nie do oceny')).toBeTruthy();
    expect(screen.getByText('podejrzany — odznaczony')).toBeTruthy();
    await fireEvent.click(screen.getByRole('checkbox', { name: /gra\.apk/ }));
    expect(s.transfer.restore.choice.apks_on).toEqual(['/sdcard/Download/gra.apk']);
  });

  test('later steps (apps, WhatsApp chats) are greyed out "in the next version" without checkboxes', async () => {
    await show();
    const later = screen.getByRole('region', { name: 'Później w programie' });
    expect(later.querySelectorAll('input').length).toBe(0);
    expect(later.textContent).toMatch(/Aplikacje/);
    expect(later.textContent).not.toMatch(/SMS|Kontakty/);
    expect(later.textContent).toMatch(/w kolejnej wersji/);
  });

  test('contacts and messages: counts, synced accounts, messenger contacts; a kind missing from the copy is hidden', async () => {
    const { s } = await show();
    const tel = screen.getByRole('region', { name: 'Kontakty i wiadomości' });
    expect(tel.textContent).toMatch(/do wgrania: 12/);
    expect(tel.textContent).toMatch(/już na telefonie: 4/);
    expect(tel.textContent).toMatch(/do wgrania: 320/);  // SMS z MMS
    expect(screen.getByText('40 kontaktów przyjdzie z konta anna@gmail.com po synchronizacji')).toBeTruthy();
    expect(screen.getByText('pominięto 5 kontaktów z komunikatorów')).toBeTruthy();
    expect(screen.queryByRole('checkbox', { name: /Historia połączeń/ })).toBeNull();
    expect(screen.queryByText(/możliwe duplikaty/)).toBeNull();
    expect(s.transfer.restore.choice.tel).toEqual(['contacts', 'sms']);
    await fireEvent.click(screen.getByRole('checkbox', { name: /SMS i MMS/ }));
    expect(s.transfer.restore.choice.tel).toEqual(['contacts']);
  });

  test('contacts already on the phone: an info banner about duplicates', async () => {
    await show({ tel: { ...TEL, phone_has_contacts: true } });
    expect(screen.getByText('Na telefonie są już kontakty — możliwe duplikaty')).toBeTruthy();
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
});
