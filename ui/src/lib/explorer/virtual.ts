// Wirtualizacja widoków eksploratora: w DOM tylko widoczne wiersze ± OVERSCAN (lista i siatka galerii).
// Układ liczony arytmetycznie, bez mierzenia elementów — ten sam układ służy do zaznaczania prostokątem
// i do strzałek, także dla kafli, których akurat nie ma w DOM.
import type { EntryView } from '../types';
import { observeSize } from '../resize';

/** Ile wierszy ponad i pod widocznymi trzymamy w DOM. */
export const OVERSCAN = 2;
/** Rozmiar widoku, gdy przeglądarka jeszcze go nie zmierzyła (i w jsdom, które nie liczy układu). */
export const FALLBACK = { width: 960, height: 720 } as const;
/** Siatka galerii: najmniejszy kafel, odstęp, wysokość nagłówka dnia. */
export const GRID = { min: 124, gap: 8, header: 44 } as const;

export interface Viewport {
  top: number;
  width: number;
  height: number;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Wiersze stałej wysokości widoczne w oknie, z zapasem: `[start, end)`. */
export function rowRange(count: number, rowH: number, top: number, height: number): [number, number] {
  const start = Math.max(0, Math.floor(top / rowH) - OVERSCAN);
  const end = Math.min(count, Math.ceil((top + height) / rowH) + OVERSCAN);
  return [start, Math.max(start, end)];
}

export interface GroupIn {
  key: string;
  label: string;
  items: EntryView[];
}

export interface Section extends GroupIn {
  top: number;
  height: number;
  rows: number;
  /** Indeks pierwszego kafla sekcji w kolejności na ekranie. */
  first: number;
}

export interface GridLayout {
  cols: number;
  tile: number;
  /** Wysokość wiersza kafli z odstępem. */
  rowH: number;
  sections: Section[];
  height: number;
  /** Wszystkie kafle w kolejności na ekranie (sekcja po sekcji). */
  order: EntryView[];
}

export function gridLayout(groups: GroupIn[], width: number): GridLayout {
  const { min, gap, header } = GRID;
  const cols = Math.max(1, Math.floor((width + gap) / (min + gap)));
  const tile = Math.max(1, (width - gap * (cols - 1)) / cols);
  const rowH = tile + gap;
  let top = 0;
  let first = 0;
  const sections = groups.map((g) => {
    const rows = Math.ceil(g.items.length / cols);
    const s: Section = { ...g, top, height: header + rows * rowH, rows, first };
    top += s.height;
    first += g.items.length;
    return s;
  });
  return { cols, tile, rowH, sections, height: top, order: sections.flatMap((s) => s.items) };
}

/** Położenie kafla `i` sekcji w treści przewijanej. */
export function tileRect(g: GridLayout, s: Section, i: number): Rect {
  const row = Math.floor(i / g.cols);
  const col = i % g.cols;
  return { x: col * (g.tile + GRID.gap), y: s.top + GRID.header + row * g.rowH, w: g.tile, h: g.tile };
}

export interface SectionSlice {
  section: Section;
  /** Kafle sekcji do wyrenderowania: `[from, to)`. */
  from: number;
  to: number;
}

/** Sekcje przecinające okno (± OVERSCAN wierszy) i ich widoczne kafle. */
export function visibleSlices(g: GridLayout, v: Viewport): SectionSlice[] {
  const pad = OVERSCAN * g.rowH;
  const lo = v.top - pad;
  const hi = v.top + v.height + pad;
  const out: SectionSlice[] = [];
  for (const section of g.sections) {
    if (section.top + section.height <= lo || section.top >= hi) continue;
    const body = section.top + GRID.header;
    const r0 = Math.max(0, Math.floor((lo - body) / g.rowH));
    const r1 = Math.min(section.rows, Math.ceil((hi - body) / g.rowH));
    out.push({ section, from: Math.min(section.items.length, r0 * g.cols), to: Math.min(section.items.length, Math.max(r0, r1) * g.cols) });
  }
  return out;
}

/** Kafle naprawdę widoczne w oknie (bez zapasu) — kolejność na ekranie. */
export function inView(g: GridLayout, v: Viewport): EntryView[] {
  const out: EntryView[] = [];
  for (const { section, from, to } of visibleSlices(g, v)) {
    for (let i = from; i < to; i++) {
      const r = tileRect(g, section, i);
      if (r.y + r.h > v.top && r.y < v.top + v.height) out.push(section.items[i]);
    }
  }
  return out;
}

const intersects = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** Ścieżki kafli przeciętych prostokątem (także spoza DOM). */
export function tilesInRect(g: GridLayout, rect: Rect): string[] {
  const out: string[] = [];
  for (const section of g.sections) {
    if (section.top + section.height <= rect.y || section.top >= rect.y + rect.h) continue;
    section.items.forEach((e, i) => {
      if (intersects(tileRect(g, section, i), rect)) out.push(e.path);
    });
  }
  return out;
}

export interface Located {
  section: Section;
  /** Indeks w sekcji. */
  i: number;
}

export function locate(g: GridLayout, index: number): Located | null {
  for (const section of g.sections) {
    if (index < section.first + section.items.length) return index >= section.first ? { section, i: index - section.first } : null;
  }
  return null;
}

/** Strzałki w siatce: lewo/prawo — sąsiedni kafel w kolejności, góra/dół — ten sam słupek w wierszu
 *  wyżej/niżej (także przez granicę dni; krótszy wiersz — jego ostatni kafel). */
export function neighbour(g: GridLayout, index: number, key: string): number | null {
  const total = g.order.length;
  if (key === 'ArrowLeft') return index > 0 ? index - 1 : null;
  if (key === 'ArrowRight') return index < total - 1 ? index + 1 : null;
  if (key !== 'ArrowUp' && key !== 'ArrowDown') return null;
  // wiersze globalnie: [indeks pierwszego kafla, liczba kafli]
  const rows: [number, number][] = [];
  for (const s of g.sections) {
    for (let r = 0; r < s.rows; r++) rows.push([s.first + r * g.cols, Math.min(g.cols, s.items.length - r * g.cols)]);
  }
  const row = rows.findIndex(([start, n]) => index >= start && index < start + n);
  const target = rows[row + (key === 'ArrowDown' ? 1 : -1)];
  if (row < 0 || !target) return null;
  return target[0] + Math.min(index - rows[row][0], target[1] - 1);
}

/** Rozmiar i przewinięcie elementu; zero (niezmierzony, jsdom) — rozmiar zastępczy. */
export function measure(node: HTMLElement): Viewport {
  return { top: node.scrollTop, width: node.clientWidth || FALLBACK.width, height: node.clientHeight || FALLBACK.height };
}

/** Załącznik (`{@attach}`) zgłaszający przewinięcie i zmianę rozmiaru obszaru przewijanego. */
export function viewport(onchange: (v: Viewport) => void) {
  return (node: HTMLElement) => {
    let previous: Viewport | undefined;
    const update = () => {
      const value = measure(node);
      if (previous?.top === value.top && previous.width === value.width && previous.height === value.height) return;
      previous = value;
      onchange(value);
    };
    const stop = observeSize(node, update);
    node.addEventListener('scroll', update, { passive: true });
    return () => {
      stop();
      node.removeEventListener('scroll', update);
    };
  };
}
