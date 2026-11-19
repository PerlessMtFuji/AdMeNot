<script lang="ts">
  import { i18n, t, tp } from '../../lib/i18n/index.svelte';
  import type { FailureView } from '../../lib/types';

  // Lista nieudanych pozycji kopii albo wgrywania: nazwa, folder i powód po ludzku (surowych kodów UI nie dostaje).
  let { failures, limit = 10 }: { failures: FailureView[]; limit?: number } = $props();
  let all = $state(false);
  const shown = $derived(all ? failures : failures.slice(0, limit));
  const num = (n: number) => new Intl.NumberFormat(i18n.lang === 'pl' ? 'pl-PL' : 'en-US').format(n);
  const TEL = ['contacts', 'sms', 'mms', 'calls'];
  const title = (f: FailureView) => (f.kind === 'tel' && TEL.includes(f.name) ? t(`transfer.sum.${f.name}`) : f.name);
</script>

<ul class="flex flex-col gap-1 text-sm">
  {#each shown as f, i (i)}
    <li class="flex min-w-0 flex-wrap items-baseline gap-x-2">
      <b class="min-w-0 break-all text-ink">{title(f)}</b>
      {#if f.kind === 'file' && f.folder}<span class="mono min-w-0 break-all text-xs text-soft">{f.folder}</span>{/if}
      {#if f.kind === 'tel'}<span class="text-mut">{tp('transfer.fail.tel_records', f.count, { count: num(f.count) })}</span>{/if}
      <span class="text-warn">{t(`transfer.fail.reason.${f.reason}`)}</span>
      {#if !f.retryable}<span class="text-soft">· {t('transfer.fail.not_retryable')}</span>{/if}
    </li>
  {/each}
</ul>
{#if !all && failures.length > limit}
  <button type="button" class="mt-1 w-fit text-sm font-semibold text-accent hover:underline" onclick={() => (all = true)}>
    {t('transfer.fail.show_all', { count: num(failures.length) })}
  </button>
{/if}
