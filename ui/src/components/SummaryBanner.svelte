<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';

  const s = getContext<Controller>('ctl').state;
  const counts = $derived(s.scan?.counts);
  const bad = $derived(counts ? counts.malicious + counts.suspicious : 0);
</script>

{#if counts}
  {#if bad > 0}
    <div class="card flex items-start gap-2.5 border-[var(--bad-line)] bg-[#fff7f7]">
      <span class="text-[22px]" aria-hidden="true">⚠️</span>
      <div>
        <b class="text-[13px]">{t('summary.found', { count: bad })}</b>
        <p class="mt-0.5 text-[#475569]">{t('summary.advice')}</p>
      </div>
    </div>
  {:else if counts.review > 0}
    <div class="card"><b>{t('summary.review')}</b></div>
  {:else}
    <div class="card border-[var(--ok-line)] bg-[var(--ok-bg)]"><b class="ok">✓ {t('summary.clean')}</b></div>
  {/if}
  {#if s.scan?.low_behavior_data}
    <div class="card border-[var(--warn-line)] bg-[var(--warn-bg)]"><span class="warn">⚠</span> {t('summary.low_data')}</div>
  {/if}
{/if}
