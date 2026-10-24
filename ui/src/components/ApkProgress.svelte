<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { formatEta } from '../lib/eta';
  import { i18n, t } from '../lib/i18n/index.svelte';
  import Button from '../ui/Button.svelte';
  import Card from '../ui/Card.svelte';
  import Progress from '../ui/Progress.svelte';
  import ApkEstimate from './ApkEstimate.svelte';

  // Analiza APK w tle: karta z paskiem nad stanem telefonu i listą aplikacji — to ona teraz „się dzieje”.
  // calm: nic jeszcze nie oznaczono — wtedy uspokajające zdanie zamiast przedwczesnego „czysto”.
  let { calm = false }: { calm?: boolean } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const value = $derived(s.apk.total ? s.apk.done / s.apk.total : 0);
  const label = $derived(t('summary.apk_running', { done: s.apk.done, total: s.apk.total }));
  const remaining = $derived(s.apk.eta === null ? null
    : formatEta({ eta_s: s.apk.eta, eta_kind: 'measured', eta_min_s: s.apk.eta, eta_max_s: s.apk.eta }, i18n.lang));
  const canStop = $derived(s.canStopToManual);
</script>

<Card class="px-4 py-3.5">
  <div class="flex items-center gap-3.5">
    <span class="spin flex-none"></span>
    <div class="flex min-w-0 flex-1 flex-col gap-1.5">
      <div class="flex items-baseline gap-2.5">
        <b class="text-ink">{t('results.apk_card')}</b>
        {#if s.apk.total}<span class="text-sm text-mut">{t('results.apk_count', { done: s.apk.done, total: s.apk.total })}</span>{/if}
        {#if remaining}<span class="ml-auto text-sm whitespace-nowrap text-soft">{remaining}</span>{/if}
      </div>
      <Progress {value} {label} />
      <div class="text-sm text-soft">
        {#if calm}<p>{t('results.apk_sub')}</p>{/if}
        <ApkEstimate class="text-xs" />
      </div>
    </div>
    {#if canStop}<Button size="sm" variant="ghost" onclick={() => ctl.stopToManual()}>{t('apk_mode.stop_to_manual')}</Button>{/if}
  </div>
</Card>
