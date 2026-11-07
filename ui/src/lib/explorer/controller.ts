import { type Bridge, isApiError } from '../bridge';
import { AudioPlayer } from './audio';
import type { AppState } from '../state.svelte';
import type { ApiError, ApiErrorBody, EntryView, ExplorerListView, ExplorerOpenView, ExplorerStart, PlaceView, TaskView } from '../types';
import { days, defaultView, type ExplorerFilter, type ExplorerView, parentPath, placeAt, ROOT, SORT_START, type SortKey } from './logic';
import { ExplorerState, type PlayingTrack } from './state.svelte';

/** Jak `EXPLORER_RECENT_MAX` w ustawieniach mostu. */
const RECENT_MAX = 8;
/** Jak długo nowe wpisy po odświeżeniu są „świeże” (animacja `pop-in`). */
const FRESH_MS = 700;
/** Zadania, które wyjście z eksploratora anuluje (most zamyka kolejkę razem z sesją). */
/** Windows pozwala wydłużyć dwuklik do ok. 500 ms (domyślny próg też jest tej wielkości). */
const DOUBLE_CLICK_MS = 500;
const FOLDER_MEMORY = 40;
const ACTIVE: ReadonlySet<TaskView['status']> = new Set(['queued', 'running', 'paused', 'waiting']);

