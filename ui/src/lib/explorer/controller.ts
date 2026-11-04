import { type Bridge, isApiError } from '../bridge';
import { AudioPlayer } from './audio';
import type { AppState } from '../state.svelte';
import type { ApiError, ApiErrorBody, EntryView, ExplorerListView, ExplorerOpenView, ExplorerStart, PlaceView, TaskView } from '../types';
import { days, defaultView, type ExplorerFilter, type ExplorerView, parentPath, placeAt, ROOT, SORT_START, type SortKey, visible } from './logic';
import { ExplorerState, type PlayingTrack } from './state.svelte';

/** Jak `EXPLORER_RECENT_MAX` w ustawieniach mostu. */
const RECENT_MAX = 8;
/** Jak długo nowe wpisy po odświeżeniu są „świeże” (animacja `pop-in`). */
const FRESH_MS = 700;
/** Zadania, które wyjście z eksploratora anuluje (most zamyka kolejkę razem z sesją). */
const ACTIVE: ReadonlySet<TaskView['status']> = new Set(['queued', 'running', 'paused', 'waiting']);

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
  private player: AudioPlayer | null = null;
  private leaveAnswer: ((ok: boolean) => void) | null = null;  // okno „N zadań zostanie anulowanych”

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
    on('explorer:storage', (d) => { if (s.open) s.storage = d; });
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
      const before = s.tasks.find((x) => x.id === task.id);
      s.tasks = before ? s.tasks.map((x) => (x.id === task.id ? task : x)) : [...s.tasks, task];
      // skończone wgranie do oglądanego folderu: nowe pliki od razu na ekranie
      if (task.kind === 'to_phone' && task.status === 'done' && before?.status !== 'done' && task.dest === s.path) {
        void this.refresh();
      }
    });
    on('explorer:drop', (d) => {
      if (!s.open) return;
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
      leftovers: r.leftovers, dest: app.settings.explorer_dest ?? null, recent: [...(app.settings.explorer_recent ?? [])],
    });
    this.earlyPlaces = null;
    app.screen = 'explorer';
    void this.loadStorage();
    await this.go(s.places[0]?.path ?? ROOT);
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
    if (same) {
      const old = new Set(s.entries.map((e) => e.path));
      this.markFresh(r.entries.filter((e) => !old.has(e.path)).map((e) => e.path));
    } else {
      this.markFresh([]);
    }
    Object.assign(s, { error: null, path: r.path, crumbs: r.crumbs, entries: r.entries, locked: r.locked,
      skipped: r.skipped });
    if (same) {
      const present = new Set(r.entries.map((e) => e.path));
      if (s.preview !== null && !present.has(s.preview)) s.preview = null;  // plik zniknął przy odświeżeniu
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
    return path === null ? undefined : this.state.entries.find((e) => e.path === path);
  }

  openPreview(path: string): void {
    if (!this.state.entries.some((e) => e.path === path && e.kind === 'file')) return;
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

  async openMap(lat: number, lon: number): Promise<void> {
    await this.request(() => this.api.explorer_open_map(lat, lon));
  }

  /** „Kopiuj na komputer” w podglądzie: tylko ten plik, do zapamiętanego folderu (bez folderu — najpierw pyta). */
  async copyPreview(): Promise<boolean> {
    const s = this.state;
    const path = s.preview;
    if (path === null || s.starting) return false;
    if (!s.dest && !(await this.pickDest())) return false;
    return this.copy([path], s.dest!, false);
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
    if (!(await this.audio.play())) s.playError = true;
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

  async skipTrack(): Promise<void> {
    const next = this.nextTrack;
    if (!next) return;
    if (this.state.preview !== null) this.openPreview(next.path);  // okno podglądu idzie za utworem
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
    this.app.settings = { ...this.app.settings, explorer_dest: r.path };
    return true;
  }

  /** „Kopiuj” z paska zaznaczenia (`verifyHash` — „Sprawdź co do bajtu”). Bez zapamiętanego folderu
   *  najpierw pyta o folder. Zaznaczenie znika, gdy zadanie trafi do kolejki. */
  async copySelected(verifyHash = false): Promise<void> {
    const s = this.state;
    const paths = [...s.selected];
    if (!paths.length || s.starting) return;
    if (!s.dest && !(await this.pickDest())) return;
    if (await this.copy(paths, s.dest!, verifyHash)) this.clear();
  }

  /** Wgranie plików i folderów z komputera do bieżącego folderu telefonu. */
  async uploadPaths(paths: string[]): Promise<void> {
    const s = this.state;
    if (!paths.length || !s.open || s.locked) return;
    await this.start('to_phone', () => this.api.explorer_upload(paths, s.path));
  }

  /** „Wgraj tutaj”: systemowe okno wyboru plików albo folderu. */
  async pickUpload(kind: 'files' | 'folder'): Promise<void> {
    const r = await this.request(() => this.api.explorer_pick_upload(kind));
    if (r) await this.uploadPaths(r.paths);
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

  /** „Otwórz folder” po kopii — folder na komputerze w Eksploratorze Windows. */
  async openFolder(task: TaskView): Promise<void> {
    await this.request(() => this.api.explorer_open_folder(task.dest));
  }

  /** „Pokaż” po wgraniu — folder na telefonie. */
  show(task: TaskView): Promise<void> {
    return this.go(task.dest);
  }

  /** Skończone zadanie znika z paska zadań. */
  dismissTask(id: string): void {
    this.state.tasks = this.state.tasks.filter((x) => x.id !== id);
  }

  dismissProblems(): void {
    this.state.problems = null;
  }

  /** Z okna problemów FAT32: odznacza pliki za duże dla pendrive'a (most podaje same nazwy). */
  unselectNames(names: readonly string[]): void {
    const wanted = new Set(names);
    for (const p of [...this.state.selected]) if (wanted.has(p.split('/').pop()!)) this.state.selected.delete(p);
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

  private async copy(paths: string[], dest: string, verifyHash: boolean): Promise<boolean> {
    return (await this.start('to_pc', () => this.api.explorer_copy(paths, dest, verifyHash))) !== null;
  }

  /** Plan zadania w moście: problemy → okno (nic nie startuje), zadanie → pasek zadań. Id zadania albo null. */
  private async start(kind: TaskView['kind'], call: () => Promise<ExplorerStart | ApiError>): Promise<string | null> {
    const s = this.state;
    s.starting = true;
    let r: ExplorerStart | null;
    try {
      r = await this.request(call);
    } finally {
      s.starting = false;
    }
    if (!r || !s.open) return null;
    if ('problems' in r) {
      s.problems = { kind, list: r.problems };
      return null;
    }
    // zdarzenia kolejki mogły przyjść przed wynikiem — nowszy stan zostaje
    if (!s.tasks.some((x) => x.id === r.task.id)) s.tasks = [...s.tasks, r.task];
    return r.task.id;
  }

  /** Wywołanie mostu z błędem w banerze nad listą (sesja zamknięta → powrót na „Połącz”); `banner = false` —
   *  błąd tylko zwraca null, a okno wywołujące (podgląd) mówi o nim samo. */
  private async request<T extends object>(call: () => Promise<T | ApiError>, banner = true): Promise<T | null> {
    let r: T | ApiError;
    try {
      r = await call();
    } catch (e) {
      r = { error: { key: 'internal', message: String(e) } };
    }
    if (!isApiError(r)) return r;
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
    // sesji już nie ma (np. most zamknął ją sam): pytanie o anulowanie zadań nie ma sensu — wyjście idzie dalej
    if (this.leaveAnswer) this.answerLeave(true);
    this.seq += 1;  // spóźniona lista poprzedniej sesji nie trafi na ekran
    this.stopTrack();
    s.selected.clear();
    this.markFresh([]);
    Object.assign(s, {
      storage: null, problems: null, drop: null, starting: false, clipboardEmpty: false,
      open: false, serial: null, device: null, places: [], recent: [], path: ROOT, crumbs: [], entries: [],
      locked: false, skipped: 0, loading: false, view: 'list', filter: 'all', query: '', anchor: null, tasks: [],
      offline: false, preview: null, playing: null, queue: [], playError: false, dest: null, leftovers: 0, media: '', error: null,
    });
  }
}
