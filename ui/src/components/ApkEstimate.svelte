<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { formatGb, formatSize } from '../lib/logic';

  // Ile analiza APK pobierze z telefonu i czy zmieści się na dysku (zdarzenie apk:estimate).
  let { class: cls = '' }: { class?: string } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const gb = (b: number) => formatGb(b, i18n.lang);
  const size = (b: number) => formatSize(b, i18n.lang);
  const e = $derived(s.apkEstimate);
</script>

{#if s.apk.running && e}
  <p class="text-mut {cls}">
    {#if e.cached && e.cached === e.apps}{t('apk_cache.all_cached', { count: e.apps })}
    {:else if e.cached}{t('apk_cache.estimate_part',
      { size: size(e.to_fetch_bytes), fetch: e.apps - e.cached, count: e.apps })}
    {:else}{tp('apk_cache.estimate', e.apps, { size: size(e.to_fetch_bytes) })}{/if}{#if e.unknown} {t('apk_cache.unknown', { count: e.unknown })}{/if}.
    {#if e.to_fetch_bytes > e.effective_bytes}{t('apk_cache.over', { gb: gb(e.effective_bytes) })}{/if}
  </p>
{/if}
