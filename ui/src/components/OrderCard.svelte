<script lang="ts">
  import { slide } from 'svelte/transition';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { groupHistory, type HistoryAppRow, initial, orderCounts } from '../lib/logic';
  import { DUR, ms } from '../lib/motion';
  import type { HistoryOrder } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import AppIcon from './AppIcon.svelte';
  import ReportButton from './ReportButton.svelte';
  import ScreenshotStrip from './ScreenshotStrip.svelte';

  type Props = { order: HistoryOrder; names: Map<string, string>; icons?: Map<string, string | null>; disabled: boolean;
    onrestore: (pkg: string) => void; onrestoreStep: (actionId: number) => void; onundoAll: () => void };
  let { order, names, icons, disabled, onrestore, onrestoreStep, onundoAll }: Props = $props();
  let open = $state<string[]>([]);
  let shotsOpen = $state(false);
  const rows = $derived(groupHistory(order.actions));
  const undone = $derived(order.status === 'undone');
  const canUndo = $derived(order.actions.some((a) => a.status === 'done' || a.status === 'pending'));
  const nameOf = (pkg: string) => names.get(pkg) ?? pkg;
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
      <div class="text-sm text-soft">{order.client ? `${order.client} · ` : ''}<span class="mono">{order.number}</span>{order.interrupted ? ` · ${order.status_label}` : ''}</div>
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
    </div>
  </div>
  {#if shotsOpen}
    <div class="border-t border-line/70 px-5 py-3" transition:slide={{ duration: ms(DUR.enter) }}>
      <ScreenshotStrip order={order.number} />
    </div>
  {/if}
  {#each rows as r (r.package)}
    <div class="group border-t border-line/70">
      <div class="flex items-center gap-3 px-5 py-2.5 transition-colors duration-150 hover:bg-surface-2">
        <AppIcon icon={icons?.get(r.package)} class="h-7 w-7">
          <span class="grid h-7 w-7 flex-none place-items-center rounded-lg bg-neutral-soft text-xs font-extrabold text-mut shadow-[var(--shadow-well)]" aria-hidden="true">{initial(nameOf(r.package))}</span>
        </AppIcon>
        <b class="min-w-0 truncate">{nameOf(r.package)}</b>
        <span class="truncate text-mut">{stateText(r)}</span>
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
        <ul class="pr-5 pb-2.5 pl-[60px]" transition:slide={{ duration: ms(DUR.enter) }}>
          {#each r.actions as a (a.id)}
            <li class="flex gap-2 py-0.5 text-sm text-mut">
              <span class="min-w-0 flex-1">{a.step_label} — {a.status_label}{a.error ? `: ${a.error}` : ''}</span>
              {#if a.status === 'done'}
                <button type="button" class="font-semibold text-accent" {disabled} onclick={() => onrestoreStep(a.id)}>↶ {t('history.restore')}</button>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/each}
</article>
