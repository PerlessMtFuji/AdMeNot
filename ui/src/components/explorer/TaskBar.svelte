<script lang="ts">
  import { fly, slide } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import type { ExplorerController } from '../../lib/explorer/controller';
  import { formatBytes } from '../../lib/explorer/logic';
  import { i18n, t, tp } from '../../lib/i18n/index.svelte';
  import { DUR, ms } from '../../lib/motion';
  import type { TaskView } from '../../lib/types';
  import Banner from '../../ui/Banner.svelte';
  import Button from '../../ui/Button.svelte';
  import Icon from '../../ui/Icon.svelte';
  import Progress from '../../ui/Progress.svelte';

  /** Pasek zadań na dole ekranu: bieżące zadanie z postępem, ▾ rozwija kolejkę, skończone zostają do ukrycia. */
  let { ex }: { ex: ExplorerController } = $props();
  const s = $derived(ex.state);
  const ACTIVE = ['queued', 'running', 'paused', 'waiting'];
  const active = $derived(s.tasks.filter((x) => ACTIVE.includes(x.status)));
  const finished = $derived(s.tasks.filter((x) => !ACTIVE.includes(x.status)));
  const current = $derived(active[0]);
  const rest = $derived(active.slice(1));
  let unfolded = $state(false);
  const MAX_FAILED = 5;

  const ICON_BTN = 'grid h-8 w-8 place-items-center rounded-[10px] text-mut transition duration-150 hover:bg-neutral-soft hover:text-ink';

  function ratio(x: TaskView): number {
    if (x.total_bytes > 0) return x.done_bytes / x.total_bytes;
    return x.total_files > 0 ? x.done_files / x.total_files : 0;
  }

  function eta(sec: number): string {
    return sec < 60 ? t('eta.under_min') : t('eta.min', { n: Math.round(sec / 60) });
  }

  function title(x: TaskView): string {
    return t(x.kind === 'to_pc' ? 'explorer.task.to_pc' : 'explorer.task.to_phone');
  }

  function name(path: string): string {
    return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
  }

  function damaged(x: TaskView): number {
    return x.failed.filter((f) => f.reason === 'mismatch').length;
  }

  function outcome(x: TaskView): string {
    if (x.status === 'cancelled') return t('explorer.task.cancelled');
    if (x.status === 'failed') return t('explorer.task.failed');
    if (x.failed.length) return t('explorer.task.with_errors');
    return tp(x.kind === 'to_pc' ? 'explorer.task.copied' : 'explorer.task.uploaded', x.done_files);
  }
</script>

