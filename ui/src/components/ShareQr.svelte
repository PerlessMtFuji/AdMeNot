<script lang="ts">
  import { getContext } from 'svelte';
  import { encode } from 'uqr';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Dialog from '../ui/Dialog.svelte';
  import Icon from '../ui/Icon.svelte';
  import Spinner from '../ui/Spinner.svelte';

  let { disabled = false }: { disabled?: boolean } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const share = $derived(s.share);
  // Ciemne moduły na białym tle także w trybie ciemnym: aparaty gorzej czytają odwrócone kody.
  // Tryb lokalny: niska korekcja błędów (L) daje rzadszy kod przy tej samej treści; ekran się nie brudzi.
  const qr = $derived(share?.url ? encode(share.url, { ecc: share.mode === 'local' ? 'L' : 'M', border: 2 }) : null);
  // Całkowita liczba pikseli na moduł i co najmniej 3 px, żeby aparat telefonu odczytał kod
  // (przegląd 2026-10-11). Gęsty kod lokalny nie mieści się w panelu: wtedy jest „Powiększ kod”.
  const MIN_PX = 3;
  const INLINE_PX = 180;
  const ZOOM_PX = 440;
  const inline = $derived(qr ? Math.max(1, Math.floor(INLINE_PX / qr.size)) : 0);
  const zoom = $derived(qr ? Math.max(MIN_PX, Math.floor(ZOOM_PX / qr.size)) : 0);
  let zoomed = $state(false);
  const path = $derived.by(() => {
    if (!qr) return '';
    let d = '';
    qr.data.forEach((row, y) => row.forEach((on, x) => { if (on) d += `M${x} ${y}h1v1h-1z`; }));
    return d;
  });
  const until = $derived(share?.expires
    ? new Date(share.expires).toLocaleTimeString(s.settings.lang, { hour: '2-digit', minute: '2-digit' })
    : null);
</script>

{#if s.planChanged}
  <Banner tone="warn" icon="triangle-alert" title={t('plan.changed')} />
{/if}
{#if !share}
  <div class="flex flex-col gap-1">
    <Button variant="ghost" {disabled} onclick={() => ctl.sharePlan()}><Icon name="qr-code" />{t('plan.share')}</Button>
    <p class="text-xs text-mut">{t('plan.share_hint')}</p>
  </div>
{:else}
  <div class="well flex flex-none items-center gap-4 p-3.5">
    {#if qr}
      <svg role="img" aria-label={t('plan.share_qr')} viewBox="0 0 {qr.size} {qr.size}" width={qr.size * inline}
        height={qr.size * inline} shape-rendering="crispEdges" class="flex-none rounded-lg bg-white"><path d={path} fill="#000" /></svg>
    {:else if share.status === 'sending'}
      <div class="grid h-[180px] w-[180px] flex-none place-items-center rounded-lg bg-white/60"><Spinner /></div>
    {/if}
    {#if share.code}
      <div class="min-w-0">
        <span class="lbl">{t('plan.share_code')}</span>
        <b class="mono block text-3xl tracking-widest">{share.code}</b>
        {#if until}<span class="text-xs text-mut">{t('plan.share_valid', { time: until })}</span>{/if}
        {#if qr && inline < MIN_PX}
          <Button size="sm" onclick={() => (zoomed = true)}><Icon name="search" />{t('plan.share_zoom')}</Button>
        {/if}
      </div>
    {/if}
  </div>
  {#if zoomed && qr}
    <Dialog title={t('plan.share_qr')} oncancel={() => (zoomed = false)}>
      <svg role="img" aria-label={t('plan.share_qr')} viewBox="0 0 {qr.size} {qr.size}" width={qr.size * zoom}
        height={qr.size * zoom} shape-rendering="crispEdges" class="mx-auto block rounded-lg bg-white"><path d={path} fill="#000" /></svg>
      {#snippet actions()}
        <Button variant="primary" onclick={() => (zoomed = false)}>{t('common.close')}</Button>
      {/snippet}
    </Dialog>
  {/if}
  {#if share.mode === 'local' && share.status === 'ready'}
    <Banner tone="warn" icon="info" title={t('plan.share_local')} />
  {:else if share.upgraded}
    <Banner tone="ok" icon="check" title={t('plan.share_upgraded', { code: share.code ?? '' })} />
  {:else if share.status === 'failed'}
    <Banner tone="bad" icon="triangle-alert"
      title={t(share.reason === 'too_long' ? 'plan.share_too_long' : 'plan.share_error')} />
  {/if}
  {#if share.url}
    <label class="flex items-center gap-2 text-sm">
      <input type="checkbox" bind:checked={s.consent} />{t('plan.consent', { code: share.code ?? '' })}
    </label>
  {/if}
{/if}
