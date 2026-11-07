<script lang="ts">
  import { tick, untrack } from 'svelte';
  import type { ExplorerController } from '../../lib/explorer/controller';
  import { folderSummary, formatBytes, type SortKey, shortDate } from '../../lib/explorer/logic';
  import { FALLBACK, rowRange, type Viewport, viewport } from '../../lib/explorer/virtual';
  import { i18n, t } from '../../lib/i18n/index.svelte';
  import { enter, stagger } from '../../lib/motion';
  import type { EntryView } from '../../lib/types';
  import Icon from '../../ui/Icon.svelte';
  import FileIcon from './FileIcon.svelte';

  /** `now` — z ekranu, odświeżane (po północy „dziś” przechodzi we „wczoraj”). */
  type Props = { ex: ExplorerController; items: EntryView[]; now: Date };
  let { ex, items, now }: Props = $props();
  const s = $derived(ex.state);
  const COLS = 'grid grid-cols-[minmax(0,1fr)_88px_118px] items-center gap-3';
  const SORTS: SortKey[] = ['name', 'size', 'date'];
  /** Stała wysokość wiersza (wirtualizacja); mieści nazwę i drugą linię z nazwą folderu aplikacji. */
  const ROW_H = 46;
  const PAD_Y = 6;
  let box: HTMLElement;
  let vp = $state.raw<Viewport>({ top: 0, ...FALLBACK });
  let focusPath = $state<string | null>(null);

  const index = $derived(new Map(items.map((e, i) => [e.path, i])));
  const range = $derived(rowRange(items.length, ROW_H, Math.max(0, vp.top - PAD_Y), vp.height));
  // Dokładnie jeden wiersz w kolejności Tab: ostatnio aktywny, kotwica albo pierwszy widoczny.
  const tabPath = $derived([focusPath, s.anchor].find((p) => p !== null && index.has(p)) ?? items[0]?.path ?? null);
  const rendered = $derived.by(() => {
    const out: number[] = [];
    for (let i = range[0]; i < range[1]; i++) out.push(i);
    // wiersz z fokusem / w kolejności Tab zostaje w DOM, nawet gdy przewinięty poza okno
    for (const p of new Set([tabPath, focusPath])) {
      const i = p === null ? undefined : index.get(p);
      if (i !== undefined && (i < range[0] || i >= range[1])) out.push(i);
    }
    return out;
  });

  // Nowy folder zaczyna się od góry (lista zostaje zamontowana, `ex.go` podmienia tylko wpisy).
  let scrolledFor = untrack(() => s.path);
  $effect(() => {
    const path = s.path;
    untrack(() => {
      if (path === scrolledFor) return;
      scrolledFor = path;
      box.scrollTop = 0;
      vp = { ...vp, top: 0 };
    });
  });

  // Wejście wierszy tylko przy pokazaniu folderu — przewijanie nie „wlatuje” wierszami.
  let fresh = $state(true);
  $effect(() => {
    void s.path;
    fresh = true;
    const timer = setTimeout(() => (fresh = false), 600);
    return () => clearTimeout(timer);
  });
  function rowIn(node: Element, opts: { i: number; on: boolean }) {
    return opts.on ? enter(node, { delay: stagger(opts.i - range[0]), y: 6 }) : { duration: 0 };
  }

  /** Przewija tak, żeby wiersz był widoczny, i daje mu fokus. */
  async function reveal(path: string): Promise<void> {
    const i = index.get(path);
    if (i === undefined) return;
    const y = PAD_Y + i * ROW_H;
    let top = vp.top;
    if (y < top) top = y;
    else if (y + ROW_H > top + vp.height) top = y + ROW_H - vp.height;
    if (top !== vp.top) {
      box.scrollTop = top;
      vp = { ...vp, top };
    }
    focusPath = path;
    await tick();
    box.querySelector<HTMLElement>(`[data-path="${CSS.escape(path)}"]`)?.focus();
  }

  $effect(() => {
    const path = s.reveal;
    if (!path) return;
    s.reveal = null;
    void reveal(path);
  });

  /** Spacja na ekranie: plik pod kursorem albo z fokusem. */
  export function openPath(path: string): void {
    const entry = items.find((e) => e.path === path);
    if (entry) open(entry);
  }

  /** Folder — wchodzi do niego, plik — otwiera podgląd. */
  function open(entry: EntryView): void {
    if (entry.kind === 'dir') void ex.go(entry.path);
    else ex.openPreview(entry.path);
  }

  /** Klawiatura w liście: Enter wchodzi do folderu albo otwiera podgląd, Ctrl+Spacja przełącza zaznaczenie (samą Spację obsługuje ekran), strzałki przesuwają
   *  zaznaczenie (z Shift — zakres). */
  function onkey(e: KeyboardEvent, entry: EntryView, i: number): void {
    if (e.key === 'Enter') {
      e.preventDefault();
      open(entry);
    } else if (e.key === ' ' && e.ctrlKey) {
      e.preventDefault();
      ex.select(entry.path, { ctrl: true });
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = items[i + (e.key === 'ArrowDown' ? 1 : -1)];
      if (!next) return;
      ex.select(next.path, { shift: e.shiftKey });
      void reveal(next.path);
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
  <div bind:this={box} role="listbox" tabindex="-1" aria-label={t('explorer.list.label')} aria-multiselectable="true"
    {@attach viewport((v) => (vp = v))}
    onfocusin={(ev) => { const p = (ev.target as HTMLElement).dataset?.path; if (p) focusPath = p; }}
    class="scroll-fade min-h-0 flex-1 overflow-y-auto outline-none">
    <div class="relative" style:height="calc({items.length * ROW_H + 2 * PAD_Y}px + var(--dock-h, 0px))">
      {#each rendered as i (items[i].path)}
        {@const e = items[i]}
        {@const sel = s.selected.has(e.path)}
        {@const dir = e.kind === 'dir' && !e.locked ? folderSummary(s.dirStats[e.path], i18n.lang) : undefined}
        <div role="option" aria-selected={sel} data-path={e.path} tabindex={tabPath === e.path ? 0 : -1}
          in:rowIn={{ i, on: fresh }}
          onclick={(ev) => ex.clickSelect(e.path, ev.detail, { ctrl: ev.ctrlKey || ev.metaKey, shift: ev.shiftKey })}
          ondblclick={() => open(e)}
          onkeydown={(ev) => onkey(ev, e, i)}
          onmouseenter={() => (s.hover = e.path)} onmouseleave={() => { if (s.hover === e.path) s.hover = null; }}
          style:top="{PAD_Y + i * ROW_H}px" style:height="{ROW_H}px"
          class="group {COLS} absolute inset-x-0 cursor-default rounded-xl px-3 select-none transition-colors duration-150 [contain:layout_style]
            {sel ? 'bg-accent-soft shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--color-accent)_35%,transparent)]'
              : 'hover:bg-neutral-soft'}">
          <div class="flex min-w-0 items-center gap-3">
            <FileIcon kind={e.kind} type={e.type} ext={e.ext} locked={e.locked} size={26} />
            <div class="min-w-0">
              <div class="truncate text-sm font-semibold {sel ? 'text-accent' : 'text-ink'}">{e.label ?? e.name}</div>
              {#if e.label || (e.kind === 'dir' && !e.locked)}
                <div class="truncate text-2xs text-soft" data-folder-files={e.kind === 'dir' ? '' : undefined} title={dir?.hint || undefined}>
                  {#if e.label}<span class="mono">{e.name}</span>{#if e.kind === 'dir'} · {/if}{/if}
                  {#if e.kind === 'dir'}{dir ? dir.files : t('explorer.folder_stats.counting')}{/if}
                </div>
              {/if}
            </div>
            {#if e.locked}<span class="flex-none text-2xs font-semibold text-soft">{t('explorer.locked_row')}</span>{/if}
          </div>
          <div class="text-right text-xs text-mut tabular-nums" title={dir?.hint || undefined}>
            {#if e.kind !== 'dir'}{formatBytes(e.size, i18n.lang)}
            {:else if e.locked}{t('explorer.list.folder')}
            {:else if dir}{dir.size}
            {:else}<span class="text-soft" aria-label={t('explorer.folder_stats.counting')}>…</span>{/if}
          </div>
          <div class="text-right text-xs text-mut tabular-nums">{shortDate(e.mtime, now)}</div>
        </div>
      {/each}
    </div>
  </div>
</div>