{#snippet controls(x: TaskView)}
  <span class="flex flex-none items-center gap-0.5">
    {#if x.status === 'running'}
      <button type="button" class={ICON_BTN} aria-label={t('explorer.task.pause')} title={t('explorer.task.pause')}
        onclick={() => ex.pause(x.id)}><Icon name="pause" size={16} /></button>
    {:else if x.status === 'paused'}
      <button type="button" class={ICON_BTN} aria-label={t('explorer.task.resume')} title={t('explorer.task.resume')}
        onclick={() => ex.resume(x.id)}><Icon name="play" size={16} /></button>
    {/if}
    <button type="button" class={ICON_BTN} aria-label={t('explorer.task.cancel')} title={t('explorer.task.cancel')}
      onclick={() => ex.cancel(x.id)}><Icon name="x" size={16} /></button>
  </span>
{/snippet}

{#snippet activeRow(x: TaskView)}
  {#if x.status === 'waiting'}
    <Banner tone="warn" icon="wifi-off" title={title(x)}>
      {t('explorer.task.waiting')}
      {#snippet actions()}
        <Button size="sm" variant="ghost" onclick={() => ex.cancel(x.id)}>{t('explorer.task.cancel')}</Button>
      {/snippet}
    </Banner>
  {:else}
    <div class="flex min-w-0 items-center gap-3">
      <Icon name={x.kind === 'to_pc' ? 'download' : 'upload'} size={18} class="text-accent" />
      <div class="flex min-w-0 flex-1 flex-col gap-1.5">
        <div class="flex items-baseline gap-2.5">
          <b class="truncate text-sm text-ink">{title(x)}</b>
          <span class="text-2xs font-semibold text-mut tabular-nums">{t('explorer.task.progress', { done: x.done_files, total: x.total_files })}</span>
          <span class="flex-1"></span>
          {#if x.status === 'queued'}
            <span class="text-2xs font-semibold text-soft">{t('explorer.task.queued')}</span>
          {:else if x.status === 'paused'}
            <span class="text-2xs font-semibold text-warn">{t('explorer.task.paused')}</span>
          {:else if x.speed > 0}
            <span class="text-2xs text-mut tabular-nums">
              {t('explorer.task.speed', { speed: formatBytes(x.speed, i18n.lang) })}{x.eta_s !== null ? ` · ${eta(x.eta_s)}` : ''}
            </span>
          {/if}
        </div>
        <Progress value={ratio(x)} label={title(x)} />
      </div>
      {@render controls(x)}
    </div>
  {/if}
{/snippet}

{#snippet doneRow(x: TaskView)}
  {@const bad = x.failed.length}
  {@const hurt = damaged(x)}
  <div class="flex flex-col gap-2">
    <div class="flex min-w-0 items-center gap-3">
      <span class="grid h-8 w-8 flex-none place-items-center rounded-full {bad || x.status !== 'done' ? 'bg-warn-strong/25 text-warn' : 'bg-ok/15 text-ok'}">
        <Icon name={bad || x.status !== 'done' ? 'triangle-alert' : 'check'} size={16} />
      </span>
      <div class="flex min-w-0 flex-1 flex-col">
        <b class="truncate text-sm text-ink">{outcome(x)}</b>
        <span class="flex flex-wrap gap-x-2.5 text-2xs text-mut">
          {#if bad}<span>{tp(x.kind === 'to_pc' ? 'explorer.task.failed_pc' : 'explorer.task.failed_phone', bad)}</span>{/if}
          {#if hurt}<span>{tp('explorer.task.damaged', hurt)}</span>{/if}
          {#if x.skipped}<span>{tp('explorer.task.skipped', x.skipped)}</span>{/if}
          {#if x.renamed}
            <span title={t(x.kind === 'to_pc' ? 'explorer.task.renamed_title_pc' : 'explorer.task.renamed_title_phone')}>{tp('explorer.task.renamed', x.renamed)}</span>
          {/if}
          {#if x.verified === 'hash' && !bad}<span>{t('explorer.task.verified')}</span>{/if}
        </span>
      </div>
      {#if x.status === 'done'}
        {#if ex.canRetry(x)}
          <Button size="sm" title={t('explorer.task.retry_title')} onclick={() => ex.retryDamaged(x)}>{t('explorer.task.retry')}</Button>
        {/if}
        {#if x.kind === 'to_pc'}
          <Button size="sm" onclick={() => ex.openFolder(x)}>{t('explorer.task.open_folder')}</Button>
        {:else}
          <Button size="sm" onclick={() => ex.show(x)}>{t('explorer.task.show')}</Button>
        {/if}
      {/if}
      <button type="button" class={ICON_BTN} aria-label={t('explorer.task.dismiss')} title={t('explorer.task.dismiss')}
        onclick={() => ex.dismissTask(x.id)}><Icon name="x" size={16} /></button>
    </div>
    {#if bad}
      <ul class="ml-11 flex flex-col gap-0.5 text-2xs text-mut">
        {#each x.failed.slice(0, MAX_FAILED) as f (f.path)}
          <li class="truncate">{name(f.path)} — {t(`explorer.task.reason_${x.kind === 'to_pc' ? 'pc' : 'phone'}.${f.reason}`)}</li>
        {/each}
        {#if bad > MAX_FAILED}<li>{tp('explorer.task.more', bad - MAX_FAILED)}</li>{/if}
      </ul>
    {/if}
  </div>
{/snippet}

{#if s.tasks.length}
  <section aria-label={t('explorer.task.label')}
    transition:fly={{ y: 24, duration: ms(DUR.panel), easing: cubicOut }}
    class="flex flex-none flex-col gap-2.5 rounded-2xl card px-4 py-3">
    {#each finished as x (x.id)}
      <div transition:slide={{ duration: ms(DUR.micro) }}>{@render doneRow(x)}</div>
    {/each}
    {#if current}
      <div>
        {@render activeRow(current)}
        {#if rest.length}
          <button type="button" aria-expanded={unfolded} onclick={() => (unfolded = !unfolded)}
            class="mt-2 inline-flex items-center gap-1 text-2xs font-semibold text-mut hover:text-ink">
            {t('explorer.task.queue', { count: active.length })}
            <Icon name="chevron-down" size={14} class="transition-transform duration-150 {unfolded ? 'rotate-180' : ''}" />
          </button>
        {/if}
      </div>
      {#if unfolded}
        <ul class="flex flex-col gap-2 border-t border-line pt-2.5" transition:slide={{ duration: ms(DUR.micro) }}>
          {#each rest as x (x.id)}<li>{@render activeRow(x)}</li>{/each}
        </ul>
      {/if}
    {/if}
  </section>
{/if}
