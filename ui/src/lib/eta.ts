import { t } from './i18n/index.svelte';
import type { Lang, EtaView } from './types';

export function formatEta(e: EtaView | null, _lang: Lang): string {
  if (!e || e.eta_s === null) return t('eta.unknown');
  const min = (s: number) => Math.max(1, Math.round(s / 60));
  if (e.eta_kind === 'rough' && e.eta_min_s !== null && e.eta_max_s !== null && e.eta_max_s >= 60) {
    return t('eta.range', { lo: min(e.eta_min_s), hi: min(e.eta_max_s) });
  }
  return e.eta_s < 60 ? t('eta.under_min') : t('eta.min', { n: min(e.eta_s) });
}
