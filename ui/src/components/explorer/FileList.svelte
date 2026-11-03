<script lang="ts">
  import type { ExplorerController } from '../../lib/explorer/controller';
  import { formatBytes, type SortKey, shortDate } from '../../lib/explorer/logic';
  import { i18n, t } from '../../lib/i18n/index.svelte';
  import { enter, stagger } from '../../lib/motion';
  import type { EntryView } from '../../lib/types';
  import Icon from '../../ui/Icon.svelte';
  import FileIcon from './FileIcon.svelte';

  type Props = { ex: ExplorerController; items: EntryView[] };
  let { ex, items }: Props = $props();
  const s = $derived(ex.state);
  const now = new Date();
  const COLS = 'grid grid-cols-[minmax(0,1fr)_88px_118px] items-center gap-3';
  const SORTS: SortKey[] = ['name', 'size', 'date'];
  let box: HTMLElement;

  /** Klawiatura w liście: Enter wchodzi do folderu, strzałki przesuwają zaznaczenie (z Shift — zakres). */
  function onkey(e: KeyboardEvent, entry: EntryView, i: number): void {
    if (e.key === 'Enter' && entry.kind === 'dir') {
      e.preventDefault();
      void ex.go(entry.path);
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = items[i + (e.key === 'ArrowDown' ? 1 : -1)];
      if (!next) return;
      ex.select(next.path, { shift: e.shiftKey });
      box.querySelector<HTMLElement>(`[data-path="${CSS.escape(next.path)}"]`)?.focus();
    }
  }
</script>

<div class="flex min-h-0 flex-1 flex-col">
  <div role="row" class="{COLS} border-b border-line/70 px-3 pb-2 text-2xs font-bold text-mut">
    {#each SORTS as key (key)}
      {@const on = s.sort.key === key}
      <div role="columnheader" aria-sort={on ? (s.sort.dir === 1 ? 'ascending' : 'descending') : 'none'}
        class={key === 'name' ? '' : 'text-right'}>
        <button type="button" onclick={() => ex.setSort(key)}
          class="inline-flex items-center gap-1 rounded-md px-1 py-0.5 transition duration-150 hover:text-ink
            {key === 'name' ? '' : 'flex-row-reverse'} {on ? 'text-ink' : ''}">
          {t(`explorer.list.${key}`)}
          <span class="transition duration-200 {on ? 'opacity-100' : 'opacity-0'}">
            <Icon name={on && s.sort.dir === -1 ? 'arrow-down' : 'arrow-up'} size={12} strokeWidth={2.6} />
          </span>
        </button>
      </div>
    {/each}
  </div>
  <div bind:this={box} role="listbox" aria-label={t('explorer.list.label')} aria-multiselectable="true"
    class="scroll-fade min-h-0 flex-1 overflow-y-auto py-1.5">
    {#each items as e, i (e.path)}
      {@const sel = s.selected.has(e.path)}
      <div role="option" aria-selected={sel} data-path={e.path} tabindex={(s.anchor ?? items[0]?.path) === e.path ? 0 : -1}
        in:enter={{ delay: stagger(i), y: 6 }}
        onclick={(ev) => ex.select(e.path, { ctrl: ev.ctrlKey || ev.metaKey, shift: ev.shiftKey })}
        ondblclick={() => { if (e.kind === 'dir') void ex.go(e.path); }}
        onkeydown={(ev) => onkey(ev, e, i)}
        class="group {COLS} cursor-default rounded-xl px-3 py-1.5 select-none transition-colors duration-150
          {sel ? 'bg-accent-soft shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-accent)_35%,transparent)]'
            : 'hover:bg-neutral-soft'}">
        <div class="flex min-w-0 items-center gap-3">
          <FileIcon kind={e.kind} type={e.type} ext={e.ext} locked={e.locked} size={26} />
          <div class="min-w-0">
            <div class="truncate text-sm font-semibold {sel ? 'text-accent' : 'text-ink'}">{e.label ?? e.name}</div>
            {#if e.label}<div class="mono truncate text-2xs text-soft">{e.name}</div>{/if}
          </div>
          {#if e.locked}<span class="flex-none text-2xs font-semibold text-soft">{t('explorer.locked_row')}</span>{/if}
        </div>
        <div class="text-right text-xs text-mut tabular-nums">
          {e.kind === 'dir' ? t('explorer.list.folder') : formatBytes(e.size, i18n.lang)}
        </div>
        <div class="text-right text-xs text-mut tabular-nums">{shortDate(e.mtime, now)}</div>
      </div>
    {/each}
  </div>
</div>
