<script lang="ts">
  import { getContext } from 'svelte';
  import { slide } from 'svelte/transition';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { groupHistory, historyApp, type HistoryAppRow, initial, orderCounts } from '../lib/logic';
  import { DUR, ms } from '../lib/motion';
  import type { AppView, HistoryOrder } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Dialog from '../ui/Dialog.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import AppIcon from './AppIcon.svelte';
  import { builtInIcon } from './BrowserIcon.svelte';
  import ReportButton from './ReportButton.svelte';
  import ScreenshotStrip from './ScreenshotStrip.svelte';

  // `openDisabled`: otwarcie strony zajmuje telefon, więc czeka na koniec każdego zadania, nie tylko zlecenia.
  type Props = { order: HistoryOrder; scanned?: AppView[]; disabled: boolean; openDisabled: boolean;
    onrestore: (pkg: string) => void; onrestoreStep: (actionId: number) => void; onundoAll: () => void;
    onopenSite: (actionId: number) => void; ondelete: () => void };
  let { order, scanned = [], disabled, openDisabled, onrestore, onrestoreStep, onundoAll, onopenSite, ondelete }: Props = $props();
  let confirming = $state(false);
  // Folder PDF z ustawień to archiwum serwisu: usunięcie zlecenia go nie sprząta (report/files.py).
  const ctl = getContext<Controller | undefined>('ctl');
  const pdfDir = $derived(ctl?.state.settings.report_pdf_dir ?? null);
  let open = $state<string[]>([]);
  let shotsOpen = $state(false);
  const rows = $derived(groupHistory(order.actions));
  const undone = $derived(order.status === 'undone');
  // Krok z `manual_undo` (kanał nie do przywrócenia) zostaje „done” po cofnięciu: sam nie daje nic do cofnięcia.
  const canUndo = $derived(order.actions.some((a) => (a.status === 'done' && !a.manual_undo) || a.status === 'pending'));
  const nameOf = (pkg: string) => historyApp(order, pkg, scanned).name;
  const title = $derived.by(() => {
    if (order.interrupted) return t('history.interrupted_title', { names: rows.map((r) => nameOf(r.package)).join(', ') });
    const text = orderCounts(rows).map(([level, n]) => tp(`history.did.${level}`, n)).join(` ${t('history.and')} `);
    return text.charAt(0).toUpperCase() + text.slice(1) + (undone ? t('history.undone_suffix') : '');
  });

  function stateText(r: HistoryAppRow): string {
    if (r.state === 'restored') return t('history.restored');
    if (r.state === 'pending') return t('history.pending');
    if (r.state === 'failed') return t('history.failed');
    return t(`history.level_done.${r.level}`) + (r.backup ? ` · ${t('history.backup')}` : '');
  }

  function toggle(pkg: string) {
    open = open.includes(pkg) ? open.filter((p) => p !== pkg) : [...open, pkg];
  }
</script>

