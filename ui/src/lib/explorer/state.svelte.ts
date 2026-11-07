import { SvelteSet } from 'svelte/reactivity';
import type { ApiErrorBody, CrumbView, EntryView, ExplorerProblem, FolderStatsView, PhoneCard, PlaceView, StorageView, TaskView } from '../types';
import { i18n } from '../i18n/index.svelte';
import { type ExplorerFilter, type ExplorerView, filterEntries, ROOT, sortEntries, type SortSpec } from './logic';

/** Komunikat na „Połącz” po nieudanym otwarciu albo zamknięciu eksploratora przez most. */
export type ExplorerNotice = 'busy' | 'other_phone' | 'switched';

/** Stan eksploratora plików: otwarta sesja (most trzyma blokadę telefonu), bieżący folder i zaznaczenie. */
export class ExplorerState {
  open = $state(false);
  /** Telefon otwartej sesji (zdarzenia `explorer:*` innego telefonu są pomijane). */
  serial = $state<string | null>(null);
  device = $state<PhoneCard | null>(null);
  places = $state<PlaceView[]>([]);
  /** Pamięć telefonu (null: jeszcze nie odczytana albo odczyt się nie udał). */
  storage = $state.raw<StorageView | null>(null);
  /** „Ostatnio” — ostatnio odwiedzone foldery tego telefonu, najnowszy pierwszy (most zapisuje je osobno
   *  dla każdego telefonu i oddaje w `explorer_open`). */
  recent = $state<string[]>([]);
  path = $state(ROOT);
  crumbs = $state<CrumbView[]>([]);
  /** Raw: lista jest podmieniana w całości, a głębokie proxy na tysiącach wpisów kosztowało setki ms na klawisz. */
  entries = $state.raw<EntryView[]>([]);
  /** Cały bieżący folder bez dostępu (kłódka zamiast listy). */
  locked = $state(false);
  skipped = $state(0);
  /** Trwa odczyt folderu (`explorer_list`). */
  loading = $state(false);
  view = $state<ExplorerView>('list');
  /** Podgląd pliku w dymku po najechaniu (ustawienie `explorer_peek`). */
  peek = $state(true);
  sort = $state<SortSpec>({ key: 'date', dir: -1 });
  filter = $state<ExplorerFilter>('all');
  query = $state('');
  /** Liczby plików i rozmiary folderów tej sesji (ścieżka → wynik); raw — zdarzenia podmieniają całość. */
  dirStats = $state.raw<Record<string, FolderStatsView>>({});
  /** Wpisy po sortowaniu: liczone tylko przy zmianie folderu, sortowania albo języka, nie przy każdym klawiszu.
   *  Liczby folderów wchodzą tylko przy sortowaniu po rozmiarze (inaczej każdy policzony folder sortowałby od nowa). */
  sorted = $derived(sortEntries(this.entries, this.sort, i18n.lang, this.sort.key === 'size' ? this.dirStats : undefined));
  /** Wpisy w kolejności na ekranie (sortowanie, filtr typu, szukanie). */
  items = $derived(filterEntries(this.sorted, this.filter, this.query));
  /** Wpis po ścieżce. */
  byPath = $derived(new Map(this.entries.map((e) => [e.path, e])));
  selected = new SvelteSet<string>();
  /** Pierwszy klik mógł być początkiem dwukliku: pasek zaznaczenia jeszcze czeka. */
  barHeld = $state(false);
  /** Pozycja pod kursorem: Spacja otwiera ją bez klikania. */
  hover = $state<string | null>(null);
  /** Lista ma się przewinąć do tej pozycji („Pokaż” po wgraniu). */
  reveal = $state<string | null>(null);
  /** Kotwica zaznaczenia zakresem (Shift+klik). */
  anchor = $state<string | null>(null);
  /** Zadania kolejki; raw — zdarzenia podmieniają je w całości, bez głębokich proxy. */
  tasks = $state.raw<TaskView[]>([]);
  /** Telefon zniknął z listy — most czeka na jego powrót (`explorer:online`). */
  offline = $state(false);
  /** Ścieżka pliku w oknie podglądu. */
  preview = $state<string | null>(null);
  /** Utwór w odtwarzaczu (gra dalej po zamknięciu podglądu, w mini-odtwarzaczu). */
  playing = $state<PlayingTrack | null>(null);
  /** Lista odtwarzania zapamiętana przy starcie utworu (kolejność z ekranu): ⏭ i auto-przejście idą po niej,
   *  niezależnie od folderu, filtra i szukania oglądanych później. */
  queue = $state.raw<PlayingTrack[]>([]);
  /** Utwór się nie wczytał albo nie da się go odtworzyć. */
  playError = $state(false);
  /** Folder docelowy kopii na komputerze (zapamiętany przez most). */
  dest = $state<string | null>(null);
  /** Ile plików tymczasowych z poprzednich otwarć most usunął z telefonu (baner do zamknięcia). */
  leftovers = $state(0);
  /** Adres lokalnego serwera mediów. */
  media = $state('');
  /** Błąd ostatniego odczytu folderu — baner nad listą (poprzednia zawartość zostaje). */
  error = $state<ApiErrorBody | null>(null);
  /** Baner na „Połącz”: telefon zajęty albo eksplorator zamknięty przez most. */
  notice = $state<ExplorerNotice | null>(null);
  /** Problemy planu zadania — nic nie wystartowało, okno mówi dlaczego. */
  problems = $state<ExplorerProblems | null>(null);
  /** Strefa upuszczania: przeciąganie plików nad oknem (`count` — liczba przeciąganych pozycji, jeśli znana)
   *  albo upuszczone pliki w trakcie planowania wgrania (`bytes` z mostu). */
  drop = $state<DropInfo | null>(null);
  /** Trwa planowanie kopii lub wgrania (przyciski nie startują drugiego zadania). */
  starting = $state(false);
  /** Stały folder docelowy jest niedostępny (np. odłączony pendrive) — baner, kopia pyta o inny folder. */
  destMissing = $state(false);
  /** Wpisy, które pojawiły się przy ostatnim odświeżeniu folderu (wskakują, `pop-in`). */
  fresh = new SvelteSet<string>();
  /** Ctrl+V bez plików w schowku Windows — podpowiedź do zamknięcia. */
  clipboardEmpty = $state(false);
  /** Wyjście z eksploratora przy trwających zadaniach: ile zadań przepadnie (0 — okno pytania zamknięte). */
  leaveAsk = $state(0);
}

export interface PlayingTrack {
  path: string;
  title: string;
  /** Okładka (adres miniatury) albo null — wtedy kolorowy kafel. */
  cover: string | null;
  url: string;
}

export interface ExplorerProblems {
  kind: TaskView['kind'];
  list: ExplorerProblem[];
}

export interface DropInfo {
  count: number | null;
  bytes: number | null;
  dropped: boolean;
}
