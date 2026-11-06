<script lang="ts">
  import { tick, untrack } from 'svelte';
  import type { ExplorerController } from '../../lib/explorer/controller';
  import { days } from '../../lib/explorer/logic';
  import { openMorph } from '../../lib/explorer/morph';
  import type { ThumbQueue } from '../../lib/explorer/thumbs';
  import {
    FALLBACK, GRID, type GroupIn, gridLayout, inView, locate, neighbour, type Rect, tileRect, tilesInRect, type Viewport,
    viewport, visibleSlices,
  } from '../../lib/explorer/virtual';
  import { t, tp } from '../../lib/i18n/index.svelte';
  import { reducedMotion } from '../../lib/motion';
  import type { EntryView } from '../../lib/types';
  import Icon from '../../ui/Icon.svelte';
  import Lasso from './Lasso.svelte';
  import Thumb from './Thumb.svelte';

  type Props = { ex: ExplorerController; items: EntryView[]; now: Date; thumbs: ThumbQueue };
  let { ex, items, now, thumbs }: Props = $props();
  const s = $derived(ex.state);

  /** Margines treści w obszarze przewijanym (poświata zaznaczonego kafla nie jest ucinana). */
  const PAD = 6;
  /** Kaskada wyostrzania: odstęp między kolejnymi kaflami i najdalszy kafel z własnym opóźnieniem. */
  const STEP_MS = 25;
  const STEP_MAX = 12;
  const DIRS = '/dirs';

  let box: HTMLElement;
  let content: HTMLElement;
  let vp = $state<Viewport>({ top: 0, ...FALLBACK });
  let focusPath = $state<string | null>(null);
  let lasso = $state<Rect | null>(null);

  // Foldery na górze, pliki po dniach (kolejność dni jak w sortowaniu listy).
  const groups = $derived.by((): GroupIn[] => {
    const dirs = items.filter((e) => e.kind === 'dir');
    const files = items.filter((e) => e.kind === 'file');
    return [...(dirs.length ? [{ key: DIRS, label: t('explorer.gallery.folders'), items: dirs }] : []), ...days(files, now)];
  });
  const layout = $derived(gridLayout(groups, Math.max(1, vp.width - 2 * PAD)));
  const order = $derived(layout.order.map((e) => e.path));
  const index = $derived(new Map(order.map((p, i) => [p, i])));
  const slices = $derived(visibleSlices(layout, vp));
  const seen = $derived(inView(layout, vp));
  // Dokładnie jeden kafel w kolejności Tab: ostatnio aktywny, kotwica albo pierwszy widoczny.
  const tabPath = $derived([focusPath, s.anchor].find((p) => p !== null && index.has(p)) ?? order[0] ?? null);

  const source = (e: EntryView) => e.thumb ?? (e.type === 'video' ? e.url : null);

  interface Tile { e: EntryView; rect: Rect; i: number }
  const tiles = $derived.by((): Tile[] => {
    const out: Tile[] = [];
    const add = (section: (typeof layout.sections)[number], i: number) =>
      out.push({ e: section.items[i], rect: tileRect(layout, section, i), i: section.first + i });
    for (const { section, from, to } of slices) for (let i = from; i < to; i++) add(section, i);
    // kafel z fokusem / w kolejności Tab zostaje w DOM, nawet gdy przewinięty poza okno
    for (const p of new Set([tabPath, focusPath])) {
      const i = p === null ? undefined : index.get(p);
      const at = i === undefined ? null : locate(layout, i);
      if (at && !out.some((x) => x.e.path === p)) add(at.section, at.i);
    }
    return out;
  });

  // Nowy folder zaczyna się od góry (widok zostaje zamontowany, `ex.go` podmienia tylko wpisy). Przed
  // kaskadą: ta bierze kafle widoczne po przewinięciu na górę.
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

  // Pierwsze pokazanie folderu: kafle widoczne w tej chwili wyostrzają się kaskadą.
  let shown = $state<{ path: string; at: number; order: Map<string, number> } | null>(null);
  $effect(() => {
    const path = s.path;
    const first = seen;
    untrack(() => {
      if (shown?.path === path || !first.length) return;
      shown = { path, at: performance.now(), order: new Map(first.map((e, i) => [e.path, Math.min(i, STEP_MAX)])) };
    });
  });
  function cascadeAt(path: string): number | null {
    const n = shown?.order.get(path);
    if (!shown || n === undefined || reducedMotion()) return null;
    const at = shown.at + n * STEP_MS;
    return performance.now() > at + 500 ? null : at;  // po kaskadzie (przewinięcie i powrót) — już bez niej
  }

  // Kolejka miniatur: widoczne pierwsze (w kolejności na ekranie), zapas ± 2 wiersze potem; reszta anulowana.
  $effect(() => {
    const wanted: [string, number][] = [];
    const visible = new Set(seen.map((e) => e.path));
    for (const { e, i } of tiles) {
      const url = source(e);
      if (url) wanted.push([url, visible.has(e.path) ? i : 100_000 + i]);
    }
    untrack(() => {
      thumbs.cancelAllExcept(new Set(wanted.map(([url]) => url)));
      for (const [url, priority] of wanted) thumbs.want(url, priority);
    });
  });
  $effect(() => () => thumbs.cancelAllExcept(new Set()));

  /** Kolor dominujący dnia: pierwsza znana miniatura z początku dnia. */
  function dayColor(group: GroupIn): string | null {
    for (const e of group.items.slice(0, 24)) {
      const url = source(e);
      const color = url ? thumbs.get(url)?.color : null;
      if (color) return color;
    }
    return null;
  }

  function daySelected(group: GroupIn): boolean {
    return group.items.length > 0 && group.items.every((e) => s.selected.has(e.path));
  }

  function onclick(ev: MouseEvent, e: EntryView): void {
    const check = ev.target instanceof Element && ev.target.closest('[data-check]');
    if (check) ex.select(e.path, { ctrl: true }, order);
    else ex.clickSelect(e.path, ev.detail, { ctrl: ev.ctrlKey || ev.metaKey, shift: ev.shiftKey }, order);
  }

  /** Przewija tak, żeby kafel był cały widoczny (pod nagłówkiem dnia), i daje mu fokus. */
  async function reveal(path: string): Promise<void> {
    const i = index.get(path);
    const at = i === undefined ? null : locate(layout, i);
    if (!at) return;
    const r = tileRect(layout, at.section, at.i);
    let top = vp.top;
    if (r.y - GRID.header < top) top = r.y - GRID.header;
    else if (r.y + r.h + PAD > top + vp.height) top = r.y + r.h + PAD - vp.height;
    if (top !== vp.top) {
      box.scrollTop = top;
      vp = { ...vp, top };
    }
    focusPath = path;
    await tick();
    box.querySelector<HTMLElement>(`[data-path="${CSS.escape(path)}"]`)?.focus();
  }

  /** Folder — wchodzi do niego, plik — otwiera podgląd (zdjęcie rośnie z kafla). */
  function open(e: EntryView): void {
    ex.cancelClick();
    if (e.kind === 'dir') void ex.go(e.path);
    else void openMorph(e.path, () => ex.openPreview(e.path));
  }

  /** Klawiatura w siatce: Enter wchodzi do folderu albo otwiera podgląd, Spacja przełącza zaznaczenie, strzałki przesuwają
   *  (z Shift — zakres). */
  function onkey(ev: KeyboardEvent, e: EntryView, i: number): void {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      open(e);
    } else if (ev.key === ' ') {
      ev.preventDefault();
      ex.select(e.path, { ctrl: true }, order);
    } else if (ev.key.startsWith('Arrow')) {
      const next = neighbour(layout, i, ev.key);
      ev.preventDefault();
      if (next === null) return;
      ex.select(order[next], { shift: ev.shiftKey }, order);
      void reveal(order[next]);
    }
  }

  // ---- zaznaczanie prostokątem ----------------------------------------------------------------
  /** Punkt w układzie treści (z przewinięciem). */
  function point(ev: MouseEvent): { x: number; y: number } {
    const r = content.getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  }

  /** Przerwanie ciągnięcia (koniec ciągnięcia albo zniknięcie galerii w jego trakcie). */
  let endDrag: (() => void) | null = null;
  $effect(() => () => endDrag?.());

  function onmousedown(ev: MouseEvent): void {
    const target = ev.target instanceof Element ? ev.target : null;
    if (ev.button !== 0 || target?.closest('[role="option"], button')) return;
    if (ev.offsetX > box.clientWidth && box.clientWidth > 0) return;  // pasek przewijania
    ev.preventDefault();
    const additive = ev.ctrlKey || ev.metaKey;
    const base = additive ? [...s.selected] : [];
    const start = point(ev);
    let moved = false;
    const move = (m: MouseEvent) => {
      // przy krawędzi obszaru przewija się sam
      const b = box.getBoundingClientRect();
      if (b.height > 0 && m.clientY > b.bottom - 24) box.scrollTop += 24;
      else if (b.height > 0 && m.clientY < b.top + 24) box.scrollTop -= 24;
      const p = point(m);
      const rect = { x: Math.min(start.x, p.x), y: Math.min(start.y, p.y), w: Math.abs(p.x - start.x), h: Math.abs(p.y - start.y) };
      if (!moved && rect.w < 3 && rect.h < 3) return;
      moved = true;
      lasso = rect;
      ex.selectRect([...base, ...tilesInRect(layout, rect)], false);
    };
    const stop = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      endDrag = null;
    };
    const up = () => {
      stop();
      if (!moved && !additive) ex.clear();  // klik w puste miejsce — jak w Windows
      lasso = null;
    };
    endDrag?.();
    endDrag = stop;
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  }
</script>

