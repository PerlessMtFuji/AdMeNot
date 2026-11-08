<script lang="ts">
  import { getContext, tick } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t, tp } from '../lib/i18n/index.svelte';
  import { transferRows, type TransferRow } from '../lib/logic';
  import { enter, stagger } from '../lib/motion';
  import Button from '../ui/Button.svelte';
  import Dialog from '../ui/Dialog.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import Spinner from '../ui/Spinner.svelte';
  import CopyNote from './CopyNote.svelte';
  import ReportButton from './ReportButton.svelte';

  // Historia → Przeniesienia: jeden wiersz = jedno zlecenie ZS (albo kopia, która zlecenia jeszcze nie ma).
  // Na wierzchu jedna akcja pasująca do stanu, reszta w menu ⋯; liczby kategorii po rozwinięciu wiersza.
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const rows = $derived(transferRows(s.transfer.orders, s.transfer.copies));
  let expanded = $state<Record<string, boolean>>({});
  let menuFor = $state<string | null>(null);
  let confirming = $state<TransferRow | null>(null);
  let noteRefs = $state<Record<string, CopyNote | undefined>>({});

  const lang = $derived(i18n.lang === 'pl' ? 'pl-PL' : 'en-GB');
  const date = (iso: string) => new Date(iso).toLocaleString(lang, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  const dayMonth = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
  const num = (n: number) => new Intl.NumberFormat(i18n.lang === 'pl' ? 'pl-PL' : 'en-US').format(n);

  const online = $derived(s.devices.filter((d) => d.state === 'device'));
  const selected = $derived(s.serial ? online.find((d) => d.serial === s.serial) ?? null : null);
  const phoneReady = $derived(selected !== null && s.job === null);
  // „Wgraj na podłączony”: tylko inny telefon niż ten, z którego jest kopia (po IMEI; bez IMEI nie ma jak porównać).
  const canUpload = (r: TransferRow) => !!r.disk && (r.state === 'copy_ready' || r.state === 'incomplete') && phoneReady
    && !(selected?.imei && selected.imei === r.source.imei);
  const targetConnected = (r: TransferRow) => !!r.target?.imei && online.some((d) => d.imei === r.target?.imei);
  const restored = (r: TransferRow) => r.state === 'restored' || r.state === 'restored_notes';
  const hasCopy = (r: TransferRow) => !!r.disk && !r.copy?.deleted_at;
  const topReport = (r: TransferRow) => !!r.number && restored(r);
  const showWhatsapp = (r: TransferRow) => !!r.number && restored(r) && ((r.counts.files_whatsapp ?? 0) > 0 || r.whatsappRestored);
  const showReinstall = (r: TransferRow) => !!r.number && r.appsBlocked && targetConnected(r);
  const menuReport = (r: TransferRow) => !!r.number && !topReport(r);
  const hasMenu = (r: TransferRow) => hasCopy(r) || showWhatsapp(r) || showReinstall(r) || menuReport(r);

  const phone = (p: { name: string | null } | null, fallback: string) => p?.name || fallback;
  const label = (r: TransferRow) => `${phone(r.source, t('transfer.hist.old_phone'))} → ${phone(r.target, t('transfer.hist.new_phone'))}${r.number ? `, ${r.number}` : ''}`;
  const pill = (r: TransferRow): { tone: 'ok' | 'warn' | 'bad' | 'neutral'; text: string } => {
    switch (r.state) {
      case 'restored': return { tone: 'ok', text: t('transfer.hist.state.restored') };
      case 'restored_notes': return { tone: 'warn', text: tp('transfer.hist.notes', r.notes) };
      case 'failed': return { tone: 'bad', text: t('transfer.hist.state.failed') };
      case 'interrupted': return { tone: 'warn', text: t('transfer.hist.state.interrupted') };
      case 'incomplete': return { tone: 'warn', text: t('transfer.hist.state.incomplete') };
      default: return { tone: 'neutral', text: t(`transfer.hist.state.${r.state}`) };
    }
  };
  const busy = (r: TransferRow) => !!r.number && s.transfer.appsBusy === r.number;
  const appsNote = (r: TransferRow) => {
    const key = r.number ? s.transfer.appsNotes[r.number] : undefined;
    return key ? t(`transfer.hist.apps_note.${['transfer_no_phone', 'transfer_copy_missing'].includes(key) ? key : 'other'}`) : null;
  };

  // Zawartość z `counts`: tylko niezerowe; kopie sprzed liczników według grup mają tylko łączne `files`.
  const CONTENTS = ['contacts', 'sms', 'mms', 'calls', 'files_photos', 'files_videos', 'files_downloads',
    'files_whatsapp', 'files_others', 'apps'] as const;
  function contents(counts: Record<string, number>): { key: string; n: number }[] {
    const perKind = CONTENTS.some((k) => k.startsWith('files_') && counts[k]);
    const first = CONTENTS.find((x) => x.startsWith('files_'));
    const keys = CONTENTS.flatMap((k): string[] => (!k.startsWith('files_') || perKind ? [k] : k === first ? ['files'] : []));
    return keys.filter((k) => (counts[k] ?? 0) > 0).map((k) => ({ key: k, n: counts[k] }));
  }

  function toggle(r: TransferRow): void {
    expanded = { ...expanded, [r.key]: !expanded[r.key] };
  }

  async function editNote(r: TransferRow): Promise<void> {
    menuFor = null;
    expanded = { ...expanded, [r.key]: true };
    await tick();
    await noteRefs[r.key]?.edit();
  }

  function pick(action: () => unknown): void {
    menuFor = null;
    void action();
  }
</script>

<!-- Klik poza menu zamyka je; własny przycisk ⋯ i menu mają `data-menu`. -->
<svelte:window onkeydown={(e) => { if (menuFor && e.key === 'Escape') menuFor = null; }}
  onclick={(e) => { if (menuFor && !e.composedPath().some((n) => n instanceof HTMLElement && n.dataset.menu === menuFor)) menuFor = null; }} />

{#if rows.length}
  <section id="transfer-orders" aria-label={t('transfer.hist.title')} class="flex scroll-mt-4 flex-col gap-3">
    <p class="text-mut">{t('transfer.hist.sub')}</p>
    <div class="rounded-2xl card">
      {#each rows as r, i (r.key)}
        {@const p = pill(r)}
        {@const open = !!expanded[r.key]}
        {@const note = appsNote(r)}
        <article aria-label={label(r)} class="border-line {i > 0 ? 'border-t' : ''}" in:enter={{ delay: stagger(i) }}>
          <div class="flex items-center gap-3 px-4 py-3">
            <button type="button" aria-expanded={open} aria-label={open ? t('transfer.hist.hide') : t('transfer.hist.details')}
              class="grid h-8 w-8 flex-none place-items-center rounded-lg text-soft transition duration-150 hover:bg-neutral-soft hover:text-ink"
              onclick={() => toggle(r)}>
              <span class="transition-transform duration-150 {open ? 'rotate-90' : ''}"><Icon name="chevron-right" size={16} /></span>
            </button>
            <div class="min-w-0 flex-1">
              <div class="flex min-w-0 flex-wrap items-baseline gap-x-2">
                <span class="min-w-0 truncate">
                  <b>{phone(r.source, t('transfer.hist.old_phone'))}</b>
                  <span class="px-0.5 text-soft" aria-hidden="true">→</span>
                  {#if r.target}<b>{phone(r.target, t('transfer.hist.new_phone'))}</b>{:else}<span class="text-mut">{t('transfer.hist.new_phone')}</span>{/if}
                </span>
                {#if r.number}<span class="mono text-xs text-soft">{r.number}</span>{/if}
              </div>
              <div class="text-sm text-mut">
                {#if r.state === 'interrupted'}
                  {[r.client, date(r.at)].filter(Boolean).join(' · ')} · <span class="text-warn">{t('transfer.hist.interrupted')}</span>
                {:else}
                  {[r.client, date(r.at)].filter(Boolean).join(' · ')}
                  {#if r.copy?.deleted_at}
                    · {t('transfer.hist.deleted', { date: dayMonth(r.copy.deleted_at) })}
                  {:else if r.copy}
                    · <span class={r.copy.days_left <= 1 ? 'font-semibold text-warn' : ''}>{tp('transfer.hist.left', r.copy.days_left)}</span>
                  {/if}
                {/if}
                {#if r.appsBlocked && !busy(r)}<span class="text-warn"> · {t('transfer.hist.apps_waiting')}</span>{/if}
                {#if busy(r)}<span class="inline-flex items-center gap-1.5 text-accent"> · <Spinner />{t('transfer.hist.installing')}</span>{/if}
                {#if note}<span class="text-warn"> · {note}</span>{/if}
              </div>
            </div>
            <div class="flex flex-none justify-end min-[900px]:w-[136px]"><Pill tone={p.tone}>{p.text}</Pill></div>
            <div class="flex flex-none justify-end min-[900px]:w-[190px]">
              {#if topReport(r)}
                <ReportButton order={r.number!} variant="secondary" size="sm" label={t('transfer.hist.report')} />
              {:else if canUpload(r)}
                <Button variant="secondary" size="sm" onclick={() => ctl.planRestore(r.disk!.id)}>
                  <Icon name="smartphone" size={14} />{t('transfer.hist.to_phone')}
                </Button>
              {/if}
            </div>
            <div class="relative h-9 w-9 flex-none" data-menu={r.key}>
            {#if hasMenu(r)}
                <Button variant="ghost" size="icon" label={t('transfer.hist.more', { name: label(r) })}
                  onclick={() => (menuFor = menuFor === r.key ? null : r.key)}>
                  <Icon name="ellipsis" size={18} />
                </Button>
                {#if menuFor === r.key}
                  <div role="menu" aria-label={t('transfer.hist.more', { name: label(r) })} data-menu={r.key}
                    class="absolute top-full right-0 z-20 mt-1.5 flex min-w-[230px] flex-col gap-0.5 rounded-2xl card p-1.5 shadow-xl">
                    {#if hasCopy(r)}
                      <button type="button" role="menuitem" class="menu-item" onclick={() => pick(() => ctl.extendTransfer(r.disk!.id))}>
                        <Icon name="clock" size={15} />{t('transfer.hist.menu.extend')}
                      </button>
                      <button type="button" role="menuitem" class="menu-item" onclick={() => void editNote(r)}>
                        <Icon name="sticky-note" size={15} />{t('transfer.hist.menu.note')}
                      </button>
                    {/if}
                    {#if showWhatsapp(r)}
                      <button type="button" role="menuitemcheckbox" aria-checked={r.whatsappRestored} class="menu-item"
                        onclick={() => pick(() => ctl.setOrderWhatsapp(r.number!, !r.whatsappRestored))}>
                        <span class="grid h-[15px] w-[15px] place-items-center rounded-[4px] border {r.whatsappRestored ? 'border-accent bg-accent text-white' : 'border-line'}">
                          {#if r.whatsappRestored}<Icon name="check" size={11} />{/if}
                        </span>{t('transfer.hist.menu.whatsapp')}
                      </button>
                    {/if}
                    {#if showReinstall(r)}
                      <button type="button" role="menuitem" class="menu-item" disabled={s.job !== null || busy(r)}
                        onclick={() => pick(() => ctl.reinstallFromHistory(r.number!))}>
                        <Icon name="download" size={15} />{t('transfer.hist.menu.reinstall')}
                      </button>
                    {/if}
                    {#if menuReport(r)}
                      <button type="button" role="menuitem" class="menu-item" onclick={() => pick(() => ctl.report(r.number!))}>
                        <Icon name="file-text" size={15} />{t('transfer.hist.menu.report')}
                      </button>
                    {/if}
                    {#if hasCopy(r)}
                      <div class="my-0.5 border-t border-line"></div>
                      <button type="button" role="menuitem" class="menu-item text-bad" onclick={() => pick(() => (confirming = r))}>
                        <Icon name="trash-2" size={15} />{t('transfer.hist.menu.delete')}
                      </button>
                    {/if}
                  </div>
                {/if}
            {/if}
            </div>
          </div>
          {#if open}
            <div class="flex flex-col gap-2 px-4 pb-4 pl-[60px] text-sm">
              <div class="flex flex-wrap gap-x-6 gap-y-1 text-mut">
                <span>{t('transfer.hist.old_label')}: <b class="font-semibold text-ink">{phone(r.source, t('transfer.hist.old_phone'))}</b>
                  {#if r.source.imei}<span class="mono text-xs text-soft"> · {t('transfer.hist.imei', { imei: r.source.imei })}</span>{/if}</span>
                {#if r.target}
                  <span>{t('transfer.hist.new_label')}: <b class="font-semibold text-ink">{phone(r.target, t('transfer.hist.new_phone'))}</b>
                    {#if r.target.imei}<span class="mono text-xs text-soft"> · {t('transfer.hist.imei', { imei: r.target.imei })}</span>{/if}</span>
                {/if}
              </div>
              {#if contents(r.counts).length}
                <div class="flex flex-wrap gap-x-4 gap-y-0.5 text-mut" data-testid="copy-contents">
                  {#each contents(r.counts) as item (item.key)}
                    <span>{t(`transfer.contents.${item.key}`)} <b class="font-semibold text-ink">{num(item.n)}</b></span>
                  {/each}
                </div>
              {:else}
                <div class="text-soft">{t('transfer.hist.empty_counts')}</div>
              {/if}
              {#if r.disk}<CopyNote bind:this={noteRefs[r.key]} copy={r.disk} />{/if}
            </div>
          {/if}
        </article>
      {/each}
    </div>
  </section>
{/if}

{#if confirming}
  {@const c = confirming}
  <Dialog title={t('transfer.delete_title', { name: [phone(c.source, t('transfer.hist.old_phone')), c.client].filter(Boolean).join(', ') })}
    oncancel={() => (confirming = null)}>
    {t('transfer.delete_text')}
    {#snippet actions()}
      <Button onclick={() => (confirming = null)}>{t('common.cancel')}</Button>
      <!-- `c` jest wyliczane z `confirming` przy każdym odczycie: id bierzemy przed zamknięciem okna -->
      <Button variant="danger" onclick={() => { const id = c.disk?.id; confirming = null; if (id) void ctl.deleteTransfer(id); }}>{t('transfer.delete_confirm')}</Button>
    {/snippet}
  </Dialog>
{/if}

<style>
  .menu-item {
    display: flex;
    align-items: center;
    gap: 0.625rem;
    width: 100%;
    border-radius: 10px;
    padding: 0.5rem 0.75rem;
    text-align: left;
    font-size: var(--text-sm);
    font-weight: 600;
    white-space: nowrap;
    transition: background-color 140ms;
  }
  .menu-item:hover:enabled {
    background: var(--color-neutral-soft);
  }
  .menu-item:disabled {
    opacity: 0.5;
  }
</style>
