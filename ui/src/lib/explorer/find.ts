export type Match = { start: number; end: number };

/** Podgląd tekstu kończy się tu: większy plik zjada pamięć okna i zamraża je (40 MB to było 2,3 GB). */
export const MAX_TEXT = 16 * 1024 * 1024;
/** Tyle trafień liczymy; więcej nikt nie przejdzie klawiszem, a lista też kosztuje. */
export const MAX_MATCHES = 100_000;
/** Podświetlone są tylko trafienia wokół bieżącego: tysiące znaczników w DOM zacinają okno. */
export const MARK_WINDOW = 200;

/** Dosłowne szukanie Unicode; zapytanie nigdy nie jest interpretowane jako regex/HTML. */
export function findMatches(text: string, query: string, whole = false, limit = MAX_MATCHES): Match[] {
  if (!query) return [];
  const literal = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const word = '[\\p{L}\\p{N}_]';
  const re = new RegExp(whole ? `(?<!${word})${literal}(?!${word})` : literal, 'giu');
  const out: Match[] = [];
  for (const m of text.matchAll(re)) {
    out.push({ start: m.index, end: m.index + m[0].length });
    if (out.length >= limit) break;
  }
  return out;
}
