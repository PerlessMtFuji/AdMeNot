import { type Bridge, isApiError } from '../bridge';
import type { AppState } from '../state.svelte';
import type { ApiError, EntryView, ExplorerListView, ExplorerOpenView, PlaceView } from '../types';
import { days, defaultView, type ExplorerFilter, type ExplorerView, parentPath, placeAt, ROOT, SORT_START, type SortKey, visible } from './logic';
import { ExplorerState } from './state.svelte';

/** Jak `EXPLORER_RECENT_MAX` w ustawieniach mostu. */
const RECENT_MAX = 8;

export interface SelectMods {
  ctrl?: boolean;
  shift?: boolean;
}

/** Eksplorator plików telefonu: sesja mostu (`explorer_*`), nawigacja i zaznaczenie. Ekran aplikacji
 *  przełącza na `explorer` po udanym otwarciu i z powrotem na „Połącz” po zamknięciu. */
export class ExplorerController {
  readonly state = new ExplorerState();
  private seq = 0;  // odczyt folderu: liczy się tylko odpowiedź na ostatnie przejście
  private opening = false;
  private earlyPlaces: PlaceView[] | null = null;  // liczby Miejsc, które przyszły przed wynikiem otwarcia

  constructor(private readonly app: AppState, private readonly bridge: Bridge) {}

  private get api() {
    return this.bridge.api;
  }

  /** Wpisy bieżącego folderu w kolejności na ekranie (sortowanie, filtr typu, szukanie). */
  get items(): EntryView[] {
    const s = this.state;
    return visible(s.entries, s.filter, s.query, s.sort);
  }

  subscribe(): void {
    const on = this.bridge.on;
    const s = this.state;
    const mine = (d: { serial: string }) => s.open && d.serial === s.serial;
    on('explorer:places', (d) => {
      if (s.open) s.places = d.places;
      else if (this.opening) this.earlyPlaces = d.places;
    });
    on('explorer:offline', (d) => { if (mine(d)) s.offline = true; });
    on('explorer:online', (d) => {
      if (!mine(d)) return;
      s.offline = false;
      void this.refresh();
    });
    on('explorer:closed', (d) => {
      if (!mine(d)) return;
      this.leave();  // most już zamknął sesję: bez `explorer_close`
      s.notice = d.reason;
    });
    on('explorer:task', (d) => {
      if (!s.open) return;
      const i = s.tasks.findIndex((x) => x.id === d.task.id);
      s.tasks = i < 0 ? [...s.tasks, d.task] : s.tasks.map((x, j) => (j === i ? d.task : x));
    });
  }

  /** „Pliki” na „Połącz”. Zajęty telefon (`explorer_busy`) — baner na „Połącz”, ekran zostaje. */
  async open(serial: string): Promise<void> {
    const s = this.state;
    const app = this.app;
    s.notice = null;
    this.opening = true;
    this.earlyPlaces = null;
    let r: ExplorerOpenView | ApiError;
    try {
      r = await this.api.explorer_open(serial);
    } catch (e) {
      r = { error: { key: 'internal', message: String(e) } };
    } finally {
      this.opening = false;
    }
    if (isApiError(r)) {
      if (r.error.key === 'explorer_busy') s.notice = 'busy';
      else app.error = r.error;
      return;
    }
    this.reset();
    Object.assign(s, {
      open: true, serial, device: r.device, places: this.earlyPlaces ?? r.places, media: r.media,
      leftovers: r.leftovers, dest: app.settings.explorer_dest ?? null, recent: [...(app.settings.explorer_recent ?? [])],
    });
    this.earlyPlaces = null;
    app.screen = 'explorer';
    await this.go(s.places[0]?.path ?? ROOT);
  }

  /** „Wróć”: most zwalnia telefon, ekran wraca na „Połącz”. */
  async close(): Promise<void> {
    const wasOpen = this.state.open;
    this.leave();
    if (!wasOpen) return;
    try {
      await this.api.explorer_close();
    } catch {
      // okno i tak wraca na „Połącz”; most zamyka sesję także przy wyjściu z programu
    }
  }

  async go(path: string, refresh = false): Promise<void> {
    const s = this.state;
    if (!s.open) return;
    const seq = ++this.seq;
    s.loading = true;
    let r: ExplorerListView | ApiError;
    try {
      r = await this.api.explorer_list(path);
    } catch (e) {
      r = { error: { key: 'internal', message: String(e) } };
    }
    if (seq !== this.seq || !s.open) return;
    s.loading = false;
    if (isApiError(r)) {
      if (r.error.key === 'explorer_not_open') {  // sesji już nie ma (np. zamknięta przy wyjściu z uśpienia)
        this.leave();
        this.app.error = r.error;
      } else {
        s.error = r.error;  // poprzednia zawartość zostaje, baner mówi, co się nie udało
      }
      return;
    }
    const same = refresh && r.path === s.path;
    Object.assign(s, { error: null, path: r.path, crumbs: r.crumbs, entries: r.entries, locked: r.locked,
      skipped: r.skipped });
    if (same) {
      const present = new Set(r.entries.map((e) => e.path));
      for (const p of [...s.selected]) if (!present.has(p)) s.selected.delete(p);
      if (s.anchor && !present.has(s.anchor)) s.anchor = null;
    } else {
      s.selected.clear();
      Object.assign(s, { anchor: null, query: '', preview: null,
        view: defaultView(placeAt(s.places, r.path)?.key ?? null) });
    }
    if (!r.locked && r.path !== ROOT) s.recent = [r.path, ...s.recent.filter((p) => p !== r.path)].slice(0, RECENT_MAX);
  }