<div bind:this={box} role="listbox" tabindex="-1" aria-label={t('explorer.list.label')} aria-multiselectable="true"
  {@attach viewport((v) => (vp = v))} {onmousedown}
  onfocusin={(ev) => { const p = (ev.target as HTMLElement).dataset?.path; if (p) focusPath = p; }}
  class="relative min-h-0 flex-1 overflow-y-auto overscroll-contain outline-none select-none">
  <div bind:this={content} class="relative" style:height="{layout.height + PAD}px" style:margin="0 {PAD}px">
    {#each slices as { section } (section.key)}
      {@const all = daySelected(section)}
      {@const color = section.key === DIRS ? null : dayColor(section)}
      <!-- Pas sekcji (cała wysokość dnia) tylko po to, żeby nagłówek był przyklejony w jej granicach. -->
      <div class="pointer-events-none absolute inset-x-0 z-10" style:top="{section.top}px" style:height="{section.height}px">
        <div class="sticky top-0 flex items-center" style:height="{GRID.header}px">
          {#if section.key === DIRS}
            <span data-day class="glass-pill pointer-events-auto rounded-full px-3 py-1 text-xs font-extrabold text-ink">
              {section.label}
            </span>
          {:else}
            <button type="button" data-day onclick={() => ex.selectDay(section.key)}
              aria-label={t(all ? 'explorer.gallery.unselect_day' : 'explorer.gallery.select_day', { day: section.label })}
              aria-pressed={all}
              class="glass-pill group/day pointer-events-auto flex items-center gap-2 rounded-full py-1 pr-3 pl-1.5 text-xs font-extrabold text-ink"
              style:--day={color}>
              <span class="grid h-[18px] w-[18px] place-items-center rounded-full transition-[transform,opacity] duration-200
                {all ? 'bg-accent text-white' : 'text-transparent shadow-[inset_0_0_0_1.5px_var(--color-soft)] group-hover/day:text-soft'}">
                <Icon name="check" size={11} strokeWidth={3.2} />
              </span>
              {section.label}
              <span class="font-semibold text-mut tabular-nums">{tp('explorer.gallery.files', section.items.length)}</span>
            </button>
          {/if}
        </div>
      </div>
    {/each}
    {#each tiles as { e, rect, i } (e.path)}
      {@const sel = s.selected.has(e.path)}
      {@const url = source(e)}
      <div role="option" aria-selected={sel} aria-label={e.label ?? e.name} data-path={e.path} tabindex={tabPath === e.path ? 0 : -1}
        class="group absolute top-0 left-0 rounded-[12px] outline-offset-2"
        style:transform="translate({rect.x}px, {rect.y}px)" style:width="{rect.w}px" style:height="{rect.h}px"
        onclick={(ev) => onclick(ev, e)}
        ondblclick={(ev) => { if (!(ev.target instanceof Element && ev.target.closest('[data-check]'))) open(e); }}
        onkeydown={(ev) => onkey(ev, e, i)}>
        <div class="h-full w-full {s.fresh.has(e.path) ? '[animation:pop-in_.35s]' : ''}">
          <Thumb entry={e} thumb={url ? thumbs.get(url) : null} noThumb={!url || thumbs.failed(url)} selected={sel}
            cascadeAt={cascadeAt(e.path)} onbroken={() => { if (url) thumbs.broken(url); }} />
        </div>
      </div>
    {/each}
    {#if lasso}<Lasso rect={lasso} />{/if}
  </div>
</div>
