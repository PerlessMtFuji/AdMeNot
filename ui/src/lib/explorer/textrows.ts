// Wiersze podglądu tekstu: w DOM są tylko widoczne, więc układ i kolorowanie liczymy na przesunięciach w tekście.
// 350 KB JSON-a to było 77 tys. węzłów i kilka sekund, a 2 MB wywracało okno.
import type { Match } from './find';
import type { Token } from './highlight';

/** Najdłuższy wiersz na ekranie: zminifikowany JSON to jedna linia, której nie da się pokazać w jednym kawałku. */
export const ROW_CHARS = 2000;

export interface TextRows {
  /** Początek każdego wiersza ekranu w tekście; `starts[n]` — koniec tekstu. */
  starts: Int32Array;
  /** Koniec treści wiersza (bez `\n`). */
  ends: Int32Array;
  /** Numer linii pliku; 0 — ciąg dalszy podzielonej linii. */
  lines: Int32Array;
  count: number;
  /** Liczba linii pliku. */
  total: number;
  /** Najszerszy wiersz w znakach (szerokość przewijania). */
  width: number;
}

/** Podział tekstu na wiersze ekranu; końcowa pusta linia po ostatnim `\n` się nie liczy (jak w edytorach). */
export function textRows(text: string, limit = ROW_CHARS): TextRows {
  let capacity = 1024;
  let starts = new Int32Array(capacity + 1);
  let ends = new Int32Array(capacity);
  let lines = new Int32Array(capacity);
  let count = 0;
  let width = 0;
  let total = 0;
  const push = (start: number, end: number, line: number) => {
    if (count === capacity) {
      capacity *= 2;
      const grow = <T extends Int32Array>(old: T, size: number) => {
        const next = new Int32Array(size);
        next.set(old);
        return next;
      };
      starts = grow(starts, capacity + 1);
      ends = grow(ends, capacity);
      lines = grow(lines, capacity);
    }
    starts[count] = start;
    ends[count] = end;
    lines[count] = line;
    count += 1;
    width = Math.max(width, end - start);
  };
  let at = 0;
  while (at < text.length) {
    let stop = text.indexOf('\n', at);
    if (stop < 0) stop = text.length;
    total += 1;
    let from = at;
    let first = true;
    do {
      const to = Math.min(stop, from + limit);
      push(from, to, first ? total : 0);
      first = false;
      from = to;
    } while (from < stop);
    at = stop + 1;
  }
  starts[count] = text.length;
  return { starts, ends, lines, count, total, width };
}

/** Wiersz ekranu z danym miejscem w tekście. */
export function rowAt(rows: TextRows, offset: number): number {
  let lo = 0;
  let hi = rows.count - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (rows.starts[mid] <= offset) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** Początki tokenów w tekście (tokeny sklejone dają cały tekst). */
export function tokenStarts(tokens: readonly Token[]): Int32Array {
  const out = new Int32Array(tokens.length + 1);
  let at = 0;
  tokens.forEach((token, i) => {
    out[i] = at;
    at += token.text.length;
  });
  out[tokens.length] = at;
  return out;
}

function tokenAt(starts: Int32Array, offset: number): number {
  let lo = 0;
  let hi = starts.length - 2;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (starts[mid] <= offset) lo = mid;
    else hi = mid - 1;
  }
  return Math.max(0, lo);
}

export interface Segment {
  text: string;
  cls: string;
  /** Numer trafienia wyszukiwania albo -1. */
  hit: number;
}

/** Kawałki wierszy `[from, to)` z kolorami i trafieniami, wiersz po wierszu. `marks` — trafienia, których numery
 *  zaczynają się od `markFrom`; każdy wiersz kończy `\n`. */
export function rowSegments(text: string, rows: TextRows, tokens: readonly Token[], starts: Int32Array, from: number, to: number,
  marks: readonly Match[], markFrom: number): Segment[] {
  const out: Segment[] = [];
  if (from >= to) return out;
  let token = tokenAt(starts, rows.starts[from]);
  let hit = 0;
  for (let row = from; row < to; row++) {
    let at = rows.starts[row];
    const end = rows.ends[row];
    while (at < end) {
      while (token < tokens.length - 1 && starts[token + 1] <= at) token++;
      while (hit < marks.length && marks[hit].end <= at) hit++;
      const match = marks[hit];
      const inside = !!match && match.start <= at;
      const stop = Math.min(end, starts[token + 1], match ? (inside ? match.end : match.start) : end);
      out.push({ text: text.slice(at, stop), cls: tokens[token]?.cls ?? '', hit: inside ? markFrom + hit : -1 });
      at = stop;
    }
    out.push({ text: '\n', cls: '', hit: -1 });
  }
  return out;
}
