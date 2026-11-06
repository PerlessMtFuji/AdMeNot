export type Match = { start: number; end: number };

/** Dosłowne szukanie Unicode; zapytanie nigdy nie jest interpretowane jako regex/HTML. */
export function findMatches(text: string, query: string, whole = false): Match[] {
  if (!query) return [];
  const literal = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const word = '[\\p{L}\\p{N}_]';
  const re = new RegExp(whole ? `(?<!${word})${literal}(?!${word})` : literal, 'giu');
  return Array.from(text.matchAll(re), (m) => ({ start: m.index!, end: m.index! + m[0].length }));
}
