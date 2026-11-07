// Podgląd arkuszy (XLSX/XLSM/XLS/CSV/TSV): nazwy kolumn, szukanie we wszystkich arkuszach, szerokości kolumn
// i układ siatki liczony arytmetycznie (w DOM tylko widoczne wiersze i kolumny).
import type { EntryView } from '../types';
import { MAX_MATCHES } from './find';

/** Rozszerzenia czytane jako arkusz (zgodnie z `sheets.py`). */
export const SHEET_EXTS: readonly string[] = ['xlsx', 'xlsm', 'xls', 'csv', 'tsv'];

export function isSheet(e: EntryView): boolean {
  return e.kind === 'file' && SHEET_EXTS.includes(e.ext.toLowerCase());
}

/** Kolumna jak w Excelu: 0 → A, 25 → Z, 26 → AA. */
export function colName(i: number): string {
  let out = '';
  for (let n = i + 1; n > 0; n = Math.floor((n - 1) / 26)) out = String.fromCharCode(65 + ((n - 1) % 26)) + out;
  return out;
}

export type SheetHit = { sheet: number; row: number; col: number };

/** Komórki z trafieniem (jedno na komórkę), arkusz po arkuszu; zapytanie dosłowne, bez wielkości liter. */
export function findInBook(sheets: readonly { rows: string[][] }[], query: string, whole = false,
  limit = MAX_MATCHES): SheetHit[] {
  if (!query) return [];
  const literal = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const word = '[\\p{L}\\p{N}_]';
  const re = new RegExp(whole ? `(?<!${word})${literal}(?!${word})` : literal, 'iu');
  const out: SheetHit[] = [];
  for (let s = 0; s < sheets.length; s++) {
    const rows = sheets[s].rows;
    for (let r = 0; r < rows.length; r++) {
      const row = rows[r];
      for (let c = 0; c < row.length; c++) {
        if (row[c] && re.test(row[c])) {
          out.push({ sheet: s, row: r, col: c });
          if (out.length >= limit) return out;
        }
      }
    }
  }
  return out;
}

/** Arkusz jako tekst z tabulatorami — wklejony do Excela lub Arkuszy Google rozkłada się na komórki. */
export function toTsv(rows: readonly string[][]): string {
  const cell = (v: string) => (/[\t\r\n"]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return rows.map((r) => r.map(cell).join('\t')).join('\r\n');
}

export const CELL = { min: 56, max: 320, pad: 18, char: 7.4 } as const;
/** Tyle wierszy wystarczy, żeby ocenić szerokość kolumny; dalsze nie zmieniają jej w praktyce. */
const WIDTH_SAMPLE = 300;

/** Szerokości kolumn z najdłuższej wartości (pierwsza linia komórki) w próbce wierszy, w granicach `CELL`. */
export function columnWidths(rows: readonly string[][]): number[] {
  const longest: number[] = [];
  for (const row of rows.slice(0, WIDTH_SAMPLE)) {
    for (let c = 0; c < row.length; c++) {
      const v = row[c];
      if (!v) continue;
      const nl = v.indexOf('\n');
      const n = nl < 0 ? v.length : nl;
      if (n > (longest[c] ?? 0)) longest[c] = n;
    }
  }
  const cols = rows.reduce((m, r) => Math.max(m, r.length), 0);
  return Array.from({ length: cols }, (_, c) =>
    Math.round(Math.min(CELL.max, Math.max(CELL.min, (longest[c] ?? 0) * CELL.char + CELL.pad))));
}

/** Lewe krawędzie kolumn i całkowita szerokość (ostatni element). */
export function offsets(widths: readonly number[]): number[] {
  const out = [0];
  for (const w of widths) out.push(out[out.length - 1] + w);
  return out;
}

/** Kolumny widoczne w poziomie `[left, left+width)` z zapasem jednej: `[start, end)`. */
export function colRange(edges: readonly number[], left: number, width: number): [number, number] {
  const count = edges.length - 1;
  let lo = 0;
  let hi = count;
  while (lo < hi) {  // pierwsza kolumna, której prawa krawędź jest za `left`
    const mid = (lo + hi) >> 1;
    if (edges[mid + 1] <= left) lo = mid + 1;
    else hi = mid;
  }
  let end = lo;
  while (end < count && edges[end] < left + width) end++;
  return [Math.max(0, lo - 1), Math.min(count, end + 1)];
}
