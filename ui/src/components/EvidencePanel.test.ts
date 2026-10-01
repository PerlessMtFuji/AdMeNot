import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test } from 'vitest';
import { renderWith } from '../test-utils';
import EvidencePanel from './EvidencePanel.svelte';

test('evidence: score meter, grouped reasons with muted points, raw data, no rule codes', async () => {
  const { s } = await renderWith(EvidencePanel, 'empty', { app: null });
  expect(screen.getByText('Wybierz aplikację w tabeli.')).toBeTruthy();
  void s;
});

test('evidence for a flagged app', async () => {
  const app = {
    package: 'com.clean.pro.boost', name: 'Cleaner Pro', score: 100, verdict: 'malicious',
    verdict_label: 'Szkodliwa', confidence: 'high', confidence_label: 'wysoka', gaps: [],
    trusted: false, incomplete: false, is_system: false, from_play: false,
    installer: 'com.android.chrome', is_admin: true, default_level: 'remove', problems: [],
    apk_error: null, ad_sdks: null, symptoms: [], source: { label: 'Chrome', days: 3 },
    findings: [
      { rule_id: 'DM-OVERLAY-01', class: 'behavior', category: 'ads', label: 'Okna nad innymi aplikacjami', weight: 25, text: '', text_expert: 'appops SYSTEM_ALERT_WINDOW', evidence: {} },
      { rule_id: 'DM-ADMIN-01', class: 'position', category: 'removal', label: 'Administrator urządzenia', weight: 25, text: '', text_expert: 'device_policy', evidence: {} },
      { rule_id: 'DM-COMBO-02', class: 'combo', category: 'combo', label: 'Blokuje usunięcie i nachalnie wyświetla treści', weight: 15, text: '', text_expert: 'kombinacja', evidence: {} },
    ],
  } as const;
  const { container } = render(EvidencePanel, { props: { app: app as never } });
  expect(screen.getByRole('meter', { name: 'Wynik' }).getAttribute('aria-valuenow')).toBe('100');
  expect(screen.getByText('Reklamy')).toBeTruthy();
  expect(screen.getAllByText('Okna nad innymi aplikacjami')).toHaveLength(2); // powód + nagłówek surowego wpisu
  expect(screen.getAllByText('+25')).toHaveLength(2);
  expect(screen.getByText('Blokuje usunięcie i nachalnie wyświetla treści')).toBeTruthy();
  expect(container.textContent).not.toMatch(/DM-/);
  expect(screen.getByText('Surowe dane z telefonu')).toBeTruthy();
});

test('raw data: one entry per rule, ad SDK list only once', () => {
  const base = {
    package: 'com.x', name: 'X', score: 40, verdict: 'suspicious', verdict_label: 'Podejrzana',
    confidence: 'medium', confidence_label: 'średnia', gaps: [], trusted: false,
    incomplete: false, is_system: false, from_play: false, installer: null, is_admin: false, default_level: null,
    problems: [], apk_error: null, symptoms: [], source: { label: 'Chrome', days: 1 },
  };
  const sdk = { rule_id: 'DM-ADSDK-02', class: 'apk', category: 'ads', label: 'Wiele sieci reklamowych', weight: 20,
    text: '', text_expert: 'SDK reklamowe (5): a, b, c, d, e', evidence: {} };
  const alarm = { rule_id: 'DM-WAKE-01', class: 'behavior', category: 'background', label: 'Częste wybudzanie telefonu',
    weight: 10, text: '', text_expert: 'dumpsys alarm: 600 wybudzeń', evidence: {} };
  const first = render(EvidencePanel, { props: { app: { ...base, ad_sdks: ['a', 'b', 'c', 'd', 'e'], findings: [sdk, alarm] } as never } });
  const list = first.getByRole('list', { name: 'Surowe dane z telefonu' });
  expect(list.querySelectorAll('li')).toHaveLength(2);
  expect(list.textContent!.match(/a, b, c, d, e/g)).toHaveLength(1);
  first.unmount();

  // Bez reguły SDK (np. aplikacja systemowa) lista bibliotek dochodzi jako osobny wpis.
  const second = render(EvidencePanel, { props: { app: { ...base, ad_sdks: ['a', 'b'], findings: [alarm] } as never } });
  const rows = second.getByRole('list', { name: 'Surowe dane z telefonu' }).querySelectorAll('li');
  expect(rows).toHaveLength(2);
  expect(rows[1].textContent).toContain('Biblioteki reklamowe');
  expect(rows[1].textContent).toContain('a, b');
});

