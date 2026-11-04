import { SvelteSet } from 'svelte/reactivity';
import type { ApiErrorBody, CrumbView, EntryView, ExplorerProblem, PhoneCard, PlaceView, TaskView } from '../types';
import { type ExplorerFilter, type ExplorerView, ROOT, type SortSpec } from './logic';

/** Komunikat na „Połącz” po nieudanym otwarciu albo zamknięciu eksploratora przez most. */
export type ExplorerNotice = 'busy' | 'other_phone' | 'switched';

/** Stan eksploratora plików: otwarta sesja (most trzyma blokadę telefonu), bieżący folder i zaznaczenie. */
export class ExplorerState {
  open = $state(false);
  /** Telefon otwartej sesji (zdarzenia `explorer:*` innego telefonu są pomijane). */
  serial = $state<string | null>(null);
  device = $state<PhoneCard | null>(null);
  places = $state<PlaceView[]>([]);
  /** „Ostatnio” — ostatnio odwiedzone foldery, najnowszy pierwszy (most zapisuje je w ustawieniach). */
  recent = $state<string[]>([]);
  path = $state(ROOT);
  crumbs = $state<CrumbView[]>([]);
  entries = $state<EntryView[]>([]);
  /** Cały bieżący folder bez dostępu (kłódka zamiast listy). */
  locked = $state(false);
  skipped = $state(0);
  /** Trwa odczyt folderu (`explorer_list`). */
  loading = $state(false);
  view = $state<ExplorerView>('list');
  sort = $state<SortSpec>({ key: 'date', dir: -1 });
  filter = $state<ExplorerFilter>('all');
  query = $state('');
  selected = new SvelteSet<string>();
  /** Kotwica zaznaczenia zakresem (Shift+klik). */
  anchor = $state<string | null>(null);
  /** Zadania kolejki; raw — zdarzenia podmieniają je w całości, bez głębokich proxy. */
  tasks = $state.raw<TaskView[]>([]);
  /** Telefon zniknął z listy — most czeka na jego powrót (`explorer:online`). */
  offline = $state(false);
  preview = $state<string | null>(null);
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
  /** Wpisy, które pojawiły się przy ostatnim odświeżeniu folderu (wskakują, `pop-in`). */
  fresh = new SvelteSet<string>();
  /** Ctrl+V bez plików w schowku Windows — podpowiedź do zamknięcia. */
  clipboardEmpty = $state(false);
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
