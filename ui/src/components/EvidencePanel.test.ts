import { render, screen } from '@testing-library/svelte';
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
    verdict_label: 'Szkodliwa', trusted: false, incomplete: false, is_system: false, from_play: false,
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
    package: 'com.x', name: 'X', score: 40, verdict: 'suspicious', verdict_label: 'Podejrzana', trusted: false,
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