test('evidence: data gaps show an "Assessment limits" section and the confidence line', () => {
  const app = {
    package: 'com.x', name: 'X', score: 40, verdict: 'suspicious', verdict_label: 'Podejrzana',
    confidence: 'low', confidence_label: 'niska — …', gaps: [{ key: 'apk', label: 'analiza pliku APK' }],
    trusted: false, incomplete: true, is_system: false, from_play: false, installer: null, is_admin: false,
    default_level: null, problems: [], apk_error: null, ad_sdks: null, symptoms: [],
    source: { label: 'Chrome', days: 1 }, findings: [],
  };
  render(EvidencePanel, { props: { app: app as never } });
  expect(screen.getByText('Ograniczenia oceny')).toBeTruthy();
  expect(screen.getByText('analiza pliku APK')).toBeTruthy();
  expect(screen.getByText('Pewność wniosku')).toBeTruthy();
  expect(screen.getByText('niska — …')).toBeTruthy();
});

test('evidence: incomplete without gaps and APK scope notes still show the limits section', () => {
  const app = {
    package: 'com.x', name: 'X', score: 0, verdict: 'safe', verdict_label: 'Brak istotnych sygnałów (ocena niepełna)',
    confidence: 'low', confidence_label: 'niska', gaps: [], incomplete: true,
    scope: [{ key: 'obfuscated', label: 'Kod w dużej części zaciemniony' }],
    trusted: false, is_system: false, from_play: false, installer: null, is_admin: false,
    default_level: null, problems: [], apk_error: null, ad_sdks: [], symptoms: [],
    source: { label: 'Chrome', days: 1 }, findings: [],
  };
  render(EvidencePanel, { props: { app: app as never } });
  expect(screen.getByText('Ograniczenia oceny')).toBeTruthy();
  expect(screen.getByText('Mało danych o zachowaniu aplikacji')).toBeTruthy();
  expect(screen.getByText('Kod w dużej części zaciemniony')).toBeTruthy();
});

test('capability ladder: four columns, check / dash / question mark', () => {
  const app = {
    package: 'com.x', name: 'X', score: 10, verdict: 'review', verdict_label: 'Do sprawdzenia',
    confidence: 'low', confidence_label: 'niska', gaps: [], trusted: false, incomplete: false,
    is_system: false, from_play: false, installer: null, is_admin: false, default_level: null,
    problems: [], apk_error: null, ad_sdks: null, symptoms: [], source: { label: 'Chrome', days: 1 },
    findings: [],
    capabilities: [{ key: 'overlay', label: 'Okna nad innymi aplikacjami', levels: { declared: true, code: null, granted: false, observed: null } }],
  };
  render(EvidencePanel, { props: { app: app as never } });
  for (const h of ['Prosi', 'W kodzie', 'Przyznane', 'Zaobserwowane']) expect(screen.getByRole('columnheader', { name: h })).toBeTruthy();
  const row = screen.getByRole('row', { name: /Okna nad innymi aplikacjami/ });
  expect(row.textContent).toContain('✓');
  expect(row.textContent).toContain('—');
  expect(row.textContent).toContain('?');
});

test('deep analysis button for every app, also without findings; disabled without a phone', async () => {
  const app = {
    package: 'com.quiet.app', name: 'Quiet', score: 0, verdict: 'safe', verdict_label: 'Brak istotnych sygnałów',
    confidence: 'high', confidence_label: 'wysoka', gaps: [], trusted: false, incomplete: false, is_system: false,
    from_play: true, installer: 'com.android.vending', is_admin: false, default_level: null, problems: [],
    apk_error: null, ad_sdks: [], symptoms: [], source: { label: 'Sklep Play', days: 30 }, findings: [],
  };
  const { s, bridge, getByRole } = await renderWith(EvidencePanel, 'empty', { app });
  const button = getByRole('button', { name: 'Głęboka analiza' }) as HTMLButtonElement;
  expect(button.disabled).toBe(true); // bez telefonu
  s.device = { serial: 'S1' } as never;
  await tick();
  expect(button.disabled).toBe(false);
  await fireEvent.click(button);
  expect(bridge.calls.some((c) => c.method === 'deep_analyze' && c.args[0] === 'com.quiet.app')).toBe(true);
});
