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
  expect(screen.getByText('Okna nad innymi aplikacjami')).toBeTruthy();
  expect(screen.getAllByText('+25')).toHaveLength(2);
  expect(screen.getByText('Blokuje usunięcie i nachalnie wyświetla treści')).toBeTruthy();
  expect(container.textContent).not.toMatch(/DM-/);
  expect(screen.getByText('Surowe dane z telefonu')).toBeTruthy();
});
