// Logika eksploratora plików bez stanu: typy plików, sortowanie, filtr, grupowanie po dniach.
import { i18n, t } from '../i18n/index.svelte';
import type { EntryView, FileKind, PlaceView } from '../types';

export const ROOT = '/sdcard';

export type ExplorerView = 'grid' | 'list';
export type ExplorerFilter = 'all' | 'image' | 'video' | 'doc' | 'apk';
export type SortKey = 'name' | 'date' | 'size';
export interface SortSpec {
  key: SortKey;
  dir: 1 | -1;
}
export interface DayGroup {
  key: string;
  label: string;
  items: EntryView[];
}

export const FILTERS: readonly ExplorerFilter[] = ['all', 'image', 'video', 'doc', 'apk'];
/** Pierwsze kliknięcie kolumny: nazwa rosnąco, data i rozmiar — najnowsze/największe na górze. */
export const SORT_START: Record<SortKey, 1 | -1> = { name: 1, date: -1, size: -1 };

// Te same listy co `explorer_present._TYPES` (most daje `type` dla plików telefonu; tu — dla plików z komputera).
const TYPES: [FileKind, string[]][] = [
  ['image', ['jpg', 'jpeg', 'jpe', 'png', 'webp', 'gif', 'bmp', 'heic', 'heif']],
  ['video', ['mp4', 'm4v', 'mkv', 'webm', '3gp', 'mov', 'avi', 'ts']],
  ['audio', ['mp3', 'm4a', 'aac', 'ogg', 'oga', 'opus', 'wav', 'flac', 'amr', 'awb', 'mid', 'midi']],
  ['text', ['txt', 'log', 'json', 'xml', 'csv', 'md', 'ini', 'cfg', 'conf', 'vcf', 'srt', 'html', 'htm', 'yml', 'yaml']],
  ['apk', ['apk', 'apks', 'xapk']],
  ['doc', ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp', 'rtf', 'epub']],
];
const GRID_PLACES: readonly PlaceView['key'][] = ['camera', 'screenshots', 'movies', 'whatsapp'];
// Filtr „Dokumenty” obejmuje też pliki tekstowe (notatki, logi, CSV).
const FILTER_KINDS: Record<Exclude<ExplorerFilter, 'all'>, readonly FileKind[]> = {
  image: ['image'], video: ['video'], doc: ['doc', 'text'], apk: ['apk'],
};

export function extension(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : '';
}

export function fileType(name: string): FileKind {
  const ext = extension(name);
  return TYPES.find(([, exts]) => exts.includes(ext))?.[0] ?? 'other';
}

export function defaultView(place: string | null): ExplorerView {
  return place !== null && (GRID_PLACES as readonly string[]).includes(place) ? 'grid' : 'list';
}

/** Miejsce, którego folderem jest dokładnie `path` (nie podfolder). */
export function placeAt(places: PlaceView[], path: string): PlaceView | null {
  return places.find((p) => p.path === path) ?? null;
}

export function parentPath(path: string): string | null {
  if (path === ROOT || !path.startsWith(`${ROOT}/`)) return null;
  return path.slice(0, path.lastIndexOf('/'));
}

const collator = () => new Intl.Collator(i18n.lang, { numeric: true, sensitivity: 'base' });

/** Wpisy do pokazania: foldery zawsze na górze (filtr typu dotyczy plików — foldery zostają do
 *  nawigacji), szukanie po nazwie i ludzkiej nazwie folderu. Rozmiar folderu nic nie mówi: foldery
 *  przy sortowaniu po rozmiarze idą po nazwie. */
export function visible(entries: EntryView[], filter: ExplorerFilter, query: string, sort: SortSpec): EntryView[] {
  const q = query.trim().toLocaleLowerCase();
  const kinds = filter === 'all' ? null : FILTER_KINDS[filter];
  const cmp = collator();
  const byName = (a: EntryView, b: EntryView) => cmp.compare(a.label ?? a.name, b.label ?? b.name);
  // Kolumna sortowania w wybranym kierunku; równe wartości (i foldery przy rozmiarze) zawsze A→Z.
  const key = (a: EntryView, b: EntryView): number => {
    if (sort.key === 'name') return byName(a, b) * sort.dir;
    const primary = sort.key === 'date' ? a.mtime - b.mtime : a.kind === 'file' ? a.size - b.size : 0;
    return primary * sort.dir || byName(a, b);
  };
  return entries
    .filter((e) => (!kinds || e.kind === 'dir' || kinds.includes(e.type))
      && (!q || e.name.toLocaleLowerCase().includes(q) || !!e.label?.toLocaleLowerCase().includes(q)))
    .sort((a, b) => (a.kind === b.kind ? key(a, b) : a.kind === 'dir' ? -1 : 1));
}

function localDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Etykieta dnia: „Dziś · 2 listopada”, „Wczoraj”, dalej data (z rokiem, gdy inny niż bieżący). */
export function dayLabel(date: Date, now: Date): string {
  const locale = i18n.lang === 'pl' ? 'pl-PL' : 'en-GB';
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  const long = date.toLocaleDateString(locale, { day: 'numeric', month: 'long',
    ...(date.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}) });
  if (localDay(date) === localDay(now)) return t('explorer.day.today', { date: long });
  if (localDay(date) === localDay(yesterday)) return t('explorer.day.yesterday');
  return long;
}

/** Grupy dni (czas lokalny) w kolejności pierwszego wystąpienia; w grupie kolejność wejścia. */
export function days(entries: EntryView[], now: Date): DayGroup[] {
  const groups = new Map<string, DayGroup>();
  for (const e of entries) {
    const date = new Date(e.mtime * 1000);
    const key = localDay(date);
    let group = groups.get(key);
    if (!group) {
      group = { key, label: dayLabel(date, now), items: [] };
      groups.set(key, group);
    }
    group.items.push(e);
  }
  return [...groups.values()];
}

/** Krótka data na liście: „dziś, 14:30”, „wczoraj, 9:05”, „12 paź”, „3 wrz 2025”. */
export function shortDate(mtime: number, now: Date): string {
  const locale = i18n.lang === 'pl' ? 'pl-PL' : 'en-GB';
  const date = new Date(mtime * 1000);
  const time = date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (localDay(date) === localDay(now)) return t('explorer.date.today', { time });
  if (localDay(date) === localDay(yesterday)) return t('explorer.date.yesterday', { time });
  return date.toLocaleDateString(locale, { day: 'numeric', month: 'short',
    ...(date.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}) });
}

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];

/** Rozmiar pliku: do 10 jednostek z jednym miejscem po przecinku („1,5 KB”), wyżej w całości. */
export function formatBytes(bytes: number, lang: string): string {
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit > 0 && value < 10 ? 1 : 0;
  const number = new Intl.NumberFormat(lang === 'pl' ? 'pl-PL' : 'en-US',
    { maximumFractionDigits: digits }).format(value);
  return `${number} ${UNITS[unit]}`;
}

/** Czas trwania „m:ss” albo „g:mm:ss”. */
export function clock(seconds: number): string {
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60));
  const ss = String(s % 60).padStart(2, '0');
  return h ? `${h}:${mm.padStart(2, '0')}:${ss}` : `${mm}:${ss}`;
}
