// Logika eksploratora plików bez stanu: typy plików, sortowanie, filtr, grupowanie po dniach.
import { i18n, t, tp } from '../i18n/index.svelte';
import type { EntryView, FolderStatsView, FileKind, PlaceView } from '../types';

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
/** Wybór sortowania w siatce (lista sortuje nagłówkami kolumn). */
export const SORTS = [['date', -1], ['date', 1], ['name', 1], ['name', -1], ['size', -1], ['size', 1]] as const;
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

// Formatery Intl tworzy się długo (dziesiątki µs), a lista i nagłówki dni wołają je przy każdym wierszu.
const formatters = new Map<string, Intl.DateTimeFormat | Intl.NumberFormat | Intl.Collator>();
function cached<T extends Intl.DateTimeFormat | Intl.NumberFormat | Intl.Collator>(key: string, make: () => T): T {
  let value = formatters.get(key);
  if (!value) formatters.set(key, value = make());
  return value as T;
}
const dateFormat = (locale: string, options: Intl.DateTimeFormatOptions) =>
  cached(`d:${locale}:${JSON.stringify(options)}`, () => new Intl.DateTimeFormat(locale, options));

/** Sortowanie: foldery zawsze na górze. Po rozmiarze foldery idą według policzonej zawartości (`dirs`); jeszcze
 *  niepoliczone — na końcu folderów, po nazwie. `lang` — język porównywania nazw. */
export function sortEntries(entries: readonly EntryView[], sort: SortSpec, lang: string = i18n.lang,
  dirs?: Readonly<Record<string, FolderStatsView>>): EntryView[] {
  const cmp = cached(`c:${lang}`, () => new Intl.Collator(lang, { numeric: true, sensitivity: 'base' }));
  const byName = (a: EntryView, b: EntryView) => cmp.compare(a.label ?? a.name, b.label ?? b.name);
  // Kolumna sortowania w wybranym kierunku; równe wartości (i foldery przy rozmiarze) zawsze A→Z.
  const key = (a: EntryView, b: EntryView): number => {
    if (sort.key === 'name') return byName(a, b) * sort.dir;
    if (sort.key === 'size' && a.kind === 'dir') {
      const sa = folderBytes(dirs?.[a.path]);
      const sb = folderBytes(dirs?.[b.path]);
      if (sa === null || sb === null) return sa === sb ? byName(a, b) : sa === null ? 1 : -1;
      return (sa - sb) * sort.dir || byName(a, b);
    }
    const primary = sort.key === 'date' ? a.mtime - b.mtime : a.kind === 'file' ? a.size - b.size : 0;
    return primary * sort.dir || byName(a, b);
  };
  return [...entries].sort((a, b) => (a.kind === b.kind ? key(a, b) : a.kind === 'dir' ? -1 : 1));
}

/** Nazwy małymi literami: wpis się nie zmienia, a szukanie przechodzi po wszystkich przy każdym klawiszu. */
const lowered = new WeakMap<EntryView, string>();
function searchable(e: EntryView): string {
  let text = lowered.get(e);
  if (text === undefined) {
    text = `${e.name.toLocaleLowerCase()}\n${e.label?.toLocaleLowerCase() ?? ''}`;
    lowered.set(e, text);
  }
  return text;
}

/** Filtr typu dotyczy plików (foldery zostają do nawigacji); szukanie po nazwie i ludzkiej nazwie folderu.
 *  Bez filtra i szukania — ta sama tablica. */
export function filterEntries(entries: EntryView[], filter: ExplorerFilter, query: string): EntryView[] {
  const q = query.trim().toLocaleLowerCase();
  const kinds = filter === 'all' ? null : FILTER_KINDS[filter];
  if (!kinds && !q) return entries;
  return entries.filter((e) => (!kinds || e.kind === 'dir' || kinds.includes(e.type)) && (!q || searchable(e).includes(q)));
}

/** Wpisy do pokazania: `sortEntries` i `filterEntries` razem. */
export function visible(entries: EntryView[], filter: ExplorerFilter, query: string, sort: SortSpec): EntryView[] {
  return filterEntries(sortEntries(entries, sort), filter, query);
}

function localDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Etykieta dnia: „Dziś · 2 listopada”, „Wczoraj”, dalej data (z rokiem, gdy inny niż bieżący). */
export function dayLabel(date: Date, now: Date): string {
  const locale = i18n.lang === 'pl' ? 'pl-PL' : 'en-GB';
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  const long = dateFormat(locale, { day: 'numeric', month: 'long',
    ...(date.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}) }).format(date);
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
  const time = () => dateFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(date);
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (localDay(date) === localDay(now)) return t('explorer.date.today', { time: time() });
  if (localDay(date) === localDay(yesterday)) return t('explorer.date.yesterday', { time: time() });
  return dateFormat(locale, { day: 'numeric', month: 'short',
    ...(date.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}) }).format(date);
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
  const locale = lang === 'pl' ? 'pl-PL' : 'en-US';
  const number = cached(`n:${locale}:${digits}`, () => new Intl.NumberFormat(locale, { maximumFractionDigits: digits })).format(value);
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

const folderBytes = (s: FolderStatsView | undefined): number | null => (s && 'bytes' in s ? s.bytes : null);

/** Opis folderu w kafelku i na liście: liczba plików i rozmiar; `≥` — część podfolderów bez dostępu, `≈` — rozmiar
 *  przybliżony; `hint` — wyjaśnienie znaku w dymku `title`. `null` — jeszcze liczymy. */
export function folderSummary(s: FolderStatsView | undefined, lang: string = i18n.lang):
  { files: string; size: string; hint: string } | null {
  if (!s) return null;
  if (!('bytes' in s)) return { files: t('explorer.folder_stats.failed'), size: '—', hint: t('explorer.folder_stats.failed') };
  if (s.files === 0 && !s.partial) return { files: t('explorer.folder_stats.empty'), size: formatBytes(s.bytes, lang), hint: '' };
  const at = s.partial ? '≥ ' : '';
  const hint = [s.partial ? t('explorer.folder_stats.partial') : '', s.approx ? t('explorer.folder_stats.approx') : '']
    .filter(Boolean).join(' ');
  return { files: at + tp('explorer.gallery.files', s.files), size: at + (s.approx ? '≈ ' : '') + formatBytes(s.bytes, lang), hint };
}
