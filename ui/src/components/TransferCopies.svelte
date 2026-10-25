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

  const title = (c: CopyView) => `${c.manufacturer} ${c.model}`.trim();
  const date = (iso: string) => new Date(iso).toLocaleString(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB',
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
</script>

{#if s.transfer.copies.length}
  <section aria-label={t('transfer.copies_title')} class="flex flex-col gap-2">
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
        </div>
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
