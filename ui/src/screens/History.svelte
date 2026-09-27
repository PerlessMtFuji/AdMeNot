<script lang="ts">
  import { getContext } from 'svelte';
  import OrderCard from '../components/OrderCard.svelte';
  import StepTimeline from '../components/StepTimeline.svelte';
  import type { Controller } from '../lib/controller';
  import { i18n, t } from '../lib/i18n/index.svelte';
  import { dayKey, groupHistory, modelName } from '../lib/logic';
  import { enter, stagger } from '../lib/motion';
  import type { HistoryOrder } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Card from '../ui/Card.svelte';
  import SidePanel from '../ui/SidePanel.svelte';
  import Spinner from '../ui/Spinner.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const h = $derived(s.history);
  const names = $derived(new Map((s.scan?.apps ?? []).map((a) => [a.package, a.name])));
  const interrupted = $derived(h?.orders.filter((o) => o.interrupted) ?? []);
  let other = $state('');

  function day(iso: string): string {
    const key = dayKey(iso, new Date());
    return key === 'date'
      ? new Date(iso).toLocaleDateString(i18n.lang, { day: 'numeric', month: 'short' })
      : t(`history.${key}`);
  }

  function detail(o: HistoryOrder): string {
    const rows = groupHistory(o.actions);
    const row = rows.find((r) => r.state === 'pending') ?? rows[0];
    return t('history.banner_detail', { name: names.get(row?.package ?? '') ?? row?.package ?? '',
      done: o.actions.filter((a) => a.status === 'done').length, total: o.actions.length });
  }

  function dot(o: HistoryOrder): string {
    if (o.interrupted) return 'border-warn-strong bg-warn-soft';
    if (o.status === 'undone') return 'border-line bg-surface';
    return 'border-accent bg-surface';
  }
</script>

<div class="flex min-h-0 flex-1">
  <main class="flex min-w-0 flex-1 flex-col gap-3 overflow-auto px-7 py-5">
    <h1 class="text-[19px] font-extrabold">{t('history.title')}</h1>

    {#if s.orderRunning}
      <Card>
        <div class="flex items-center gap-2 px-4 py-3 font-semibold"><Spinner />{t('history.undoing')}</div>
        {#if s.undoSteps.length}<StepTimeline steps={s.undoSteps} />{/if}
      </Card>
    {/if}
    {#if s.undoResult}
      {@const r = s.undoResult}
      <Banner tone={r.errors.length ? 'warn' : 'ok'} icon={r.errors.length ? 'triangle-alert' : 'check'}
        title="{r.order}: {r.status_label}">
        {#if r.admin_not_restored}<p>{t('history.admin_note')}</p>{/if}
        {#if r.errors.length}
          <p>{t('history.undo_errors')}</p>
          <ul class="list-disc pl-5">{#each r.errors as e, i (i)}<li>{e}</li>{/each}</ul>
        {/if}
      </Banner>
    {/if}
    {#each interrupted as o (o.id)}
      <Banner tone="warn" icon="triangle-alert"
        title={t('history.banner', { when: `${day(o.created_at).toLowerCase()}, ${o.created_at.slice(11, 16)}` })}>
        {detail(o)}
        {#snippet actions()}
          <Button variant="ghost" size="sm" disabled={s.orderRunning} onclick={() => ctl.undo(o.number)}>{t('history.undo_changes')}</Button>
          <Button variant="primary" size="sm" disabled={s.orderRunning} onclick={() => ctl.resume(o.number)}>{t('history.resume')}</Button>
        {/snippet}
      </Banner>
    {/each}

    {#if !h || !h.serial}
      <p class="text-mut">{t('history.none')}</p>
    {:else if h.orders.length === 0}
      <p class="text-mut">{t('history.empty')}</p>
    {:else}
      <ol class="relative mt-2 pl-[92px] before:absolute before:top-2 before:bottom-0 before:left-[78px] before:w-0.5 before:bg-line">
        {#each h.orders as o, i (o.id)}
          <li class="relative mb-4" in:enter={{ delay: stagger(i) }}>
            <div class="absolute top-2.5 -left-[92px] w-[66px] text-right">
              <b class="block text-[13px]">{day(o.created_at)}</b>
              <span class="text-[11px] text-soft">{o.created_at.slice(11, 16)}</span>
            </div>
            <span class="absolute top-3.5 -left-[19px] h-3 w-3 rounded-full border-2 {dot(o)}" aria-hidden="true"></span>
            <OrderCard order={o} {names} disabled={s.orderRunning}
              onrestore={(pkg) => ctl.undo(o.number, null, pkg)}
              onrestoreStep={(id) => ctl.undo(o.number, id)}
              onundoAll={() => ctl.undo(o.number)} />
          </li>
        {/each}
      </ol>
    {/if}
  </main>

  <SidePanel width={260} label={t('history.phone')}>
    <span class="lbl">{t('history.phone')}</span>
    {#each h?.devices ?? [] as d (d.serial)}
      {@const current = d.serial === h?.serial}
      <button type="button" aria-pressed={current} onclick={() => ctl.refreshHistory(d.serial)}
        class="flex items-center gap-2.5 rounded-xl p-2.5 text-left transition-colors duration-150 {current ? 'bg-accent-soft' : 'hover:bg-surface-2'}">
        <span class="h-9 w-5 flex-none rounded-[5px] {current ? 'bg-[#1f2937]' : 'bg-soft'}" aria-hidden="true"></span>
        <span class="min-w-0 flex-1">
          <b class="block truncate">{d.model ? modelName(d.model) : d.serial}</b>
          <span class="mono block truncate text-[10.5px] text-soft">{d.serial}</span>
        </span>
        {#if s.device?.serial === d.serial}<span class="text-[11px] text-ok">● USB</span>{/if}
      </button>
    {/each}
    <form class="flex gap-2" onsubmit={(e) => { e.preventDefault(); if (other.trim()) void ctl.refreshHistory(other.trim()); }}>
      <input class="mono min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-1.5 text-[11.5px]" bind:value={other}
        placeholder={t('history.serial_placeholder')} aria-label={t('history.other_serial')} />
      <Button type="submit" size="sm" disabled={!other.trim()}>{t('history.show')}</Button>
    </form>
  </SidePanel>
</div>