/** Ta sama zawartość folderu (adresy mediów wynikają ze ścieżki i są stałe w sesji). */
function sameEntries(a: readonly EntryView[], b: readonly EntryView[]): boolean {
  return a === b || (a.length === b.length && a.every((e, i) => {
    const o = b[i];
    return e.path === o.path && e.size === o.size && e.mtime === o.mtime && e.kind === o.kind && e.label === o.label
      && e.locked === o.locked;
  }));
}

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
  private freshTimer: ReturnType<typeof setTimeout> | undefined;
  private holdTimer: ReturnType<typeof setTimeout> | undefined;
  private lastClick: { path: string; selected: string[]; anchor: string | null } | null = null;
  /** Ostatnia kopia: „Kopiuj bez tych plików” powtarza ją z dodatkowymi wyłączeniami. */
  /** Błąd `explorer_no_dest` ostatniego planu kopii (zamiast banera — kopia pyta o folder). */
  private noDest = false;
  private lastCopy: { paths: string[]; dest: string | null; verify: boolean; exclude: string[]; clear: boolean } | null = null;
  private viewWrites: Promise<unknown> = Promise.resolve();
  private dismissedTasks = new Set<string>();
  /** Odwiedzone foldery: wejście pokazuje je od razu, a świeża lista dochodzi w tle. */
  private folders = new Map<string, ExplorerListView>();
  private player: AudioPlayer | null = null;
  private leaveAnswer: ((ok: boolean) => void) | null = null;  // okno „N zadań zostanie anulowanych”

  constructor(private readonly app: AppState, private readonly bridge: Bridge) {}

  /** Ustawienie „sprawdzaj kopie”: zwykłe „Kopiuj” sprawdza, a menu oferuje kopię bez sprawdzania. */
  get verifyCopies(): boolean {
    return this.app.settings.verify_copies;
  }

  private get api() {
    return this.bridge.api;
  }

  /** Wpisy bieżącego folderu w kolejności na ekranie (sortowanie, filtr typu, szukanie). */
  get items(): EntryView[] {
    return this.state.items;
  }

  subscribe(): void {
    const on = this.bridge.on;
    const s = this.state;
    const mine = (d: { serial: string }) => s.open && d.serial === s.serial;
    on('explorer:places', (d) => {
      if (s.open) s.places = d.places;
      else if (this.opening) this.earlyPlaces = d.places;
    });
    on('explorer:storage', (d) => { if (s.open) s.storage = d; });
    on('explorer:folders', (d) => {
      if (!mine(d)) return;
      const next = { ...s.dirStats };
      for (const [path, stats] of Object.entries(d.folders)) {
        if (stats) next[path] = stats;
        else delete next[path];
      }
      s.dirStats = next;
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
      const task = d.task;
      if (this.dismissedTasks.has(task.id)) return;
      const before = s.tasks.find((x) => x.id === task.id);
      s.tasks = before ? s.tasks.map((x) => (x.id === task.id ? task : x)) : [...s.tasks, task];
      // koniec wgrywania do oglądanego folderu: nowe pliki od razu na ekranie (też po anulowaniu w połowie)
      const ended = !ACTIVE.has(task.status) && (!before || ACTIVE.has(before.status));
      if (task.kind === 'to_phone' && ended && task.done_files > 0 && task.dest === s.path) void this.refresh();
    });
    on('explorer:drop', (d) => {
      if (!s.open || this.app.screen !== 'explorer') return;  // sesja żyje też na Ustawieniach i Historii
      s.drop = { count: d.count, bytes: d.bytes, dropped: true };
      void this.uploadPaths(d.paths).finally(() => { s.drop = null; });
    });
  }

  /** „Pliki” na „Połącz”. Zajęty telefon (`explorer_busy`) — baner na „Połącz”, ekran zostaje. */
  async open(serial: string): Promise<void> {
    const s = this.state;
    const app = this.app;
    if (this.opening) return;  // drugi klik „Pliki”, zanim most odpowiedział na pierwszy
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
      leftovers: r.leftovers, dest: this.startDest(), recent: [...(r.recent ?? [])],
    });
    this.earlyPlaces = null;
    app.screen = 'explorer';
    void this.loadStorage();
    void this.loadTasks();
    await this.go(s.places[0]?.path ?? ROOT);
  }

  /** Zadania kolejki mostu, które żyją dłużej niż okno (np. po przeładowaniu WebView ta sama sesja). */
  private async loadTasks(): Promise<void> {
    const s = this.state;
    const serial = s.serial;
    try {
      const r = await this.api.explorer_tasks();
      if (isApiError(r) || !s.open || s.serial !== serial) return;
      // zdarzenia `explorer:task`, które przyszły w międzyczasie, są nowsze — zostają
      const known = new Set(s.tasks.map((x) => x.id));
      const missing = r.tasks.filter((x) => !known.has(x.id) && !this.dismissedTasks.has(x.id));
      if (missing.length) s.tasks = [...missing, ...s.tasks];
    } catch {
      // bez listy pasek zadań wypełnią kolejne zdarzenia kolejki
    }
  }

  /** Zadania, które wyjście z eksploratora anuluje. */
  get activeTasks(): number {
    return this.state.tasks.filter((x) => ACTIVE.has(x.status)).length;
  }

  /** Pamięć telefonu do sylwetki w Miejscach — w tle; błąd zostawia sylwetkę bez „cieczy”. */
  private async loadStorage(): Promise<void> {
    const s = this.state;
    const serial = s.serial;
    try {
      const r = await this.api.explorer_storage();
      if (!isApiError(r) && s.open && s.serial === serial) s.storage = r;
    } catch {
      // bez pamięci sylwetka jest pusta; nic więcej się nie psuje
    }
  }

  /** „Wróć” (i każde inne wyjście z eksploratora): most zwalnia telefon, ekran wraca na „Połącz”. Przy
   *  trwających zadaniach najpierw pyta („N zadań zostanie anulowanych”); false — serwisant został. */
  async close(): Promise<boolean> {
    const count = this.state.open ? this.activeTasks : 0;
    if (count > 0 && !(await this.askLeave(count))) return false;
    const wasOpen = this.state.open;
    this.leave();
    if (!wasOpen) return true;
    try {
      await this.api.explorer_close();
    } catch {
      // okno i tak wraca na „Połącz”; most zamyka sesję także przy wyjściu z programu
    }
    return true;
  }

  private askLeave(count: number): Promise<boolean> {
    this.leaveAnswer?.(false);  // drugie wyjście, zanim odpowiedziano na pierwsze: pierwsze zostaje
    this.state.leaveAsk = count;
    return new Promise((resolve) => { this.leaveAnswer = resolve; });
  }

  /** Odpowiedź z okna pytania o wyjście: true — anuluj zadania i wyjdź, false — zostań. */
  answerLeave(ok: boolean): void {
    const answer = this.leaveAnswer;
    this.leaveAnswer = null;
    this.state.leaveAsk = 0;
    answer?.(ok);
  }

  async go(path: string, refresh = false): Promise<void> {
    const s = this.state;
    if (!s.open) return;
    const seq = ++this.seq;
    const known = refresh ? undefined : this.folders.get(path);
    if (known) this.showList(known, false);
    s.loading = !known;
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
    this.remember(r);
    if (r.folders && Object.keys(r.folders).length) s.dirStats = { ...s.dirStats, ...r.folders };
    this.showList(r, (refresh || !!known) && r.path === s.path);
  }

  private remember(r: ExplorerListView): void {
    this.folders.delete(r.path);
    this.folders.set(r.path, r);
    if (this.folders.size > FOLDER_MEMORY) this.folders.delete(this.folders.keys().next().value!);
  }

  /** Lista na ekran; `same` — ten sam folder odświeżony (zaznaczenie i podgląd zostają). */
  private showList(r: ExplorerListView, same: boolean): void {
    const s = this.state;
    // Odświeżenie bez zmian to częsty przypadek (powrót do folderu): ten sam widok, nic się nie przelicza.
    const unchanged = same && sameEntries(s.entries, r.entries);
    if (same && !unchanged) {
      const old = new Set(s.entries.map((e) => e.path));
      this.markFresh(r.entries.filter((e) => !old.has(e.path)).map((e) => e.path));
    } else if (!same) {
      this.markFresh([]);
    }
    Object.assign(s, { error: null, path: r.path, crumbs: r.crumbs, entries: unchanged ? s.entries : r.entries,
      locked: r.locked, skipped: r.skipped });
    if (same) {
      const present = new Set(r.entries.map((e) => e.path));
      if (s.preview !== null && !present.has(s.preview)) s.preview = null;  // plik zniknął przy odświeżeniu
      for (const p of [...s.selected]) if (!present.has(p)) s.selected.delete(p);
      if (s.anchor && !present.has(s.anchor)) s.anchor = null;
    } else {
      s.selected.clear();
      Object.assign(s, { anchor: null, query: '', preview: null,
        view: this.app.settings.explorer_view ?? defaultView(placeAt(s.places, r.path)?.key ?? null),
        peek: this.app.settings.explorer_peek ?? true });
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
    this.app.settings = { ...this.app.settings, explorer_view: view };
    // Kolejne szybkie kliknięcia zapisują się w tej samej kolejności co wybory.
    this.viewWrites = this.viewWrites.then(() => this.request(() => this.api.save_settings({ explorer_view: view })));
  }

  setPeek(on: boolean): void {
    this.state.peek = on;
    this.app.settings = { ...this.app.settings, explorer_peek: on };
    // Ta sama kolejka co widok: zapisy idą w kolejności kliknięć.
    this.viewWrites = this.viewWrites.then(() => this.request(() => this.api.save_settings({ explorer_peek: on })));
  }

  /** Klik zaznacza od razu; dwuklik przywraca zaznaczenie sprzed pierwszego kliku (otwiera, nie zaznacza).
   *  Pierwsze zaznaczenie wstrzymuje tylko pasek, żeby nie mignął przy dwukliku. */
  clickSelect(path: string, detail: number, mods: SelectMods = {}, order?: readonly string[]): void {
    const s = this.state;
    if (detail > 1) {
      if (this.lastClick?.path === path) {
        s.selected.clear();
        for (const p of this.lastClick.selected) s.selected.add(p);
        s.anchor = this.lastClick.anchor;
      }
      this.lastClick = null;
      return;
    }
    const before = { path, selected: [...s.selected], anchor: s.anchor };
    if (detail > 0 && !s.selected.size) this.holdBar();
    this.select(path, mods, order);
    this.lastClick = before;
  }

  private holdBar(): void {
    clearTimeout(this.holdTimer);
    this.state.barHeld = true;
    this.holdTimer = setTimeout(() => { this.state.barHeld = false; }, DOUBLE_CLICK_MS);
  }

  /** Ta sama kolumna odwraca kierunek; nowa zaczyna od `SORT_START`. */
  setSort(key: SortKey): void {
    const s = this.state;
    s.sort = s.sort.key === key ? { key, dir: s.sort.dir === 1 ? -1 : 1 } : { key, dir: SORT_START[key] };
  }

  /** Lista wyboru w siatce: `klucz:kierunek`. */
  setSortTo(value: string): void {
    const [key, dir] = value.split(':');
    this.state.sort = { key: key as SortKey, dir: Number(dir) === 1 ? 1 : -1 };
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
   *  (z Ctrl dopisany do zaznaczenia). `order` — kolejność na ekranie, gdy inna niż `items`
   *  (galeria układa pliki po dniach). */
  select(path: string, mods: SelectMods = {}, order?: readonly string[]): void {
    const s = this.state;
    const sel = s.selected;
    if (mods.shift && s.anchor) {
      order ??= this.items.map((e) => e.path);
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
    if (!additive) {
      const keep = new Set(paths);
      for (const p of [...sel]) if (!keep.has(p)) sel.delete(p);
    }
    for (const p of paths) if (!sel.has(p)) sel.add(p);
  }

  selectAll(): void {
    for (const e of this.items) this.state.selected.add(e.path);
  }

  clear(): void {
    this.state.selected.clear();
    this.state.anchor = null;
  }

  // ---- podgląd i odtwarzacz --------------------------------------------------------------------

  /** Odtwarzacz muzyki (tworzony przy pierwszym użyciu); żyje do końca sesji eksploratora. */
  get audio(): AudioPlayer {
    if (!this.player) {
      const player = new AudioPlayer();
      player.onerror = () => { this.state.playError = true; };
      player.el.addEventListener('ended', () => { void this.skipTrack(); });
      this.player = player;
    }
    return this.player;
  }

  /** Plik w oknie podglądu (wpis bieżącego folderu) albo undefined. */
  get previewEntry(): EntryView | undefined {
    const path = this.state.preview;
    return path === null ? undefined : this.state.byPath.get(path);
  }

  openPreview(path: string): void {
    if (this.state.byPath.get(path)?.kind !== 'file') return;
    this.state.preview = path;
    this.state.error = null;  // baner w podglądzie mówi tylko o jego własnych działaniach
  }

  closePreview(): void {
    this.state.preview = null;
  }

  /** Strzałki w podglądzie: poprzedni/następny plik spośród widocznych po filtrze i szukaniu (bez zawijania). */
  next(delta: 1 | -1): void {
    const s = this.state;
    const files = this.items.filter((e) => e.kind === 'file');
    const at = files.findIndex((e) => e.path === s.preview);
    const to = files[at + delta];
    if (at >= 0 && to) s.preview = to.path;
  }

  /** Wszystkie pola metadanych pliku (EXIF, MediaStore) albo null, gdy się nie udało. */
  async meta(path: string) {
    return (await this.request(() => this.api.explorer_meta(path), false))?.meta ?? null;
  }

  /** Kawałek tekstu pliku; `more` — następny kawałek tego samego pliku. */
  text(path: string, more: boolean) {
    return this.request(() => this.api.explorer_text(path, more), false);
  }

  /** Początek tekstu do dymku przy najechaniu: lekki odczyt, który nie rusza czytnika pełnego podglądu. */
  textHead(path: string) {
    return this.request(() => this.api.explorer_text_head(path), false);
  }

  /** Cały arkusz do pełnego podglądu. */
  sheet(path: string) {
    return this.request(() => this.api.explorer_sheet(path), false);
  }

  /** Początek pierwszego arkusza do dymku przy najechaniu. */
  sheetHead(path: string) {
    return this.request(() => this.api.explorer_sheet_head(path), false);
  }

  async openMap(lat: number, lon: number): Promise<void> {
    await this.request(() => this.api.explorer_open_map(lat, lon));
  }

  /** „Kopiuj na komputer” w podglądzie: tylko ten plik, do zapamiętanego folderu (bez folderu — najpierw pyta). */
  async copyPreview(): Promise<boolean> {
    const s = this.state;
    const path = s.preview;
    if (path === null || s.starting) return false;
    const dest = await this.destForCopy();
    if (dest === undefined) return false;
    return this.copy({ paths: [path], dest, verify: this.app.settings.verify_copies, exclude: [], clear: false });
  }

  /** Folder docelowy na starcie sesji: w trybie „stały” — stały folder, inaczej ostatnio użyty. */
  private startDest(): string | null {
    const st = this.app.settings;
    return (st.explorer_dest_mode === 'fixed' ? st.explorer_dest_fixed : st.explorer_dest) ?? null;
  }

  /** Folder dla kopii wg trybu z ustawień. Null — most sam weźmie stały folder (i zgłosi, gdy go nie ma);
   *  undefined — serwisant zrezygnował z wyboru. */
  private async destForCopy(): Promise<string | null | undefined> {
    const s = this.state;
    const st = this.app.settings;
    if (st.explorer_dest_mode === 'ask' || !s.dest) {
      if (st.explorer_dest_mode === 'fixed') s.destMissing = true;  // stały folder nie jest ustawiony
      if (!(await this.pickDest())) return undefined;
      return s.dest;
    }
    return st.explorer_dest_mode === 'fixed' && s.dest === st.explorer_dest_fixed ? null : s.dest;
  }

  private track(e: EntryView): PlayingTrack {
    return { path: e.path, title: e.label ?? e.name, cover: e.thumb, url: e.url! };
  }

  /** Odtwórz utwór (od początku, gdy to inny niż grający); z listy ekranu zapamiętuje listę odtwarzania. */
  async playTrack(entry: EntryView): Promise<void> {
    if (!entry.url) return;
    const s = this.state;
    if (s.playing?.path !== entry.path || !s.queue.some((t) => t.path === entry.path)) {
      s.queue = this.items.filter((e) => e.kind === 'file' && e.type === 'audio' && e.url).map((e) => this.track(e));
      if (!s.queue.some((t) => t.path === entry.path)) s.queue = [...s.queue, this.track(entry)];
    }
    await this.begin(this.track(entry));
  }

  private async begin(track: PlayingTrack): Promise<void> {
    const s = this.state;
    if (s.playing?.path !== track.path) {
      s.playError = false;
      this.audio.load(track.url);
      s.playing = track;
    }
    s.playError = !(await this.audio.play());  // udane odtworzenie (także ponowne) gasi błąd
  }

  /** Spacja / przycisk: odtwarza, wstrzymuje albo wznawia utwór. */
  async toggleTrack(entry?: EntryView): Promise<void> {
    const s = this.state;
    const playing = s.playing;
    if (playing && (!entry || entry.path === playing.path)) {
      if (this.audio.el.paused) await this.begin(playing);
      else this.audio.pause();
    } else if (entry) {
      await this.playTrack(entry);
    }
  }

  /** Następny utwór z zapamiętanej listy odtwarzania (⏭). */
  get nextTrack(): PlayingTrack | undefined {
    const { queue, playing } = this.state;
    const at = queue.findIndex((t) => t.path === playing?.path);
    return at >= 0 ? queue[at + 1] : undefined;
  }

  /** Z mini-odtwarzacza z powrotem do pełnego podglądu, także gdy oglądany jest już inny folder. */
  async openPlaying(): Promise<void> {
    const s = this.state;
    const path = s.playing?.path;
    if (!path) return;
    const folder = parentPath(path);
    if (folder && folder !== s.path) await this.go(folder);
    this.openPreview(path);
  }

  async skipTrack(): Promise<void> {
    const next = this.nextTrack;
    if (!next) return;
    const s = this.state;
    if (s.preview !== null && s.preview === s.playing?.path) this.openPreview(next.path);  // podgląd tego utworu idzie za nim
    await this.begin(next);
  }

  stopTrack(): void {
    this.state.playing = null;
    this.state.queue = [];
    this.state.playError = false;
    this.player?.stop();
  }

  // ---- zadania: kopiowanie na komputer i wgrywanie na telefon ---------------------------------

  /** Okno wyboru folderu docelowego na komputerze; most go zapamiętuje. False — anulowane. */
  async pickDest(): Promise<boolean> {
    const r = await this.request(() => this.api.explorer_pick_dest());
    if (!r?.path) return false;
    this.state.dest = r.path;
    // most zapamiętuje wybór tylko w trybie „ostatni”; w innych to jednorazowy folder tej sesji
    if (this.app.settings.explorer_dest_mode === 'last') {
      this.app.settings = { ...this.app.settings, explorer_dest: r.path };
    }
    return true;
  }

  /** „Kopiuj” z paska zaznaczenia (`verifyHash` — nadpisuje ustawienie „sprawdzaj kopie”; bez argumentu
   *  decyduje ustawienie). Tryb „pytaj” albo brak folderu — najpierw okno wyboru folderu. Zaznaczenie znika,
   *  gdy zadanie trafi do kolejki. */
  async copySelected(verifyHash?: boolean): Promise<void> {
    const s = this.state;
    const paths = [...s.selected];
    if (!paths.length || s.starting) return;
    const dest = await this.destForCopy();
    if (dest === undefined) return;
    await this.copy({ paths, dest, verify: verifyHash ?? this.app.settings.verify_copies, exclude: [], clear: true });
  }

  /** Wgranie plików i folderów z komputera do bieżącego folderu telefonu. */
  async uploadPaths(paths: string[], verifyHash = false): Promise<void> {
    const s = this.state;
    if (!paths.length || !s.open || s.locked) return;
    await this.start('to_phone', () => this.api.explorer_upload(paths, s.path, verifyHash));
  }

  /** „Wgraj tutaj”: systemowe okno wyboru plików albo folderu. */
  async pickUpload(kind: 'files' | 'folder', verifyHash = false): Promise<void> {
    const r = await this.request(() => this.api.explorer_pick_upload(kind));
    if (r) await this.uploadPaths(r.paths, verifyHash);
  }

  /** Ctrl+V: pliki skopiowane w Eksploratorze Windows. */
  async paste(): Promise<void> {
    const s = this.state;
    if (!s.open || s.locked) return;
    const r = await this.request(() => this.api.explorer_clipboard());
    if (!r) return;
    s.clipboardEmpty = r.paths.length === 0;
    await this.uploadPaths(r.paths);
  }

  async pause(id: string): Promise<void> {
    await this.request(() => this.api.explorer_pause(id));
  }

  async resume(id: string): Promise<void> {
    await this.request(() => this.api.explorer_resume(id));
  }

  async cancel(id: string): Promise<void> {
    await this.request(() => this.api.explorer_cancel(id));
  }

  /** „Ponów uszkodzone”: nieudane pliki zadania idą nowym zadaniem, stare podsumowanie znika. */
  async retry(id: string): Promise<void> {
    const r = await this.request(() => this.api.explorer_retry(id));
    if (!r?.task) return;
    this.dismissTask(id);
    await this.loadTasks();
  }

  /** „Otwórz folder” po kopii — folder na komputerze w Eksploratorze Windows. */
  async openFolder(task: TaskView): Promise<void> {
    await this.request(() => this.api.explorer_open_folder(task.dest));
  }

  /** „Pokaż” po wgraniu: folder na telefonie z zaznaczonymi wgranymi pozycjami, przewinięty do pierwszej. */
  async show(task: TaskView): Promise<void> {
    const s = this.state;
    await this.go(task.dest, task.dest === s.path);
    Object.assign(s, { query: '', filter: 'all', preview: null });
    const prefix = `${task.dest.replace(/\/$/, '')}/`;
    const tops = new Set(task.targets.filter((p) => p.startsWith(prefix))
      .map((p) => prefix + p.slice(prefix.length).split('/')[0]));
    s.selected.clear();
    const shown = this.items.filter((e) => tops.has(e.path)).map((e) => e.path);
    for (const p of shown) s.selected.add(p);
    s.anchor = shown[0] ?? null;
    s.reveal = shown[0] ?? null;
  }

  /** Skończone zadanie znika z paska zadań. */
  dismissTask(id: string): void {
    this.dismissedTasks.add(id);
    this.state.tasks = this.state.tasks.filter((x) => x.id !== id);
  }

  dismissProblems(): void {
    this.state.problems = null;
  }

  /** Z okna problemów: ta sama kopia bez plików, które się nie uda (działa też dla plików z zaznaczonego folderu). */
  async copyWithout(paths: readonly string[]): Promise<void> {
    const last = this.lastCopy;
    this.state.problems = null;
    if (last) await this.copy({ ...last, exclude: [...last.exclude, ...paths] });
  }

  /** Strefa upuszczania przy przeciąganiu nad oknem (przed upuszczeniem; samo wgranie — `explorer:drop`). */
  dragOver(count: number | null): void {
    const s = this.state;
    if (!s.open || s.locked || s.drop?.dropped) return;
    s.drop = { count, bytes: null, dropped: false };
  }

  dragEnd(): void {
    if (this.state.drop && !this.state.drop.dropped) this.state.drop = null;
  }

  dismissClipboard(): void {
    this.state.clipboardEmpty = false;
  }

  // ---- nowy folder / nowy plik tekstowy ------------------------------------------------------

  /** Null — utworzono (folder odświeżony, nowa pozycja wskakuje); inaczej błąd do pokazania w oknie. */
  async newFolder(name: string): Promise<ApiErrorBody | null> {
    return this.create(() => this.api.explorer_mkdir(this.state.path, name));
  }

  async newText(name: string, text: string): Promise<ApiErrorBody | null> {
    return this.create(() => this.api.explorer_new_text(this.state.path, name, text));
  }

  private async create(call: () => Promise<{ path: string } | ApiError>): Promise<ApiErrorBody | null> {
    let r: { path: string } | ApiError;
    try {
      r = await call();
    } catch (e) {
      r = { error: { key: 'internal', message: String(e) } };
    }
    if (isApiError(r)) return r.error;
    await this.refresh();
    return null;
  }

  private async copy(job: NonNullable<typeof this.lastCopy>): Promise<boolean> {
    this.lastCopy = job;
    const { paths, dest, verify, exclude } = job;
    this.noDest = false;
    const started = await this.start('to_pc', () => (exclude.length
      ? this.api.explorer_copy(paths, dest, verify, exclude) : this.api.explorer_copy(paths, dest, verify)), ['explorer_no_dest']);
    if (started === null && this.noDest) {
      // stały folder niedostępny: baner i wybór innego folderu na tę jedną kopię (ustawienie zostaje)
      this.noDest = false;
      const st = this.app.settings;
      this.state.destMissing = st.explorer_dest_mode === 'fixed';
      if (!(await this.pickDest())) return false;
      return this.copy({ ...job, dest: this.state.dest });
    }
    if (started !== null && job.dest === null) this.state.destMissing = false;  // stały folder znów działa
    // w trybie „stały” wybrany folder obowiązuje jedną kopię; następna wraca do stałego (i sprawdza go od nowa)
    const st = this.app.settings;
    if (st.explorer_dest_mode === 'fixed') this.state.dest = st.explorer_dest_fixed ?? null;
    if (started !== null && job.clear) this.clear();
    return started !== null;
  }

  /** Plan zadania w moście: problemy → okno (nic nie startuje), zadanie → pasek zadań. Id zadania albo null.
   *  `quiet` — klucze błędów, które nie idą do banera (wywołujący sam o nich mówi). */
  private async start(kind: TaskView['kind'], call: () => Promise<ExplorerStart | ApiError>, quiet: string[] = []): Promise<string | null> {
    const s = this.state;
    s.starting = true;
    let r: ExplorerStart | null;
    try {
      r = await this.request(call, true, quiet);
    } finally {
      s.starting = false;
    }
    if (!r || !s.open) return null;
    if ('problems' in r) {
      s.problems = { kind, list: r.problems };
      return null;
    }
    // Nowe zadanie zastępuje stare potwierdzenia; kolejka aktywnych i podsumowania z problemami zostają.
    for (const task of s.tasks) {
      if (task.id !== r.task && !ACTIVE.has(task.status) && task.status !== 'failed' && !task.failed.length && !task.omitted) {
        this.dismissTask(task.id);
      }
    }
    // Wynik zawiera tylko id. Pełne widoki przychodzą zdarzeniami; odczyt listy
    // wypełnia pasek także wtedy, gdy zdarzenie jeszcze czeka na wysłanie.
    await this.loadTasks();
    return r.task;
  }

  /** Wywołanie mostu z błędem w banerze nad listą (sesja zamknięta → powrót na „Połącz”); `banner = false` —
   *  błąd tylko zwraca null, a okno wywołujące (podgląd) mówi o nim samo. */
  private async request<T extends object>(call: () => Promise<T | ApiError>, banner = true, quiet: string[] = []): Promise<T | null> {
    let r: T | ApiError;
    try {
      r = await call();
    } catch (e) {
      r = { error: { key: 'internal', message: String(e) } };
    }
    if (!isApiError(r)) return r;
    if (quiet.includes(r.error.key)) {
      this.noDest = r.error.key === 'explorer_no_dest';
      return null;
    }
    if (r.error.key === 'explorer_not_open') {
      this.leave();
      this.app.error = r.error;
    } else if (banner && this.state.open) {
      this.state.error = r.error;
    }
    return null;
  }

  private markFresh(paths: string[]): void {
    const fresh = this.state.fresh;
    clearTimeout(this.freshTimer);
    fresh.clear();
    for (const p of paths) fresh.add(p);
    if (paths.length) this.freshTimer = setTimeout(() => fresh.clear(), FRESH_MS);
  }

  dismissLeftovers(): void {
    this.state.leftovers = 0;
  }

  dismissNotice(): void {
    this.state.notice = null;
  }

  /** Zaznaczone, a niewidoczne po zmianie filtra lub szukania, nie mogą trafić do kopii. */
  private keepVisibleSelection(): void {
    if (!this.state.selected.size) return;
    const shown = new Set(this.items.map((e) => e.path));
    for (const p of [...this.state.selected]) if (!shown.has(p)) this.state.selected.delete(p);
  }

  /** Koniec sesji po stronie UI: stan od nowa, ekran eksploratora wraca na „Połącz”. */
  private leave(): void {
    // „Ostatnio” zapisuje most (osobno dla każdego telefonu) i oddaje przy następnym otwarciu
    this.reset();
    if (this.app.screen === 'explorer') this.app.screen = 'main';
  }

  private reset(): void {
    const s = this.state;
    clearTimeout(this.holdTimer);
    this.lastClick = null;
    this.lastCopy = null;
    this.folders.clear();
    this.dismissedTasks.clear();
    // sesji już nie ma (np. most zamknął ją sam): pytanie o anulowanie zadań nie ma sensu — wyjście idzie dalej
    if (this.leaveAnswer) this.answerLeave(true);
    this.seq += 1;  // spóźniona lista poprzedniej sesji nie trafi na ekran
    this.stopTrack();
    s.selected.clear();
    this.markFresh([]);
    Object.assign(s, {
      dirStats: {}, storage: null, problems: null, drop: null, starting: false, destMissing: false, clipboardEmpty: false, barHeld: false, hover: null, reveal: null,
      open: false, serial: null, device: null, places: [], recent: [], path: ROOT, crumbs: [], entries: [],
      locked: false, skipped: 0, loading: false, view: 'list', filter: 'all', query: '', anchor: null, tasks: [],
      offline: false, preview: null, playing: null, queue: [], playError: false, dest: null, leftovers: 0, media: '', error: null,
    });
  }
}
