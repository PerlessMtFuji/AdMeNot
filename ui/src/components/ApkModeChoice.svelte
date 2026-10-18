<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { formatEta } from '../lib/eta';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { formatSize } from '../lib/logic';
  import type { ApkModeQuestion } from '../lib/types';

  // Wybór po szybkim skanie (spec trybu ręcznego §3.1): pełna analiza z szacunkiem albo tryb ręczny.
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const q = $derived(s.apkQuestion?.kind === 'mode' ? (s.apkQuestion as ApkModeQuestion) : null);
  let remember = $state(false);
  const apps = $derived(q ? tp('panel.apps', q.apps) : '');
  const summary = $derived(!q || q.to_fetch_bytes === undefined ? apps
    : q.cached ? t('apk_mode.summary_cached', { apps, size: formatSize(q.to_fetch_bytes, i18n.lang), cached: q.cached })
    : t('apk_mode.summary', { apps, size: formatSize(q.to_fetch_bytes, i18n.lang) }));
  const eta = $derived(q ? formatEta(q, i18n.lang) : '');
  const CHOICE = 'rounded-2xl card px-5 py-4 text-left transition duration-150 hover:ring-2 hover:ring-accent/40 enabled:active:translate-y-px';
</script>

{#if q}
  <div class="grid gap-4 py-6">
    <p class="text-center text-mut">{summary}</p>
    <div class="grid grid-cols-2 gap-4 max-[900px]:grid-cols-1">
      <button type="button" class={CHOICE} onclick={() => ctl.chooseApkMode('full', remember)}>
        <span class="flex items-baseline justify-between gap-3">
          <b class="text-md">{t('apk_mode.full')}</b>
          <span class="mono text-sm">{eta}{#if q.eta_kind === 'rough' && q.eta_s !== null} <span class="text-soft">· {t('eta.rough')}</span>{/if}</span>
        </span>
        <span class="mt-1 block text-sm text-mut">{t('apk_mode.full_sub')}</span>
      </button>
      <button type="button" class={CHOICE} onclick={() => ctl.chooseApkMode('manual', remember)}>
        <span class="flex items-baseline justify-between gap-3">
          <b class="text-md">{t('apk_mode.manual')}</b>
          <span class="mono text-sm">{t('eta.now')}</span>
        </span>
        <span class="mt-1 block text-sm text-mut">{t('apk_mode.manual_sub')}</span>
      </button>
    </div>
    <label class="flex items-center justify-center gap-2 text-sm text-mut">
      <input type="checkbox" class="accent-[var(--color-accent)]" bind:checked={remember} />{t('apk_mode.remember')}
    </label>
  </div>
{/if}
