<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { formatSize } from '../lib/logic';
  import { enter, stagger } from '../lib/motion';
  import type { CopyView } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Dialog from '../ui/Dialog.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';

  // Kopie danych starych telefonów (przenoszenie): usuwane po 7 dniach, „Przedłuż” dodaje kolejne 7.
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  let confirming = $state<CopyView | null>(null);

  // Wgrać można skończoną kopię, na telefon wybrany na ekranie Połącz i gdy nic innego nie trwa.
  const phoneReady = $derived(!!s.serial && s.devices.some((d) => d.serial === s.serial && d.state === 'device') && s.job === null);
  const finished = (c: CopyView) => c.status === 'complete' || c.status === 'incomplete';
  // „wgrano na”: nic już nie zostało do wgrania; „przerwane”: most da się wznowić (flaga `resumable`).
  const serials = (c: CopyView, done: boolean) => (c.restores ?? []).filter((r) => r.resumable !== done)
    .map((r) => r.serial).join(', ');

  const title = (c: CopyView) => `${c.manufacturer} ${c.model}`.trim();
  const date = (iso: string) => new Date(iso).toLocaleString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB',
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
</script>

{#if s.transfer.copies.length}
  <section id="transfer-copies" aria-label={t('transfer.copies_title')} class="flex scroll-mt-4 flex-col gap-2">
    <span class="lbl">{t('transfer.copies_title')}</span>
    {#each s.transfer.copies as c, i (c.id)}
      <article aria-label={title(c)} class="flex items-center gap-3 rounded-2xl card px-5 py-3" in:enter={{ delay: stagger(i) }}>
        <div class="min-w-0 flex-1">
          <div class="flex min-w-0 items-center gap-2">
            <b class="truncate">{title(c)}</b>
            {#if c.status !== 'complete'}<Pill tone="warn">{t(`transfer.status.${c.status}`)}</Pill>{/if}
          </div>
          <div class="text-sm text-soft">
            {[c.client, date(c.created), formatSize(c.bytes, i18n.lang)].filter(Boolean).join(' · ')}
            · <span class={c.days_left <= 1 ? 'font-semibold text-warn' : ''}>{tp('transfer.days_left', c.days_left)}</span>
          </div>
          {#if serials(c, true)}<div class="text-sm text-soft">{t('transfer.restore.uploaded_to', { list: serials(c, true) })}</div>{/if}
          {#if serials(c, false)}<div class="text-sm text-warn">{t('transfer.restore.interrupted_on', { list: serials(c, false) })}</div>{/if}
        </div>
        {#if finished(c)}
          <Button variant="secondary" size="sm" disabled={!phoneReady} onclick={() => ctl.planRestore(c.id)}>
            <Icon name="smartphone" size={14} />{t('transfer.restore.to_phone')}
          </Button>
        {/if}
        <Button variant="ghost" size="sm" onclick={() => ctl.extendTransfer(c.id)}><Icon name="clock" size={14} />{t('transfer.extend')}</Button>
        <Button variant="ghost" size="sm" onclick={() => (confirming = c)}><Icon name="trash-2" size={14} />{t('transfer.delete')}</Button>
      </article>
    {/each}
  </section>
{/if}

{#if confirming}
  {@const c = confirming}
  <Dialog title={t('transfer.delete_title', { name: [title(c), c.client].filter(Boolean).join(', ') })} oncancel={() => (confirming = null)}>
    {t('transfer.delete_text')}
    {#snippet actions()}
      <Button onclick={() => (confirming = null)}>{t('common.cancel')}</Button>
      <Button variant="danger" onclick={() => { confirming = null; void ctl.deleteTransfer(c.id); }}>{t('transfer.delete_confirm')}</Button>
    {/snippet}
  </Dialog>
{/if}
