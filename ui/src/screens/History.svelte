<script lang="ts">
  import { getContext } from 'svelte';
  import OrderCard from '../components/OrderCard.svelte';
  import PhoneThumb from '../components/PhoneThumb.svelte';
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
  const icons = $derived(new Map((s.scan?.apps ?? []).map((a) => [a.package, a.icon])));
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
    return 'border-accent bg-surface text-accent glow-dot';
  }
</script>

<div class="flex min-h-0 min-w-0 flex-1">
  <main class="flex min-w-0 flex-1 flex-col gap-3 scroll-fade overflow-auto px-7 py-7">
    <h1 class="text-2xl font-extrabold">{t('history.title')}</h1>

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
      <ol class="relative mt-2 pl-[104px] before:absolute before:top-2 before:bottom-0 before:left-[88px] before:w-0.5 before:rounded-full before:bg-[linear-gradient(var(--color-accent),var(--color-line)_40%)] before:opacity-60">
        {#each h.orders as o, i (o.id)}
          <li class="relative mb-4" in:enter={{ delay: stagger(i) }}>
            <div class="absolute top-3 -left-[104px] w-[74px] text-right">
              <b class="block text-md">{day(o.created_at)}</b>
              <span class="text-xs text-soft">{o.created_at.slice(11, 16)}</span>
            </div>
            <span class="absolute top-4 -left-[21px] h-3.5 w-3.5 rounded-full border-2 {dot(o)}" aria-hidden="true"></span>
            <OrderCard order={o} {names} {icons} disabled={s.orderRunning}
              onrestore={(pkg) => ctl.undo(o.number, null, pkg)}
              onrestoreStep={(id) => ctl.undo(o.number, id)}
              onundoAll={() => ctl.undo(o.number)} />
          </li>
        {/each}
      </ol>
    {/if}
  </main>

  <SidePanel width={290} label={t('history.phone')}>
    <span class="lbl">{t('history.phone')}</span>
    {#each h?.devices ?? [] as d (d.serial)}
      {@const current = d.serial === h?.serial}
      <button type="button" aria-pressed={current} onclick={() => ctl.refreshHistory(d.serial)}
        class="flex items-center gap-3 rounded-xl p-3 text-left transition duration-150 {current ? 'rail-now' : 'hover:bg-neutral-soft'}">
        <PhoneThumb compact image={d.image} name={modelName(d.name)} />
        <span class="min-w-0 flex-1">
          <b class="line-clamp-2 break-words leading-snug">{modelName(d.name)}</b>
          {#if d.model && d.model !== d.name}<span class="block truncate text-xs text-mut">{modelName(d.model)}</span>{/if}
          <span class="mono block truncate text-2xs text-soft">{d.serial}</span>
        </span>
        {#if s.device?.serial === d.serial}<span class="text-xs text-ok">● USB</span>{/if}
      </button>
    {/each}
    <form class="flex gap-2" onsubmit={(e) => { e.preventDefault(); if (other.trim()) void ctl.refreshHistory(other.trim()); }}>
      <input class="field mono min-w-0 flex-1 rounded-[10px] px-2.5 py-1.5 text-sm" bind:value={other}
        placeholder={t('history.serial_placeholder')} aria-label={t('history.other_serial')} />
      <Button type="submit" size="sm" disabled={!other.trim()}>{t('history.show')}</Button>
    </form>
  </SidePanel>
</div>
