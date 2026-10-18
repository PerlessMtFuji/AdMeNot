import { describe, expect, test } from 'vitest';
import { formatEta } from './eta';
import { t } from './i18n/index.svelte';

describe('formatEta', () => {
  const none = { eta_s: null, eta_kind: null, eta_min_s: null, eta_max_s: null };

  test('brak czasu', () => {
    expect(formatEta(null, 'pl')).toBe(t('eta.unknown'));
    expect(formatEta(none, 'pl')).toBe(t('eta.unknown'));
  });

  test('czas zmierzony i orientacyjny', () => {
    expect(formatEta({ eta_s: 30, eta_kind: 'measured', eta_min_s: 30, eta_max_s: 30 }, 'pl')).toBe(t('eta.under_min'));
    expect(formatEta({ eta_s: 690, eta_kind: 'measured', eta_min_s: 690, eta_max_s: 690 }, 'pl')).toBe(t('eta.min', { n: 12 }));
    expect(formatEta({ eta_s: 600, eta_kind: 'rough', eta_min_s: 360, eta_max_s: 900 }, 'pl')).toBe(t('eta.range', { lo: 6, hi: 15 }));
  });

  test('klucze eta.* istnieją (nie wracają jako klucz)', () => {
    expect(t('eta.min', { n: 12 })).toBe('~12 min');
    expect(t('eta.range', { lo: 6, hi: 15 })).toBe('6–15 min');
  });
});
