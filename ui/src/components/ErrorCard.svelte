<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { ERROR_KEYS, t } from '../lib/i18n/index.svelte';

  let props: { fatal?: boolean } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const known: readonly string[] = ERROR_KEYS;
  const key = $derived(s.error && known.includes(s.error.key) ? s.error.key : 'internal');
</script>

{#if props.fatal}
  <div class="card hard" role="alert">
    <b>{t('error.fatal')}</b>
    <p class="evidence mt-2">{s.fatal}</p>
    <button class="btn btn-pri mt-3" onclick={() => location.reload()}>{t('error.restart')}</button>
  </div>
{:else if s.error}
  <div class="card flex items-start gap-3 border-[var(--bad-line)] bg-[var(--bad-bg)]" role="alert">
    <div class="min-w-0 flex-1">
      <b>{t(`error.${key}`, { serial: s.error.serial ?? '' })}</b>
      {#if s.error.message && key !== 'wrong_device'}
        <div class="mono mt-1 text-[11px] break-words text-mut">{s.error.message}</div>
      {/if}
      {#if s.error.log}
        <div class="mt-1 text-[11px]">{t('error.log', { path: s.error.log })}</div>
      {/if}
    </div>
    {#if key === 'adb_missing'}
      <button class="btn" onclick={() => { ctl.dismissError(); ctl.openSettings(); }}>{t('connect.open_settings')}</button>
    {/if}
    <button class="btn" onclick={() => ctl.dismissError()}>{t('common.close')}</button>
  </div>
{/if}
