<script lang="ts">
  import { tick, untrack } from 'svelte';
  import { type ExplorerController } from '../../lib/explorer/controller';
  import { colName, colRange, columnWidths, findInBook, offsets, type SheetHit, toTsv } from '../../lib/explorer/sheet';
  import { FALLBACK } from '../../lib/explorer/virtual';
  import { observeSize } from '../../lib/resize';
  import { t, tp } from '../../lib/i18n/index.svelte';
  import type { EntryView, SheetBookView, SheetProblem } from '../../lib/types';
  import Banner from '../../ui/Banner.svelte';
  import Icon from '../../ui/Icon.svelte';
  import FindBar from './FindBar.svelte';

  /** Podgląd arkusza: siatka z literami kolumn i numerami wierszy (w DOM tylko widoczne komórki), zakładki arkuszy,
   *  szukanie we wszystkich arkuszach, pełna wartość zaznaczonej komórki i „Kopiuj arkusz” (TSV do Excela). */
  let { ex, entry }: { ex: ExplorerController; entry: EntryView } = $props();

  const COPIED_MS = 1500;
  const ROW_H = 26;
  const SPARE_ROWS = 6;
  let book = $state.raw<SheetBookView | null>(null);
  let problem = $state<SheetProblem['problem'] | null>(null);
  let failed = $state(false);
  let active = $state(0);
  let selected = $state<{ row: number; col: number } | null>(null);
  let query = $state('');
  let whole = $state(false);
  let current = $state(0);
  let copied = $state(false);
  let copyTimer: ReturnType<typeof setTimeout> | undefined;
  let box = $state<HTMLElement>();
  let vp = $state<{ top: number; left: number; width: number; height: number }>({ top: 0, left: 0, width: FALLBACK.width, height: FALLBACK.height });

  const sheet = $derived(book?.sheets[active] ?? null);
  const rows = $derived(sheet?.rows ?? []);
  const widths = $derived(columnWidths(rows));
  const edges = $derived(offsets(widths));
  const gutter = $derived(Math.max(44, String(rows.length).length * 8 + 20));
  const totalW = $derived(gutter + edges[edges.length - 1]);
  const totalH = $derived((rows.length + 1) * ROW_H);
  const firstRow = $derived(Math.max(0, Math.floor(vp.top / ROW_H) - 1 - SPARE_ROWS));
  const lastRow = $derived(Math.min(rows.length, Math.ceil((vp.top + vp.height) / ROW_H) + SPARE_ROWS));
  const cols = $derived(colRange(edges, Math.max(0, vp.left), Math.max(0, vp.width - gutter)));
  const visibleCols = $derived(Array.from({ length: cols[1] - cols[0] }, (_, i) => cols[0] + i));
  const visibleRows = $derived(Array.from({ length: Math.max(0, lastRow - firstRow) }, (_, i) => firstRow + i));

  const hits = $derived<SheetHit[]>(book ? findInBook(book.sheets, query, whole) : []);
  const perSheet = $derived.by(() => {
    const out = new Map<number, number>();
    for (const h of hits) out.set(h.sheet, (out.get(h.sheet) ?? 0) + 1);
    return out;
  });
  /** Trafienia bieżącego arkusza: `wiersz:kolumna` → numer trafienia. */
  const marks = $derived.by(() => {
    const out = new Map<string, number>();
    hits.forEach((h, i) => { if (h.sheet === active) out.set(`${h.row}:${h.col}`, i); });
    return out;
  });
  const value = $derived(selected ? rows[selected.row]?.[selected.col] ?? '' : '');
  const separator = $derived(book?.delimiter ? t(`explorer.preview.sheet_sep.${({ ';': 'semicolon', ',': 'comma', '\t': 'tab', '|': 'pipe' } as Record<string, string>)[book.delimiter] ?? 'comma'}`) : '');

  function scrollTo(row: number, col: number): void {
    if (!box) return;
    const top = (row + 1) * ROW_H;
    if (top < box.scrollTop + ROW_H || top + ROW_H > box.scrollTop + box.clientHeight) box.scrollTop = top - box.clientHeight / 2;
    const left = edges[col] ?? 0;
    const right = edges[col + 1] ?? left;
    const view = box.clientWidth - gutter;
    if (left < box.scrollLeft || right > box.scrollLeft + view) box.scrollLeft = Math.max(0, left - view / 3);
    measure();
  }

  async function showHit(): Promise<void> {
    const hit = hits[current];
    if (!hit) return;
    if (hit.sheet !== active) active = hit.sheet;
    selected = { row: hit.row, col: hit.col };
    await tick();
    scrollTo(hit.row, hit.col);
  }
  $effect(() => {
    void hits;
    void current;
    untrack(() => void showHit());
  });

  function search(q: string, w: boolean): void {
    query = q;
    whole = w;
    current = 0;
  }
  function step(delta: number): void {
    if (hits.length) current = (current + delta + hits.length) % hits.length;
  }
  function pick(index: number): void {
    if (index === active) return;
    active = index;
    selected = null;
    if (box) { box.scrollTop = 0; box.scrollLeft = 0; }
    measure();
    const first = hits.findIndex((h) => h.sheet === index);  // szukanie idzie dalej od tego arkusza
    if (first >= 0) current = first;
  }

  function measure(): void {
    if (!box) return;
    vp = { top: box.scrollTop, left: box.scrollLeft, width: box.clientWidth || FALLBACK.width, height: box.clientHeight || FALLBACK.height };
  }
  function track(node: HTMLElement) {
    const stop = observeSize(node, measure);
    node.addEventListener('scroll', measure, { passive: true });
    return () => { stop(); node.removeEventListener('scroll', measure); };
  }

  $effect(() => {
    const path = entry.path;
    let stale = false;
    book = null;
    problem = null;
    failed = false;
    active = 0;
    selected = null;
    void ex.sheet(path).then((r) => {
      if (stale) return;
      if (!r) failed = true;
      else if ('problem' in r) problem = r.problem;
      else {
        book = r;
        active = Math.max(0, r.sheets.findIndex((s) => !s.hidden));
      }
    });
    return () => { stale = true; clearTimeout(copyTimer); };
  });

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(toTsv(rows));
    } catch {
      return;  // schowek zablokowany — bez udawania, że się udało
    }
    copied = true;
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => (copied = false), COPIED_MS);
  }
