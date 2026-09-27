<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import type { HistoryOrder } from '../lib/types';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const h = $derived(s.history);
  const ICON: Record<string, string> = { done: '✓', failed: '✗', undone: '↺', pending: '○' };
  const names = $derived(new Map((s.scan?.apps ?? []).map((a) => [a.package, a.name])));

  function canUndo(o: HistoryOrder): boolean {
    return o.actions.some((a) => a.status === 'done' || a.status === 'pending');
  }
</script>

<section class="flex flex-col gap-2">
  <div class="flex items-center gap-3">
    <b class="text-[14px]">{t('history.title')}</b>
    {#if h && h.serials.length}
      <label class="ml-auto flex items-center gap-2">
        <span class="lbl">{t('history.phone')}</span>
        <select class="mono rounded border border-line bg-card px-1.5 py-1" aria-label={t('history.phone')}
          value={h.serial ?? ''} onchange={(e) => ctl.refreshHistory(e.currentTarget.value)}>
          {#each h.serials as serial (serial)}<option value={serial}>{serial}</option>{/each}
        </select>
      </label>
    {/if}
  </div>

  {#if s.orderRunning}
    <div class="card"><span class="spin"></span> {t('history.working')}</div>
  {/if}
  {#if s.undoResult}
    <div class="card {s.undoResult.errors.length
      ? 'border-[var(--warn-line)] bg-[var(--warn-bg)]'
      : 'border-[var(--ok-line)] bg-[var(--ok-bg)]'}" role="status">
      <b>{s.undoResult.order}: {s.undoResult.status_label}</b>
      {#if s.undoResult.admin_not_restored}<p class="mt-1">{t('history.admin_note')}</p>{/if}
      {#if s.undoResult.errors.length}
        <p class="mt-1">{t('history.undo_errors')}</p>
        <ul class="list-disc pl-5">{#each s.undoResult.errors as e, i (i)}<li>{e}</li>{/each}</ul>
      {/if}
    </div>
  {/if}

  {#if !h || !h.serial}
    <div class="card">{t('history.none')}</div>
  {:else if h.orders.length === 0}
    <div class="card">{t('history.empty')}</div>
  {:else}
    {#each h.orders as o (o.id)}
      <div class="card {o.status === 'undone' ? 'opacity-70' : ''}">
        <div class="flex flex-wrap items-center gap-2">
          <b class="mono">{o.number}</b>
          <span class="text-mut">{o.created_at.replace('T', ' ')}{o.client ? ` · ${o.client}` : ''} · {o.status_label}</span>
          {#if o.interrupted}<span class="tag tag-warn">{t('history.interrupted')}</span>{/if}
          <span class="ml-auto flex gap-2">
            {#if o.interrupted}
              <button class="btn px-2.5 py-1 text-[11px]" disabled={s.orderRunning}
                onclick={() => ctl.resume(o.number)}>{t('history.resume')}</button>
            {/if}
            {#if canUndo(o)}
              <button class="btn px-2.5 py-1 text-[11px]" disabled={s.orderRunning}
                onclick={() => ctl.undo(o.number)}>↶ {t('history.undo_all')}</button>
            {/if}
          </span>
        </div>
        <ul class="mt-2 flex flex-col gap-1">
          {#each o.actions as a (a.id)}
            <li class="flex items-center gap-2 text-[12px]">
              <span class={a.status === 'done' ? 'ok' : a.status === 'failed' ? 'bad' : 'text-mut'}>{ICON[a.status] ?? '·'}</span>
              <span>
                <b>{names.get(a.package) ?? a.package}</b> — {a.step_label}
                <span class="text-mut">({a.level_label}, {a.status_label}{a.error ? `: ${a.error}` : ''})</span>
              </span>
              {#if a.status === 'done'}
                <button class="btn-link ml-auto" disabled={s.orderRunning}
                  onclick={() => ctl.undo(o.number, a.id)}>↶ {t('history.restore')}</button>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/each}
  {/if}
</section>
