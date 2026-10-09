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
  // Telefon jak na karcie urządzenia: nazwa, a obok IMEI (zapas: numer seryjny), żeby rozróżnić dwa takie same modele.
  const device = $derived.by(() => {
    const e = s.error;
    const id = e?.imei ? `IMEI ${e.imei}` : e?.serial;
    if (!e?.device) return id ?? '';
    return id && id !== e.device ? `${e.device} (${id})` : e.device;
  });
</script>

{#if fatal}
  <div role="alert" class="mx-auto mt-10 flex max-w-[520px] flex-col items-center gap-3 rounded-2xl card p-6 text-center">
    <span class="grid h-12 w-12 place-items-center rounded-full bg-bad-soft text-bad"><Icon name="triangle-alert" size={22} /></span>
    <b class="text-lg">{t('error.fatal')}</b>
    <pre class="mono w-full rounded-lg bg-surface-2 p-2.5 text-left text-xs whitespace-pre-wrap text-mut">{s.fatal}</pre>
    <div class="flex gap-2">
      {#if s.fatalCrash}<Button onclick={() => ctl.openCrash(s.fatalCrash!)}>{t('crash.send')}</Button>{/if}
      <Button variant="primary" onclick={() => location.reload()}>{t('error.restart')}</Button>
    </div>
  </div>
{:else if s.error}
  <div role="alert" in:enter class="flex items-start gap-3 rounded-2xl border border-bad/30 bg-bad-soft px-4 py-3">
    <span class="mt-0.5 text-bad"><Icon name="triangle-alert" size={16} /></span>
    <div class="min-w-0 flex-1">
      <b class="text-ink">{t(`error.${key}`, { device })}</b>
      {#if s.error.message && key !== 'wrong_device'}
        <div class="mono mt-1 text-xs break-words text-mut">{s.error.message}</div>
      {/if}
      {#if s.error.log}<div class="mt-1 text-xs text-mut">{t('error.log', { path: s.error.log })}</div>{/if}
    </div>
    {#if key === 'adb_missing'}
      <Button size="sm" onclick={() => { ctl.dismissError(); ctl.openSettings(); }}>{t('connect.open_settings')}</Button>
    {/if}
    {#if s.error.crash}
      <Button size="sm" onclick={() => ctl.openCrash(s.error!.crash!)}>{t('crash.send')}</Button>
    {/if}
    <Button size="sm" variant="ghost" onclick={() => ctl.dismissError()}>{t('common.close')}</Button>
  </div>
{/if}
