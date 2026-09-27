<script lang="ts">
  import { slide } from 'svelte/transition';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { groupHistory, type HistoryAppRow, initial, orderCounts } from '../lib/logic';
  import { DUR, ms } from '../lib/motion';
  import type { HistoryOrder } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  type Props = { order: HistoryOrder; names: Map<string, string>; disabled: boolean;
    onrestore: (pkg: string) => void; onrestoreStep: (actionId: number) => void; onundoAll: () => void };
  let { order, names, disabled, onrestore, onrestoreStep, onundoAll }: Props = $props();
  let open = $state<string[]>([]);
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
  class="rounded-2xl {undone ? 'border border-dashed border-line' : 'bg-surface shadow-card'}">
  <div class="flex items-start gap-3 px-4 pt-3 pb-2.5">
    <div class="min-w-0 flex-1">
      <div class="text-[14.5px] {undone ? 'font-semibold text-mut' : 'font-bold'}">{title}</div>
      <div class="text-[11.5px] text-soft">{order.client ? `${order.client} · ` : ''}<span class="mono">{order.number}</span>{order.interrupted ? ` · ${order.status_label}` : ''}</div>
    </div>
    {#if canUndo && !order.interrupted}
      <Button variant="ghost" size="sm" {disabled} onclick={onundoAll}><Icon name="undo-2" />{t('history.undo_all')}</Button>
    {/if}
  </div>
  {#each rows as r (r.package)}
    <div class="group border-t border-[var(--color-surface-2)]">
      <div class="flex items-center gap-2.5 px-4 py-2 transition-colors duration-150 hover:bg-surface-2">
        <span class="grid h-[22px] w-[22px] flex-none place-items-center rounded-md bg-neutral-soft text-[10.5px] font-extrabold text-mut" aria-hidden="true">{initial(nameOf(r.package))}</span>
        <b class="min-w-0 truncate">{nameOf(r.package)}</b>
        <span class="truncate text-mut">{stateText(r)}</span>
        <span class="ml-auto flex flex-none items-center gap-3">
          <button type="button" class="text-[11.5px] font-semibold text-soft hover:text-ink" aria-expanded={open.includes(r.package)}
            onclick={() => toggle(r.package)}>{t('history.steps')}</button>
          {#if r.canRestore}
            <button type="button" {disabled} aria-label="{t('history.restore')} {nameOf(r.package)}" onclick={() => onrestore(r.package)}
              class="text-[11.5px] font-semibold text-accent opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus:opacity-100 disabled:opacity-40">↶ {t('history.restore')}</button>
          {/if}
        </span>
      </div>
      {#if open.includes(r.package)}
        <ul class="pr-4 pb-2 pl-[52px]" transition:slide={{ duration: ms(DUR.enter) }}>
          {#each r.actions as a (a.id)}
            <li class="flex gap-2 py-0.5 text-[11.5px] text-mut">
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
