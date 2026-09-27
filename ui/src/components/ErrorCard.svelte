<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { ERROR_KEYS, t } from '../lib/i18n/index.svelte';
  import { enter } from '../lib/motion';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  let { fatal = false }: { fatal?: boolean } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const known: readonly string[] = ERROR_KEYS;
  const key = $derived(s.error && known.includes(s.error.key) ? s.error.key : 'internal');
</script>

{#if fatal}
  <div role="alert" class="mx-auto mt-10 flex max-w-[520px] flex-col items-center gap-3 rounded-2xl bg-surface p-6 text-center shadow-card">
    <span class="grid h-12 w-12 place-items-center rounded-full bg-bad-soft text-bad"><Icon name="triangle-alert" size={22} /></span>
    <b class="text-[15px]">{t('error.fatal')}</b>
    <pre class="mono w-full rounded-lg bg-surface-2 p-2.5 text-left text-[11px] whitespace-pre-wrap text-mut">{s.fatal}</pre>
    <Button variant="primary" onclick={() => location.reload()}>{t('error.restart')}</Button>
  </div>
{:else if s.error}
  <div role="alert" in:enter class="flex items-start gap-3 rounded-2xl border border-bad/30 bg-bad-soft px-4 py-3">
    <span class="mt-0.5 text-bad"><Icon name="triangle-alert" size={16} /></span>
    <div class="min-w-0 flex-1">
      <b class="text-ink">{t(`error.${key}`, { serial: s.error.serial ?? '' })}</b>
      {#if s.error.message && key !== 'wrong_device'}
        <div class="mono mt-1 text-[11px] break-words text-mut">{s.error.message}</div>
      {/if}
      {#if s.error.log}<div class="mt-1 text-[11px] text-mut">{t('error.log', { path: s.error.log })}</div>{/if}
    </div>
    {#if key === 'adb_missing'}
      <Button size="sm" onclick={() => { ctl.dismissError(); ctl.openSettings(); }}>{t('connect.open_settings')}</Button>
    {/if}
    <Button size="sm" variant="ghost" onclick={() => ctl.dismissError()}>{t('common.close')}</Button>
  </div>
{/if}
