import { getContext, setContext } from 'svelte';

const KEY = 'settingsSearch';

export type SettingsSearch = { query: string; matches(q: string, text: string): boolean };

/** Bez diakrytyków i wielkości liter; `ł` nie rozkłada się w NFD, więc osobno. */
function fold(s: string): string {
  return s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ł/gi, 'l').toLowerCase();
}

export function matches(q: string, text: string): boolean {
  const needle = fold(q).trim();
  return needle === '' || fold(text).includes(needle);
}

export function createSettingsSearch(): SettingsSearch {
  let query = $state('');
  const search: SettingsSearch = {
    get query() { return query; },
    set query(v: string) { query = v; },
    matches,
  };
  setContext(KEY, search);
  return search;
}

const FALLBACK: SettingsSearch = { query: '', matches };

export function useSettingsSearch(): SettingsSearch {
  return getContext<SettingsSearch | undefined>(KEY) ?? FALLBACK;
}

/** Grupa dowiaduje się od wierszy, czy którykolwiek jest widoczny. */
export type GroupRegistry = { rows: Map<string, string> };
export const GROUP_KEY = 'settingsGroup';