  async up(): Promise<void> {
    const parent = parentPath(this.state.path);
    if (parent) await this.go(parent);
  }

  refresh(): Promise<void> {
    return this.go(this.state.path, true);
  }

  setView(view: ExplorerView): void {
    this.state.view = view;
  }

  /** Ta sama kolumna odwraca kierunek; nowa zaczyna od `SORT_START`. */
  setSort(key: SortKey): void {
    const s = this.state;
    s.sort = s.sort.key === key ? { key, dir: s.sort.dir === 1 ? -1 : 1 } : { key, dir: SORT_START[key] };
  }

  setFilter(filter: ExplorerFilter): void {
    this.state.filter = filter;
    this.keepVisibleSelection();
  }

  setQuery(query: string): void {
    this.state.query = query;
    this.keepVisibleSelection();
  }

  /** Zaznaczenie jak w Windows: klik — tylko ten, Ctrl — przełącza, Shift — zakres od kotwicy
   *  (z Ctrl dopisany do zaznaczenia). */
  select(path: string, mods: SelectMods = {}): void {
    const s = this.state;
    const sel = s.selected;
    if (mods.shift && s.anchor) {
      const order = this.items.map((e) => e.path);
      const a = order.indexOf(s.anchor);
      const b = order.indexOf(path);
      if (a >= 0 && b >= 0) {
        if (!mods.ctrl) sel.clear();
        for (const p of order.slice(Math.min(a, b), Math.max(a, b) + 1)) sel.add(p);
        return;
      }
    }
    if (mods.ctrl) {
      if (!sel.delete(path)) sel.add(path);
    } else {
      sel.clear();
      sel.add(path);
    }
    s.anchor = path;
  }

  /** Klik w nagłówek dnia: zaznacza pliki tego dnia, a gdy już są zaznaczone — odznacza. */
  selectDay(day: string): void {
    const sel = this.state.selected;
    const group = days(this.items.filter((e) => e.kind === 'file'), new Date()).find((g) => g.key === day);
    if (!group) return;
    const all = group.items.every((e) => sel.has(e.path));
    for (const e of group.items) {
      if (all) sel.delete(e.path);
      else sel.add(e.path);
    }
  }

  /** Zaznaczanie prostokątem; `additive` (Ctrl) — dopisuje do dotychczasowego. */
  selectRect(paths: string[], additive: boolean): void {
    const sel = this.state.selected;
    if (!additive) sel.clear();
    for (const p of paths) sel.add(p);
  }

  selectAll(): void {
    for (const e of this.items) this.state.selected.add(e.path);
  }

  clear(): void {
    this.state.selected.clear();
    this.state.anchor = null;
  }

  dismissLeftovers(): void {
    this.state.leftovers = 0;
  }

  dismissNotice(): void {
    this.state.notice = null;
  }

  /** Zaznaczone, a niewidoczne po zmianie filtra lub szukania, nie mogą trafić do kopii. */
  private keepVisibleSelection(): void {
    const shown = new Set(this.items.map((e) => e.path));
    for (const p of [...this.state.selected]) if (!shown.has(p)) this.state.selected.delete(p);
  }

  /** Koniec sesji po stronie UI: stan od nowa, ekran eksploratora wraca na „Połącz”. */
  private leave(): void {
    // „Ostatnio” zapisuje most; kopia w ustawieniach okna pokaże je przy następnym otwarciu
    if (this.state.open) this.app.settings = { ...this.app.settings, explorer_recent: [...this.state.recent] };
    this.reset();
    if (this.app.screen === 'explorer') this.app.screen = 'main';
  }

  private reset(): void {
    const s = this.state;
    this.seq += 1;  // spóźniona lista poprzedniej sesji nie trafi na ekran
    s.selected.clear();
    Object.assign(s, {
      open: false, serial: null, device: null, places: [], recent: [], path: ROOT, crumbs: [], entries: [],
      locked: false, skipped: 0, loading: false, view: 'list', filter: 'all', query: '', anchor: null, tasks: [],
      offline: false, preview: null, dest: null, leftovers: 0, media: '', error: null,
    });
  }
}