<article aria-label={order.number}
  class="rounded-2xl {undone ? 'border border-dashed border-line' : 'card'}">
  <div class="flex items-start gap-3 px-5 pt-4 pb-3">
    <div class="min-w-0 flex-1">
      <div class="text-lg {undone ? 'font-semibold text-mut' : 'font-bold'}">{title}</div>
      <div class="text-sm text-soft">{order.client ? `${order.client} · ` : ''}<span class="mono">{order.number}</span>{order.interrupted ? ` · ${order.status_label}` : ''}{#if order.manual}{' '}<Pill tone="neutral">{t('history.manual')}</Pill>{/if}</div>
      {#if order.screenshots}
        <button type="button" class="mt-1 text-sm font-semibold text-soft hover:text-ink" aria-expanded={shotsOpen}
          onclick={() => (shotsOpen = !shotsOpen)}>{t('shot.history', { count: order.screenshots })}</button>
      {/if}
    </div>
    <div class="flex flex-none flex-col items-end gap-1">
      <ReportButton order={order.number} variant="ghost" size="sm" />
      {#if canUndo && !order.interrupted}
        <Button variant="ghost" size="sm" {disabled} onclick={onundoAll}><Icon name="undo-2" />{t('history.undo_all')}</Button>
      {/if}
      <Button variant="ghost" size="sm" {disabled} onclick={() => (confirming = true)}><Icon name="trash-2" />{t('history.delete')}</Button>
    </div>
  </div>
  {#if shotsOpen}
    <div class="border-t border-line/70 px-5 py-3" transition:slide={{ duration: ms(DUR.enter) }}>
      <ScreenshotStrip order={order.number} />
    </div>
  {/if}
  {#each rows as r (r.package)}
    {@const app = historyApp(order, r.package, scanned)}
    <div class="group border-t border-line/70">
      <div class="flex items-center gap-3 px-5 py-2.5 transition-colors duration-150 hover:bg-surface-2">
        <!-- przeglądarek zwykle nie analizujemy: bez zapisanej ikony wbudowane logo -->
        <AppIcon icon={app.icon ?? builtInIcon(r.package)} class="h-8 w-8">
          <span class="grid h-8 w-8 flex-none place-items-center rounded-lg bg-neutral-soft text-xs font-extrabold text-mut shadow-[var(--shadow-well)]" aria-hidden="true">{initial(app.name)}</span>
        </AppIcon>
        <span class="flex min-w-0 flex-col">
          <span class="flex min-w-0 items-baseline gap-3">
            <b class="min-w-0 truncate">{app.name}</b>
            <span class="truncate text-mut">{stateText(r)}</span>
          </span>
          {#if app.name !== r.package}<span class="mono truncate text-2xs text-soft">{r.package}</span>{/if}
        </span>
        <span class="ml-auto flex flex-none items-center gap-3">
          <button type="button" class="text-sm font-semibold text-soft hover:text-ink" aria-expanded={open.includes(r.package)}
            onclick={() => toggle(r.package)}>{t('history.steps')}</button>
          {#if r.canRestore}
            <button type="button" {disabled} aria-label="{t('history.restore')} {nameOf(r.package)}" onclick={() => onrestore(r.package)}
              class="text-sm font-semibold text-accent opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus:opacity-100 disabled:opacity-40">↶ {t('history.restore')}</button>
          {/if}
        </span>
      </div>
      {#if open.includes(r.package)}
        <ul class="pr-5 pb-2.5 pl-[64px]" transition:slide={{ duration: ms(DUR.enter) }}>
          {#each r.actions as a (a.id)}
            <li class="flex gap-2 py-0.5 text-sm text-mut">
              <span class="min-w-0 flex-1">{a.step_label} — {a.status_label}{a.error ? `: ${a.error}` : ''}</span>
              {#if a.status === 'done' && a.manual_undo}
                <span class="max-w-[55%] text-right text-soft">{a.manual_undo}</span>
              {:else if a.status === 'done' && a.kind === 'channel'}
                <!-- włączenie na telefonie: cofanie tego jednego kroku otwiera ekran kanału -->
                <button type="button" class="font-semibold text-accent" {disabled} onclick={() => onrestoreStep(a.id)}>📱 {t('history.enable_on_phone')}</button>
              {:else if a.status === 'undone' && a.kind === 'channel' && a.site_url}
                <button type="button" class="font-semibold text-accent" disabled={openDisabled} onclick={() => onopenSite(a.id)}>🌐 {t('history.open_site')}</button>
              {:else if a.status === 'done'}
                <button type="button" class="font-semibold text-accent" {disabled} onclick={() => onrestoreStep(a.id)}>↶ {t('history.restore')}</button>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/each}
</article>
{#if confirming}
  <Dialog title={t('history.delete_title', { number: order.number })} oncancel={() => (confirming = false)}>
    {t('history.delete_text')}
    {#if pdfDir}<p class="mt-2">{t('history.delete_pdf_kept', { dir: pdfDir })}</p>{/if}
    {#snippet actions()}
      <Button onclick={() => (confirming = false)}>{t('common.cancel')}</Button>
      <Button variant="danger" onclick={() => { confirming = false; ondelete(); }}>{t('history.delete_confirm')}</Button>
    {/snippet}
  </Dialog>
{/if}
