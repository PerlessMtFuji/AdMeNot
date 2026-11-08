<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { formatEta } from '../lib/eta';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { formatGb, formatSize } from '../lib/logic';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import Progress from '../ui/Progress.svelte';
  import Tooltip from '../ui/Tooltip.svelte';

  // Analiza APK w tle: jedna cienka linia nad zakładkami (spec układu Naprawy §3 p.2) — to ona teraz „się dzieje”.
  // calm: nic jeszcze nie oznaczono — wtedy uspokajające zdanie zamiast przedwczesnego „czysto”.
  // Zdanie i szacunek pobierania nie mieszczą się w linii przy oknie 1200 px, więc idą do dymka przy ikonie.
  let { calm = false }: { calm?: boolean } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const value = $derived(s.apk.total ? s.apk.done / s.apk.total : 0);
  const label = $derived(t('summary.apk_running', { done: s.apk.done, total: s.apk.total }));
  const remaining = $derived(s.apk.eta === null ? null
    : formatEta({ eta_s: s.apk.eta, eta_kind: 'measured', eta_min_s: s.apk.eta, eta_max_s: s.apk.eta }, i18n.lang));
  const canStop = $derived(s.canStopToManual);
  // Szacunek przekracza miejsce na dysku — ikona dymka dostaje ton ostrzegawczy.
  const exceeds = $derived(!!s.apkEstimate && s.apkEstimate.to_fetch_bytes > s.apkEstimate.effective_bytes);
  const over = $derived(exceeds && s.apk.running);
  // Ile analiza pobierze z telefonu i czy zmieści się na dysku (zdarzenie apk:estimate).
  const estimate = $derived.by(() => {
    const e = s.apkEstimate;
    if (!s.apk.running || !e) return '';
    const size = formatSize(e.to_fetch_bytes, i18n.lang);
    const base = e.cached && e.cached === e.apps ? t('apk_cache.all_cached', { count: e.apps })
      : e.cached ? t('apk_cache.estimate_part', { size, fetch: e.apps - e.cached, count: e.apps })
      : tp('apk_cache.estimate', e.apps, { size });
    const unknown = e.unknown ? ` ${t('apk_cache.unknown', { count: e.unknown })}` : '';
    const overText = exceeds ? ` ${t('apk_cache.over', { gb: formatGb(e.effective_bytes, i18n.lang) })}` : '';
    return `${base}${unknown}.${overText}`;
  });
  // Szacunek czasu w linii znika przy wąskim oknie (max-[1200px]) — wtedy jest w dymku.
  const hint = $derived([calm ? t('results.apk_sub') : '', estimate, remaining ?? ''].filter(Boolean).join(' '));
</script>

<div class="flex min-w-0 items-center gap-3 text-sm whitespace-nowrap text-mut">
  <span class="spin flex-none"></span>
  <b class="flex-none text-ink">{t('results.apk_card')}</b>
  {#if s.apk.total}<span class="flex-none tabular-nums">{t('results.apk_count', { done: s.apk.done, total: s.apk.total })}</span>{/if}
  {#if remaining}<span class="flex-none text-soft max-[1200px]:hidden" aria-hidden="true">·</span><span class="flex-none text-soft max-[1200px]:hidden">{remaining}</span>{/if}
  {#if hint}
    <Tooltip text={hint} class="flex-none whitespace-normal">
      <button type="button" aria-label={hint} class="grid rounded-full p-0 text-soft outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]">
        <Icon name="info" size={15} class={over ? 'text-warn' : ''} />
      </button>
    </Tooltip>
  {/if}
  <div class="min-w-0 flex-1 basis-12"><Progress {value} {label} /></div>
  {#if canStop}<Button size="sm" variant="ghost" class="flex-none" onclick={() => ctl.stopToManual()}>{t('apk_mode.stop_to_manual')}</Button>{/if}
</div>