</script>

<div class="absolute inset-0 flex flex-col gap-3 p-6" aria-label={t('explorer.preview.sheet_label')} role="region">
  {#if failed}
    <Banner tone="bad" icon="triangle-alert">{t('explorer.preview.failed')}</Banner>
  {:else if problem}
    <Banner tone="info" icon="info">{t(`explorer.preview.sheet_problem.${problem}`)}</Banner>
  {:else if !book}
    <span class="spin m-4 inline-block" role="status" aria-label={t('explorer.preview.loading')}></span>
  {:else}
    <div class="flex flex-none items-center gap-3 text-xs text-white/70">
      {#if book.sheets.length > 1}<span class="tabular-nums">{tp('explorer.preview.sheet_count', book.sheets.length)}</span>{/if}
      <span class="tabular-nums">{tp('explorer.preview.sheet_rows', rows.length)}</span>
      {#if separator}<span class="rounded-full bg-white/10 px-2.5 py-0.5 font-semibold">{t('explorer.preview.sheet_delimiter', { delimiter: separator })}</span>{/if}
      {#if book.encoding}<span class="rounded-full bg-white/10 px-2.5 py-0.5 font-semibold">{t('explorer.preview.encoding', { encoding: book.encoding })}</span>{/if}
      <span class="flex-1"></span>
      <button type="button" onclick={copy} disabled={!rows.length}
        class="inline-flex items-center gap-1.5 rounded-[10px] bg-white/10 px-3 py-1.5 font-semibold text-white transition duration-150
          enabled:hover:bg-white/20 disabled:opacity-50">
        <Icon name={copied ? 'check' : 'copy'} size={14} />{copied ? t('explorer.preview.text_copied') : t('explorer.preview.sheet_copy')}
      </button>
    </div>
    <FindBar total={hits.length} {current} onsearch={search} onstep={step} />
    {#if sheet?.truncated}
      <p class="flex-none text-xs text-white/70">{t('explorer.preview.sheet_truncated')}</p>
    {/if}
    <div class="flex min-h-[34px] flex-none items-start gap-2 rounded-xl bg-white/[.06] px-3 py-1.5 text-[13px]" data-cellbar>
      <b class="mono flex-none pt-px text-white/60 tabular-nums">{selected ? `${colName(selected.col)}${selected.row + 1}` : ''}</b>
      <span class="max-h-24 min-w-0 flex-1 overflow-auto break-words whitespace-pre-wrap text-white/90 select-text">{value}</span>
    </div>

    <div bind:this={box} {@attach track} data-grid
      class="relative min-h-0 flex-1 overflow-auto rounded-2xl bg-white/[.04] text-[13px] shadow-[inset_0_0_0_1px_rgb(255_255_255/.08)]">
      {#if !rows.length}
        <p class="p-4 text-white/60">{t('explorer.preview.sheet_empty')}</p>
      {:else}
        <div class="relative" style:width="{totalW}px" style:height="{totalH}px">
          <div class="sticky top-0 z-20 flex bg-[#151922] text-[11px] font-semibold text-white/55" style:height="{ROW_H}px" style:width="{totalW}px">
            <div class="sticky left-0 z-10 flex-none border-r border-b border-white/10 bg-[#151922]" style:width="{gutter}px"></div>
            {#each visibleCols as c (c)}
              <div class="absolute top-0 grid h-full place-items-center border-r border-b border-white/10
                {selected?.col === c ? 'bg-accent/30 text-white' : ''}"
                style:left="{gutter + edges[c]}px" style:width="{widths[c]}px">{colName(c)}</div>
            {/each}
          </div>
          {#each visibleRows as r (r)}
            <div class="absolute left-0 flex" style:top="{(r + 1) * ROW_H}px" style:height="{ROW_H}px" style:width="{totalW}px" data-row={r}>
              <div class="sticky left-0 z-10 flex-none border-r border-b border-white/10 bg-[#151922] pr-2 text-right text-[11px] leading-[26px]
                font-semibold tabular-nums {selected?.row === r ? 'text-white' : 'text-white/45'}" style:width="{gutter}px">{r + 1}</div>
              {#each visibleCols as c (c)}
                {@const v = rows[r][c] ?? ''}
                {@const hit = marks.get(`${r}:${c}`)}
                <button type="button" tabindex="-1" title={v.length > 30 || v.includes('\n') ? v : undefined}
                  onclick={() => (selected = { row: r, col: c })} data-hit={hit}
                  class="absolute top-0 h-full truncate border-r border-b border-white/[.07] px-2 text-left leading-[25px] text-white/90
                    {hit === current && hit !== undefined ? 'cell-active' : hit !== undefined ? 'cell-hit' : ''}
                    {selected?.row === r && selected?.col === c ? 'cell-selected' : ''}
                    {/^-?[\d\s]+([.,]\d+)?%?$/.test(v) ? 'text-right tabular-nums' : ''}"
                  style:left="{gutter + edges[c]}px" style:width="{widths[c]}px">{v}</button>
              {/each}
            </div>
          {/each}
        </div>
      {/if}
    </div>

    {#if book.sheets.length > 1}
      <nav class="flex flex-none gap-1 overflow-x-auto" aria-label={t('explorer.preview.sheet_tabs')}>
        {#each book.sheets as s, i (i)}
          {@const n = perSheet.get(i) ?? 0}
          <button type="button" onclick={() => pick(i)} aria-current={i === active ? 'true' : undefined}
            class="inline-flex flex-none items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition duration-150
              {i === active ? 'bg-white/20 text-white' : 'bg-white/[.06] text-white/70 hover:bg-white/15'} {s.hidden ? 'italic' : ''}">
            {s.name || '—'}{#if s.hidden}<span class="font-normal text-white/50">({t('explorer.preview.sheet_hidden')})</span>{/if}
            {#if n}<span class="rounded-full bg-[#fde68a] px-1.5 text-[10px] text-[#111827] tabular-nums"
              title={tp('explorer.preview.sheet_hits', n)}>{n}</span>{/if}
          </button>
        {/each}
      </nav>
    {/if}
  {/if}
</div>

<style>
  .cell-hit { background: rgb(253 230 138 / .85); color: #111827; }
  .cell-active { background: #fb923c; color: #111827; }
  .cell-selected { outline: 2px solid var(--color-accent, #60a5fa); outline-offset: -2px; z-index: 1; }
</style>
