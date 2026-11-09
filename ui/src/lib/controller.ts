import { type Bridge, isApiError } from './bridge';
import { i18n } from './i18n/index.svelte';
import { actedAfter, changedVerdicts, defaultApps, installableApps, defaultSelection, defaultUploadChoice, keptUploadChoice, otherGroup, TEL_KINDS, telWrite, resumableCopy, UPLOAD_GROUPS, resumeSelection, rescanSelection, TRANSFER_CATEGORIES, transferNeed, transferTotals, isManual, mergeSelection, offeredFixes, stableEta, notificationsManual, upsertStep, withoutUndone } from './logic';
import { EMPTY_TRANSFER_SELECTION, emptyRestore, type AppState, type HistoryTab, type RepairTab, type SettingsCategory } from './state.svelte';
import { ExplorerController } from './explorer/controller';
import { applyTheme } from './theme';
import type {
  ApiError, AppView, CacheCleared, CacheUsage, ExportKind, TransferCategory, EtaView, DevicesPayload, Lang, Level, Mode, ServiceInfo, Settings, TelKind, TelemetrySample, Theme, UploadChoiceView, Verdict,
} from './types';

const CONSOLE_LIMIT = 500;
const FLASH_MS = 2000;  // czas animacji `.flash` z app.css

/** Błędy dokończenia aplikacji, po których warto spróbować przy następnym odblokowaniu (kabel, zajęty telefon). */
const REINSTALL_TRANSIENT = ['disconnected', 'offline', 'timeout', 'adb_error', 'busy', 'device_busy', 'transfer_no_phone',
  'transfer_too_many_disconnects'];

export class Controller {
  private ended = new Set<string>();
  /** Telefony do przejścia „Kopia gotowa → plan wgrywania”, odłożone do końca zadania kopii. */
  private offerAfterBackup: string[] | null = null;
  private knownLoaded = false;
  private autoMirrored = new Set<string>();
  /** Wybór serwisanta sprzed ponownego planu po `transfer_phone_full` — nowy plan go zachowuje (przycięty). */
  private replanChoice: UploadChoiceView | null = null;
  private resumeAfterScan = false;  // „Wznów” z ekranu Połącz: po odczycie telefonu kopia rusza sama
  private uiErrorSent = false;
  private rechecking = false;  // odczyt kontroli w tle: następny nie startuje, póki poprzedni trwa
  private flashToken = 0;  // błysk zmienionych werdyktów: zdejmuje go tylko timer ostatniego apk:done
  private etaSeq = 0;  // szacunek dla zaznaczenia: liczy się tylko odpowiedź na ostatnie zapytanie

  /** Eksplorator plików telefonu (ekran `explorer`). */
  readonly explorer: ExplorerController;

  constructor(readonly state: AppState, readonly bridge: Bridge) {
    this.explorer = new ExplorerController(state, bridge, (changes) => this.saveSettings(changes));
  }

  private get api() {
    return this.bridge.api;
  }

  private async call<T>(promise: Promise<T | ApiError>): Promise<T | null> {
    try {
      const result = await promise;
      if (isApiError(result)) {
        if (result.error.key === 'busy' && result.error.message === 'phone_cleanup') {
          // Telefon wraca do ustawień sprzed przerwanego wgrywania: baner sprzątania (z `transfer:cleanup_started`),
          // nie karta błędu. Most ponawia sprzątanie sam, więc bez przycisku „Spróbuj ponownie”.
          return null;
        }
        this.state.error = result.error;
        return null;
      }
      return result;
    } catch (e) {
      this.state.error = { key: 'internal', message: String(e) };
      return null;
    }
  }

  /** Odczyt w tle (auto-sprawdzanie co `RECHECK_MS`): błąd mostu nie podnosi karty błędu (`s.error`) — następna
   *  próba za chwilę; jawne akcje serwisanta idą przez `call`. */
  private async quiet<T>(promise: Promise<T | ApiError>): Promise<T | null> {
    try {
      const result = await promise;
      return isApiError(result) ? null : result;
    } catch {
      return null;
    }
  }

  setJob(id: string, kind: string): void {
    if (!this.ended.has(id)) this.state.job = { id, kind };
  }

  async init(): Promise<void> {
    this.subscribe();
    const settings = await this.call(this.api.get_settings());
    if (settings) this.applySettings(settings);
    const update = await this.call(this.api.update_state());
    if (update) this.state.update = update;
    await this.loadCrashes();
    // Przed listą urządzeń: onDevices() decyduje o auto-podglądzie na podstawie s.mirror.available.
    const mirror = await this.call(this.api.mirror_status());
    if (mirror) this.state.mirror = { ...this.state.mirror, available: mirror.available, serial: mirror.serial, state: mirror.state };
    const devices = await this.call(this.api.list_devices());
    if (devices) this.onDevices(devices);
    await this.call(this.api.watch_devices(true));
    await this.loadKnownSerials();
  }

  async loadKnownSerials(): Promise<void> {
    if (this.knownLoaded) return;
    this.knownLoaded = true;
    const r = await this.call(this.api.history(null));
    if (r) this.state.knownSerials = r.serials;
  }

  private applySettings(settings: Settings): void {
    this.state.settings = settings;
    i18n.lang = settings.lang;
    if (typeof document !== 'undefined') document.documentElement.lang = settings.lang;
    if (typeof document !== 'undefined') applyTheme(settings.theme ?? 'system');
    this.state.settingsLoaded = true;
  }

  /** Telefony gotowe (`state: device`) w poprzedniej liście — do wykrycia „pojawił się nowy”. */
  private readySerials = new Set<string>();

  private onDevices(d: DevicesPayload): void {
    const s = this.state;
    s.devices = d.devices;
    s.devicesError = d.error;
    if (s.serial && !d.devices.some((e) => e.serial === s.serial && e.state === 'device')) {
      s.serial = null;
    }
    const ready = d.devices.filter((e) => e.state === 'device');
    if (!s.serial && ready.length === 1) s.serial = ready[0].serial;
    // Baner sprzątania dotyczy jednego telefonu: znika z jego odłączeniem albo po wybraniu innego.
    const c = s.transfer.cleanup;
    if (c.serial && !ready.some((e) => e.serial === c.serial)) s.transfer.cleanup = { serial: null, running: false, ok: null };
    else this.dropOtherCleanup();
    const picked = s.serial ? d.devices.find((e) => e.serial === s.serial && e.state === 'device') : undefined;
    if (picked && s.settings.mirror_auto && s.mirror.available && !this.autoMirrored.has(picked.serial)
        && !this.mirrorActive(picked.serial)) {
      this.autoMirrored.add(picked.serial);  // raz na uruchomienie: zamknięte okno nie wraca samo
      void this.mirrorStart(picked.serial, picked.model?.replaceAll('_', ' ') ?? picked.serial);
    }
    const before = this.readySerials;
    this.readySerials = new Set(ready.map((e) => e.serial));
    this.offerRestoreToNewPhone(ready.map((e) => e.serial).filter((x) => !before.has(x)));
  }

  /** Po gotowej kopii („Kopia gotowa”) podłączony nowy telefon (inny niż źródło kopii) od razu dostaje plan wgrywania.
   *  Raz na pojawienie się telefonu; ten sam stary telefon albo kilka telefonów naraz — nic (wybór zostaje na ekranie Połącz). */
  private offerRestoreToNewPhone(fresh: string[]): void {
    const s = this.state;
    const copy = s.transfer.copy;
    if (fresh.length === 0 || s.phase !== 'transfer_done' || !copy || copy.status === 'in_progress' || s.transfer.result?.status === 'stopped') return;
    // `transfer:done` przychodzi jeszcze z wnętrza zadania kopii: plan teraz dostałby „busy” — czekamy na `job:end`.
    if (s.job?.kind === 'backup') {
      this.offerAfterBackup = [...(this.offerAfterBackup ?? []), ...fresh];
      return;
    }
    const others = s.devices.filter((e) => e.state === 'device' && e.serial !== copy.serial);
    if (others.length !== 1 || !fresh.includes(others[0].serial)) return;
    this.selectDevice(others[0].serial);
    void this.planRestore(copy.id);
  }

  private subscribe(): void {
    const on = this.bridge.on;
    const s = this.state;
    on('devices', (d) => this.onDevices(d));
    on('scan:stage', (d) => { s.scanStage = d.stage; });
    on('scan:device', (d) => { s.device = d.device; });
    on('scan:done', (d) => {
      s.scan = d.scan;
      s.interrupted = d.interrupted;
      // Bez „zawsze pełna” werdykty heurystyk są ukryte do wyboru trybu: nic nie może być zaznaczone za serwisanta.
      s.selection = s.settings.apk_mode_default === 'full' ? defaultSelection(d.scan.apps) : {};
      s.apkFullChosen = false;
      s.actedLog = {};
      s.undoTarget = null;
      s.touched = [];
      s.unlocked = [];
      s.fixes.clear();
      s.expanded = [];
      s.openGroups = {};
      s.repairTab = 'apps';
      s.diagnostics = false;
      s.who = null;
      s.apk = { done: 0, total: 0, running: true, changed: [], eta: null };
      s.apkEstimate = null;
      s.apkFullEta = null;
      s.apkQuestion = null;
      s.selectionEta = null;
      s.showSystem = false;
      s.apkScope = 'all';
      s.phase = 'results';
    });
    // Zdarzenia porzuconej analizy APK (poprzedni skan) nie mogą zmienić nowego (BUG-10).
    const stale = (d: { job_id?: string }): boolean => !!d.job_id && !!s.job && d.job_id !== s.job.id;
    // Most prowadzi analizę APK po skanie w tym samym zadaniu (kind „scan” → „apk”) i nie wysyła
    // zmiany rodzaju: pierwsze zdarzenie analizy tego zadania ją oznacza (przycisk „Przerwij i szukaj ręcznie”).
    const apkStage = (d: { job_id?: string }): void => {
      if (s.job?.kind === 'scan' && d.job_id === s.job.id) s.job = { ...s.job, kind: 'apk' };
    };
    const eta = (d: EtaView): EtaView => ({ eta_s: d.eta_s, eta_kind: d.eta_kind, eta_min_s: d.eta_min_s, eta_max_s: d.eta_max_s });
    on('apk:estimate', (d) => {
      if (stale(d)) return;
      apkStage(d);
      s.apkEstimate = d;
      if (d.scope === 'all') s.apkFullEta = eta(d);
    });
    on('apk:question', (d) => {
      if (stale(d)) return;
      apkStage(d);
      s.apkQuestion = d;
      if (d.kind === 'mode') s.apkFullEta = eta(d);  // pytanie o tryb dotyczy całego telefonu
    });
    on('apk:progress', (d) => {
      if (stale(d)) return;
      apkStage(d);
      s.apk = { ...s.apk, done: d.done, total: d.total, running: true, eta: stableEta(s.apk.eta, d.eta_s) };
    });
    on('apk:done', (d) => {
      if (stale(d)) return;
      // Błysk „werdykt się zmienił” tylko po analizie na żądanie (głęboka, zaznaczone): po pełnej
      // zmienia się prawie każdy wiersz „Do sprawdzenia” i błysk niczego nie wyróżnia.
      const onDemand = s.job?.kind === 'deep' || s.apkScope === 'selected';
      const changed = onDemand ? changedVerdicts(s.scan?.apps ?? [], d.scan.apps) : [];
      // Znacznik znika po jednym błysku, żeby ponowne zamontowanie wiersza go nie powtarzało.
      const token = ++this.flashToken;
      if (changed.length) {
        setTimeout(() => { if (token === this.flashToken) s.apk = { ...s.apk, changed: [] }; }, FLASH_MS);
      }
      // Tryb częściowy: werdykty spoza analizy na żądanie są ukryte — bez domyślnych zaznaczeń.
      if (!isManual(d.scan)) s.selection = mergeSelection(s.selection, d.scan.apps, s.touched);
      s.scan = d.scan;
      s.apkQuestion = null;
      s.apk = { ...s.apk, running: false, changed, eta: null };
      if (isManual(d.scan)) void this.refreshSelectionEta();
    });
    on('apk:manual', (d) => {
      if (stale(d)) return;
      // Z pełnej analizy do ręcznego: zostaje tylko to, co serwisant sam zaznaczył lub zmienił.
      if (!isManual(s.scan)) {
        s.selection = Object.fromEntries(Object.entries(s.selection).filter(([p]) => s.touched.includes(p)));
      }
      s.scan = d.scan;
      s.apkQuestion = null;
      s.apk = { ...s.apk, running: false, eta: null };
      void this.refreshSelectionEta();
    });
    on('incident:state', (d) => { s.incident = { recording: d.recording, marks: 0, result: null }; });
    on('incident:done', (d) => {
      s.incident = { recording: false, marks: d.marks, result: d };
      if (d.error) s.error = d.error;
    });
    on('apk:stopped', (d) => {
      if (stale(d)) return;
      s.apkQuestion = null;
      s.apk = { ...s.apk, running: false, eta: null };
      this.fullEndedWithoutReport();
    });
    on('exec:order', (d) => {
      s.order = d.order;
      s.execPlan = d.plan;
      s.steps = [];
      s.result = null;
      s.donateBanner = false;
      s.stopped = false;
      s.stopping = false;
      s.verifying = false;
      s.disconnectedOrder = null;
      s.interrupted = s.interrupted.filter((o) => o !== d.order);
      s.plan = null;
      s.screen = 'main';
      s.phase = 'executing';
      this.resetShare();
      s.planChanged = false;
    });
    on('share:ready', (d) => {
      const cur = s.share;
      if (!cur || cur.id !== d.share_id) return; // spóźnione zdarzenie poprzedniego kodu
      if (this.staleShare(d.code)) return;
      s.share = { ...cur, code: d.code, status: 'ready', url: d.url, mode: d.mode, expires: d.expires,
                  upgraded: cur.mode === 'local' && d.mode === 'server', reason: null,
                  offline: d.offline ?? cur.offline };
    });
    on('share:failed', (d) => {
      const cur = s.share;
      // Kod już na ekranie działa dalej: późny błąd ponawiania w tle go nie zabiera.
      if (!cur || cur.id !== d.share_id || cur.status === 'ready') return;
      if (this.staleShare(d.code)) return;
      s.share = { ...cur, code: d.code, status: 'failed', reason: d.reason, offline: d.offline };
    });
    on('exec:step', (d) => { s.steps = upsertStep(s.steps, d); });
    on('exec:user_wait', (d) => { s.userWait = { ...d, since: Date.now() }; });
    on('exec:user_done', () => { s.userWait = null; });
    on('exec:question', (d) => { s.question = d; });
    on('exec:verify', () => { s.verifying = true; });
    on('exec:stopped', () => { s.stopped = true; });
    on('exec:done', (d) => {
      s.result = d;
      s.donateBanner = d.donate_reminder === true;
      s.actedLog = actedAfter(s.actedLog, s.execPlan, d);
      s.verifying = false;
      s.userWait = null;
      s.question = null;
      s.stopping = false;
      s.interrupted = d.stopped ? [d.order] : s.interrupted.filter((o) => o !== d.order);
      s.phase = 'done';
      void this.loadShots(d.order);
    });
    on('exec:disconnected', (d) => {
      s.disconnectedOrder = d.order;
      s.interrupted = [d.order];
      s.userWait = null;
      s.question = null;
      s.verifying = false;
      s.device = null;
      s.scan = null;
      s.phase = 'connect';
    });
    on('undo:step', (d) => { s.undoSteps = upsertStep(s.undoSteps, d); });
    on('undo:sites', (d) => {
      s.undoSites = d.sites;
      // kolejka witryn jest tylko w Historii (np. cofanie aplikacji z listy wyników): tam przechodzimy
      if (s.screen !== 'history') void this.openHistory(s.device?.serial ?? null);
    });
    on('undo:done', (d) => {
      s.undoResult = d;
      // koniec kolejki także po dwóch przekroczeniach czasu z rzędu (reszta pozycji nie dostaje zdarzeń)
      s.undoSites = null;
      s.userWait = null;
      // cofnięte zlecenie bez kroków „w toku” nie jest już przerwane: baner znika
      if (!d.interrupted.includes(d.order)) s.interrupted = s.interrupted.filter((o) => o !== d.order);
      if (s.undoing && d.errors.length === 0) {
        s.actedLog = withoutUndone(s.actedLog, s.undoing.order, s.undoing.pkg);
        s.undoTarget = null;
      }
      s.undoing = null;
      void this.refreshHistory();
    });
    on('adb:command', (d) => { s.console = [...s.console.slice(-(CONSOLE_LIMIT - 1)), d]; });
    on('job:error', (d) => {
      if (d.kind === 'exec' && d.key === 'plan_changed') {
        // Plan inny niż pokazany klientowi: nic nie ruszyło, pokazujemy nowy plan (spec plan-qr §6.3).
        s.planChanged = true;
        void this.openPlan();
        return;
      }
      if (d.kind === 'phone_cleanup') { // czerwony baner sprzątania mówi, co zrobić ręcznie; most ponawia w tle
        s.transfer.cleanup = { ...s.transfer.cleanup, running: false, ok: false };
        return;
      }
      if (d.kind === 'restore_apps') { // dokończenie aplikacji w tle: powód w wierszu „Aplikacje”, nie karta błędu
        if (s.transfer.appsBusy) s.transfer.appsNotes = { ...s.transfer.appsNotes, [s.transfer.appsBusy]: d.key };
        const r = s.transfer.restore;
        const transient = REINSTALL_TRANSIENT.includes(d.key);
        Object.assign(r, { appsError: d.key, appsProgress: null, reinstallDone: !transient, reinstallGaveUp: !transient });
        return;
      }
      if (d.kind === 'update') { // błędy aktualizacji pokazuje okno instalacji, nie karta błędu
        s.updateError = d;
        s.updateProgress = null;
        return;
      }
      s.error = d;
      // Każdy błąd zadania musi zostawić ekran, z którego da się wyjść (ponowny skan,
      // dokończenie albo cofnięcie zlecenia), niezależnie od klucza błędu.
      if (d.kind === 'scan' && s.phase === 'scanning') {
        s.phase = 'connect';
        s.device = null;
      } else if (d.kind === 'apk' || d.kind === 'deep') {
        s.apkQuestion = null;
        s.apk = { ...s.apk, running: false };
        if (d.kind === 'apk') this.fullEndedWithoutReport();
      } else if ((d.kind === 'exec' || d.kind === 'resume') && s.phase === 'executing') {
        if (s.order && !s.interrupted.includes(s.order)) s.interrupted = [...s.interrupted, s.order];
        s.userWait = null;
        s.question = null;
        s.verifying = false;
        s.stopping = false;
        s.phase = 'connect';
      } else if (d.kind === 'transfer_scan' && s.phase === 'transfer_choose' && s.transfer.inventory) {
        // „Sprawdź ponownie” nie wyszło: zostaje poprzedni odczyt i wybór, błąd widać na karcie.
      } else if (d.kind === 'transfer_scan' && s.phase === 'transfer_choose') {
        this.resetTransfer();
        s.device = null;
        s.phase = 'connect';
      } else if (d.kind === 'backup' && s.phase === 'transfer_backup') {
        // Kopia zostaje niedokończona: „Rozpocznij kopię” na ekranie wyboru ją wznowi.
        s.transfer.waiting = false;
        s.stopping = false;
        s.phase = 'transfer_choose';
        void this.refreshResumable();
      } else if (d.kind === 'restore_plan' && s.phase === 'transfer_restore_plan') {
        s.transfer.restore = emptyRestore();
        s.phase = 'connect';
      } else if (d.kind === 'restore' && s.phase === 'transfer_restore') {
        // Stan wgrywania zostaje: „Wgraj” na ekranie planu wznowi je (np. po zwolnieniu miejsca).
        s.transfer.waiting = false;
        s.stopping = false;
        s.transfer.restore.resumable = true;
        s.phase = 'transfer_restore_plan';
        void this.loadTransfers();
        // Brak miejsca: stary plan ma nieaktualne wolne miejsce i liczy już wgrane pliki — plan od nowa,
        // z zachowanym wyborem i widocznym błędem.
        if (d.key === 'transfer_phone_full') void this.replanRestore();
      } else if (d.kind === 'undo') {
        s.undoSites = null;
        s.userWait = null;
        void this.refreshHistory();
      }
    });
    this.subscribeTransfer();
    this.explorer.subscribe();
    on('job:end', (d) => {
      this.ended.add(d.job_id);
      if (d.kind === 'update') s.updateProgress = null;
      if (d.kind === 'phone_cleanup') s.transfer.cleanup = { ...s.transfer.cleanup, running: false };
      if (d.kind === 'restore_apps' && s.transfer.appsBusy) {  // doinstalowanie z Historii skończone: nowy wynik w wierszu
        s.transfer.appsBusy = null;
        void this.loadTransfers();
      }
      if (s.job?.id === d.job_id) s.job = null;
      if (d.kind === 'transfer_scan') this.continueResume();
      if (d.kind === 'backup' && this.offerAfterBackup) {
        const fresh = this.offerAfterBackup;
        this.offerAfterBackup = null;
        this.offerRestoreToNewPhone(fresh);
      }
    });
    on('update:state', (d) => { s.update = d; });
    // Wątek telemetrii usunął dane z serwera po cofnięciu zgody — baner „czeka na połączenie” znika.
    on('telemetry:deleted', () => { s.settings = { ...s.settings, telemetry_delete_pending: false }; });
    on('update:progress', (d) => { s.updateProgress = d; });
    on('app:close_requested', () => { s.closeRequested = true; });
    on('mirror:state', (d) => {
      const active = s.mirror.state === 'starting' || s.mirror.state === 'running';
      // Zdarzenie o innym telefonie, spóźnione względem optymistycznego startu kolejnego — ignoruj je całkiem.
      if (d.serial !== s.mirror.serial && active) return;
      const same = s.mirror.serial === d.serial;
      s.mirror = { ...s.mirror, serial: d.serial, state: d.state, reason: d.reason ?? null,
                   blocked: same && d.state === 'running' ? s.mirror.blocked : false,
                   awakeBlocked: same && d.state === 'running' ? s.mirror.awakeBlocked : false };
      if (d.state === 'failed') s.error = { key: 'mirror_failed', message: d.reason ?? '' };
    });
    on('mirror:warning', (d) => {
      if (s.mirror.serial !== d.serial) return;
      if (d.code === 'control_blocked') s.mirror = { ...s.mirror, blocked: true };
      else if (d.code === 'stay_awake_blocked') s.mirror = { ...s.mirror, awakeBlocked: true };
    });
  }

  // --- podłączanie i skan ---------------------------------------------------------------------

  selectDevice(serial: string): void {
    this.state.serial = serial;
    this.dropOtherCleanup();
  }

  /** Wybrany inny telefon: wynik sprzątania poprzedniego znika (trwające zostaje — most do jego końca
   *  odmawia każdego zadania, więc baner „przywracam” musi być widać). */
  private dropOtherCleanup(): void {
    const s = this.state;
    const c = s.transfer.cleanup;
    if (c.serial && !c.running && s.serial && s.serial !== c.serial) s.transfer.cleanup = { serial: null, running: false, ok: null };
  }

  async startScan(): Promise<void> {
    // ekran wychodzi z eksploratora (telefon wolny dla zadania); trwające zadania — najpierw pytanie, „Zostań” przerywa
    if (this.explorer.state.open && !(await this.explorer.close())) return;
    const s = this.state;
    if (!s.serial) return;
    Object.assign(s, {
      error: null, phase: 'scanning', scanStage: 'identify', device: null, scan: null, plan: null,
      result: null, order: null, disconnectedOrder: null, steps: [], screen: 'main',
    });
    s.apk = { done: 0, total: 0, running: false, changed: [], eta: null };
    s.apkEstimate = null;
    s.apkFullEta = null;
    s.apkQuestion = null;
    s.fixes.clear();
    const r = await this.call(this.api.start_scan(s.serial, s.client.trim() || null));
    if (r) this.setJob(r.job_id, 'scan');
    else s.phase = 'connect';
  }

  async startIncident(seconds = 120): Promise<void> {
    const r = await this.call(this.api.start_incident(seconds));
    if (r && !this.state.incident.result) this.state.incident = { recording: true, marks: 0, result: null };
  }

  async markIncident(): Promise<void> {
    const r = await this.call(this.api.mark_incident());
    if (r) this.state.incident = { ...this.state.incident, marks: this.state.incident.marks + 1 };
  }

  async deepAnalyze(pkg: string): Promise<void> {
    const s = this.state;
    const r = await this.call(this.api.deep_analyze(pkg));
    if (!r) return;
    s.apk = { ...s.apk, done: 0, total: 1, running: true, changed: [], eta: null };
    this.setJob(r.job_id, 'deep');
  }

  newScan(): void {
    // Powrót na ekran Połącz kończy sprawę: zrzut „przed skanem” należy już do następnego zlecenia.
    const serial = this.state.device?.serial ?? this.state.serial;
    if (serial) void this.call(this.api.close_order(serial));
    Object.assign(this.state, {
      phase: 'connect', screen: 'main', device: null, scan: null, result: null, order: null,
      plan: null, selection: {}, actedLog: {}, undoTarget: null, steps: [], disconnectedOrder: null, reports: {},
      categoryFilter: [], sourceFilter: null, lastShot: null, lastShotSerial: null, shotCount: 0,
      openGroups: {}, repairTab: 'apps', diagnostics: false, who: null,
      // Nowa sprawa: nazwisko poprzedniego klienta nie może trafić do protokołu następnego telefonu
      // (audyt 2026-10-11, PRIV-04), a odblokowane pakiety chronione — do jego planu (QA-01).
      client: '', unlocked: [],
    });
    this.state.fixes.clear();
  }

  /** Z Protokołu z powrotem do Naprawy: ten sam skan, kolejne akcje jako nowe zlecenie. */
  backToRepair(): void {
    const s = this.state;
    if (!s.scan || !s.result || s.result.stopped) return;
    // jak przy „Nowe skanowanie”: zrzuty od teraz należą do następnego zlecenia
    const serial = s.device?.serial ?? s.serial;
    if (serial) void this.call(this.api.close_order(serial));
    Object.assign(s, { phase: 'results', screen: 'main', result: null, order: null, execPlan: null, plan: null,
      selection: {}, touched: Object.keys(s.acted), steps: [], lastShot: null, lastShotSerial: null, shotCount: 0 });
    s.fixes.clear(); // reszta wraca niezaznaczona; zrobione poprawki znikają z listy po ponownym odczycie
    void this.recheckSiteNotifications();
    void this.refreshSelectionEta();
  }

  /** Cofa jedną aplikację w jej najnowszym zleceniu, bez wychodzenia z listy wyników. */
  async undoApp(pkg: string): Promise<void> {
    const entry = this.state.actedLog[pkg]?.at(-1);
    if (!entry || this.state.orderRunning) return;
    this.state.undoTarget = pkg; // ustawiane przed undo: zdarzenia mogą przyjść, zanim wróci wywołanie
    await this.undo(entry.order, null, pkg);
  }

  // --- wybór akcji i plan ------------------------------------------------------------------------

  /** Zaznacza albo odznacza poprawkę „Stanu telefonu” (identyfikator z `device_checks`). */
  toggleFix(fix: string): void {
    const fixes = this.state.fixes;
    if (!fixes.delete(fix)) fixes.add(fix);
  }

  /** Odczyt w tle samej kontroli powiadomień witryn (Firefox po włączeniu zdalnego debugowania). Błąd
   *  jednego odczytu nie trafia na kartę błędu: następny przyjdzie za kilka sekund. Przy otwartym planie
   *  albo stronie dla klienta nic nie zmienia: wykonane muszą być te poprawki, które pokazano.
   *  `whenDebugging`: odpytywanie w tle — telefon czyta tylko gniazdo debugowania, pełny odczyt dopiero po
   *  jego pojawieniu się (`check` = null, gdy nic się nie zmieniło). */
  async recheckSiteNotifications(whenDebugging = false): Promise<void> {
    const s = this.state;
    if (s.orderRunning || !s.scan || s.plan || s.share || this.rechecking) return;
    this.rechecking = true;
    let r;
    try {
      r = await this.api.recheck_site_notifications(whenDebugging);
    } catch {
      return;
    } finally {
      this.rechecking = false;
    }
    if (isApiError(r) || !r.check || !s.scan || s.plan || s.share) return; // plan otwarty w trakcie odczytu
    const check = r.check;
    const known = s.scan.device_checks.some((c) => c.id === check.id);
    s.scan = { ...s.scan, device_checks: known ? s.scan.device_checks.map((c) => (c.id === check.id ? check : c))
      : [...s.scan.device_checks, check] };
    // Poprawka, której telefon już nie oferuje (witryna zniknęła), nie może zostać w planie.
    const offered = new Set(offeredFixes(s.scan.device_checks));
    for (const fix of [...s.fixes]) if (!offered.has(fix)) s.fixes.delete(fix);
  }

  setLevel(pkg: string, level: Level | null): void {
    const s = this.state;
    if (level && s.acted[pkg] === 'remove') return; // usunięta w tym zleceniu: nie ma czego zmieniać
    const next = { ...s.selection };
    if (level) next[pkg] = level;
    else delete next[pkg];
    s.selection = next;
    if (!s.touched.includes(pkg)) s.touched = [...s.touched, pkg];
    void this.refreshSelectionEta();
  }

  toggle(app: AppView): void {
    const s = this.state;
    // Tryb ręczny: propozycja silnika wynika z ukrytego werdyktu — tylko po analizie na żądanie jest widoczna.
    const hidden = isManual(s.scan) && !(s.scan?.on_demand ?? []).includes(app.package);
    this.setLevel(app.package, s.selection[app.package] ? null
      : (hidden ? null : app.default_level) ?? this.selectLevel(app));
  }

  /** Wiele zmian naraz (akcje zbiorcze grupy); `null` odznacza. */
  setLevels(levels: Record<string, Level | null>): void {
    const s = this.state;
    const next = { ...s.selection };
    const touched = new Set(s.touched);
    for (const [pkg, level] of Object.entries(levels)) {
      if (level && s.acted[pkg] === 'remove') continue;
      if (level) next[pkg] = level;
      else delete next[pkg];
      touched.add(pkg);
    }
    s.selection = next;
    s.touched = [...touched];
  }

  /** „Zaznacz wszystkie” w grupie: własny wybór zostaje, reszta jak pojedyncze zaznaczenie (toggle). */
  groupSelectLevels(apps: AppView[]): Record<string, Level> {
    const s = this.state;
    const out: Record<string, Level> = {};
    for (const a of apps) {
      if (s.acted[a.package] !== 'remove') out[a.package] = s.selection[a.package] ?? a.default_level ?? this.selectLevel(a);
    }
    return out;
  }

  /** Jedna akcja dla zaznaczonych w grupie; aplikacji producenta zbiorczo nie usuwamy, tylko wyłączamy. */
  groupActionLevels(apps: AppView[], level: Level): Record<string, Level> {
    const s = this.state;
    const out: Record<string, Level> = {};
    for (const a of apps) {
      if (!s.selection[a.package] || s.acted[a.package] === 'remove') continue;
      out[a.package] = a.is_system && level === 'remove' ? 'disable' : level;
    }
    return out;
  }

  /** Akcja z ustawień dla aplikacji bez propozycji silnika; producenta nie usuwamy domyślnie (planner.default_level). */
  private selectLevel(app: AppView): Level {
    let level = this.state.settings.select_level;
    if (level === 'silence' && notificationsManual(this.state.device?.sdk)) level = 'disable'; // komunikat w wynikach
    return app.is_system && level === 'remove' ? 'disable' : level;
  }

  focus(pkg: string | null): void {
    this.state.focused = pkg;
  }

  toggleExpanded(pkg: string): void {
    const s = this.state;
    s.expanded = s.expanded.includes(pkg) ? s.expanded.filter((p) => p !== pkg) : [...s.expanded, pkg];
  }

  setGroupOpen(verdict: Verdict, open: boolean): void {
    this.state.openGroups = { ...this.state.openGroups, [verdict]: open };
  }

  setRepairTab(tab: RepairTab): void {
    this.state.repairTab = tab;
  }

  openDiagnostics(): void {
    this.state.diagnostics = true;
  }

  closeDiagnostics(): void {
    this.state.diagnostics = false;
  }

  setDetailsOpen(open: boolean): void {
    this.state.detailsOpen = open;
  }

  async openPlan(): Promise<void> {
    const s = this.state;
    s.diagnostics = false;
    this.resetShare();
    const r = await this.call(this.api.preview_plan({ ...s.selection }, [...s.unlocked], [...s.fixes]));
    if (r) s.plan = r;
  }

  closePlan(): void {
    this.resetShare();
    this.state.planChanged = false;
    this.state.plan = null;
  }

  /** Kod QR dla klienta (spec plan-qr §6.1). Identyfikator nadaje UI, bo zdarzenie może przyjść
   *  przed wynikiem wywołania. */
  async sharePlan(): Promise<void> {
    const s = this.state;
    this.resetShare();
    s.planChanged = false;
    const id = crypto.randomUUID();
    s.share = { id, code: null, status: 'sending', url: null, mode: null, expires: null, upgraded: false, reason: null };
    const r = await this.call(this.api.share_plan({ ...s.selection }, [...s.unlocked], id, [...s.fixes]));
    if (!r) {
      if (s.share?.id === id) s.share = null;
      return;
    }
    if (s.share?.id === id && s.share.code === null && !this.staleShare(r.code)) s.share = { ...s.share, code: r.code };
  }

  /** Kod z udostępnienia inny niż kod planu na ekranie: telefon zmienił się od podglądu, więc klient
   *  zobaczyłby inny plan niż serwisant. Przeliczamy plan i prosimy o nowy kod (spec plan-qr §6.2). */
  private staleShare(code: string): boolean {
    const s = this.state;
    if (!s.plan?.code || s.plan.code === code) return false;
    s.planChanged = true;
    void this.openPlan();
    return true;
  }

  resetShare(): void {
    const s = this.state;
    if (s.share) void this.call(this.api.cancel_share(s.share.id));
    s.share = null;
    s.consent = false;
  }

  async unlock(pkg: string): Promise<void> {
    this.state.unlocked = [...this.state.unlocked, pkg];
    await this.openPlan();
  }

  // --- wykonanie ------------------------------------------------------------------------------------

  async execute(): Promise<void> {
    const s = this.state;
    s.error = null;
    const consent = s.consent && s.share?.code ? { code: s.share.code } : null;
    const r = await this.call(this.api.execute({ ...s.selection }, [...s.unlocked], consent, [...s.fixes]));
    if (r) this.setJob(r.job_id, 'exec');
    else this.retiredToDialog();
  }

  async stop(): Promise<void> {
    const job = this.state.job;
    if (!job) return;
    this.state.stopping = true;
    await this.call(this.api.stop(job.id));
  }

  /** „Otwórz ponownie na telefonie”: ten sam ekran, czas oczekiwania biegnie dalej. */
  async reopenScreen(): Promise<void> {
    await this.call(this.api.reopen_screen());
  }

  /** „Pomiń” przy witrynie w cofaniu: bieżący ekran przestaje czekać, otwiera się następna witryna. */
  async skipSite(): Promise<void> {
    await this.call(this.api.skip_site());
  }

  /** Strona przywróconego kanału na telefonie: zapisuje go od nowa. Niepowodzenie — baner, nie karta błędu. */
  async openSite(order: string, actionId: number): Promise<void> {
    const s = this.state;
    s.openSiteFailed = false;
    try {
      const r = await this.api.open_site(order, actionId);
      s.openSiteFailed = isApiError(r) || !r.ok;
    } catch {
      s.openSiteFailed = true;
    }
  }

  async answer(value: 'retry' | 'skip'): Promise<void> {
    const q = this.state.question;
    if (!q) return;
    this.state.question = null;
    await this.call(this.api.answer(q.job_id, value));
  }

  async resume(order: string): Promise<void> {
    // ekran wychodzi z eksploratora (telefon wolny dla zadania); trwające zadania — najpierw pytanie, „Zostań” przerywa
    if (this.explorer.state.open && !(await this.explorer.close())) return;
    const s = this.state;
    s.error = null;
    // zlecenie znika z „przerwanych” dopiero z `exec:order`: nieudane wznowienie zostawia je
    const r = await this.call(this.api.resume(order));
    if (r) this.setJob(r.job_id, 'resume');
    else this.retiredToDialog();
  }

  async undo(order: string, actionId: number | null = null, pkg: string | null = null): Promise<void> {
    const s = this.state;
    s.error = null;
    s.undoSteps = [];
    s.undoResult = null;
    s.undoSites = null;
    s.openSiteFailed = false;
    s.undoing = actionId === null ? { order, pkg } : null;
    const r = await this.call(this.api.undo(order, actionId, pkg));
    if (r) this.setJob(r.job_id, 'undo');
    else s.undoing = s.undoTarget = null;
  }

  // --- przenoszenie danych: kopia starego telefonu --------------------------------------------------

  private subscribeTransfer(): void {
    const on = this.bridge.on;
    const s = this.state;
    on('transfer:inventory', (d) => {
      if (s.phase !== 'transfer_choose') return; // serwisant już wyszedł z przenoszenia
      const prev = s.transfer.inventory; // jest tylko po „Sprawdź ponownie” (`startTransfer` czyści stan)
      s.transfer.selection = prev ? rescanSelection(s.transfer.selection, prev, d.inventory)
        : resumeSelection(d.inventory, d.resumable?.selection, s.settings.transfer_apps_default);
      s.transfer.inventory = d.inventory;
      s.transfer.resumable = d.resumable;
      s.phase = 'transfer_choose';
    });
    on('transfer:progress', (d) => {
      s.transfer.progress = d;
      s.transfer.waiting = false;
    });
    on('transfer:waiting', () => { s.transfer.waiting = true; });
    on('transfer:copy', (d) => { s.transfer.copy = d.copy; });
    on('transfer:done', (d) => {
      s.transfer.result = d.result;
      s.transfer.copy = d.copy;
      s.transfer.waiting = false;
      s.stopping = false;
      s.phase = 'transfer_done';
      // nowy telefon podłączony już w czasie kopii: karta „Podłącz nowy telefon” obiecuje przejście od razu
      this.offerRestoreToNewPhone(s.devices.filter((e) => e.state === 'device').map((e) => e.serial));
    });
    on('transfer:restore_plan', (d) => {
      if (s.phase !== 'transfer_restore_plan') return; // serwisant już wyszedł z ekranu wgrywania
      const kept = this.replanChoice;
      this.replanChoice = null;
      const tel = d.tel ?? null;
      const apps = d.apps ?? null;  // starsze nagrania mostu nie mają aplikacji
      Object.assign(s.transfer.restore, { plan: d.plan, copy: d.copy, tel, apps,
        choice: kept ? keptUploadChoice(d.plan, kept, tel, apps) : defaultUploadChoice(d.plan, tel, s.settings.verify_copies, apps),
        resumable: d.resumable, sameRecent: d.same_phone_recent });
    });
    on('transfer:restore_progress', (d) => {
      s.transfer.restore.progress = d;
      s.transfer.waiting = false;
    });
    on('transfer:tel_progress', (d) => {
      s.transfer.restore.telProgress = d;
      s.transfer.waiting = false;
    });
    on('transfer:tap', (d) => {
      const r = s.transfer.restore;
      r.tap = d.request;
      r.tapPackage = d.package;
    });
    // Ponowienie po nieudanej próbie tego samego telefonu zostaje czerwonym banerem (bez migania na żółto).
    on('transfer:cleanup_started', (d) => {
      const c = s.transfer.cleanup;
      s.transfer.cleanup = { serial: d.serial, running: true, ok: c.serial === d.serial ? c.ok : null };
    });
    // Nieudane sprzątanie most ponawia w tle (najwyżej 3 razy): ten sam stan, jeden baner (nic się nie piętrzy).
    on('transfer:cleanup_done', (d) => {
      s.transfer.cleanup = { serial: d.serial, running: false, ok: d.ok };
      s.transfer.restore.tap = null;
    });
    on('transfer:apps_progress', (d) => {
      s.transfer.restore.appsProgress = d;
      s.transfer.waiting = false;
    });
    // Dokończenie aplikacji po odblokowaniu Xiaomi: nowy wynik zastępuje stary w tym samym zleceniu.
    on('transfer:apps_done', (d) => {
      const r = s.transfer.restore;
      if (r.order !== d.order) return;
      // nadal zablokowane: kolejne odblokowanie uruchomi dokończenie jeszcze raz
      Object.assign(r, { appsResult: d.apps, appsProgress: null, appsError: null, reinstallGaveUp: false, reinstallDone: !d.apps.blocked, awaitBlock: d.apps.blocked });
    });
    on('transfer:restore_done', (d) => {
      Object.assign(s.transfer.restore, { result: d.result, copy: d.copy, telResult: d.tel ?? null,
        telError: d.tel_error ?? null, tap: null, appsResult: d.apps ?? null, appsError: d.apps_error ?? null, reinstallGaveUp: false,
        appsProgress: null, order: d.order ?? null, whatsapp: d.whatsapp ?? null, whatsappRestored: false, reinstallDone: false, awaitBlock: false });
      s.transfer.copies = s.transfer.copies.map((c) => (c.id === d.copy.id ? d.copy : c));
      s.transfer.waiting = false;
      s.stopping = false;
      s.phase = 'transfer_restored';
    });
  }

  private resetTransfer(): void {
    const tr = this.state.transfer;
    Object.assign(tr, { inventory: null, resumable: null, selection: { ...EMPTY_TRANSFER_SELECTION }, progress: null,
      waiting: false, result: null, copy: null, restore: emptyRestore() });
  }

  /** „Kopiuj dane” na ekranie Połącz: inwentarz wybranego telefonu, potem ekran wyboru. `resume` („Wznów”
   *  z banera): po inwentarzu kopia rusza od razu z zapisanym wyborem — patrz `continueResume`. */
  async startTransfer(resume = false): Promise<void> {
    // ekran wychodzi z eksploratora (telefon wolny dla zadania); trwające zadania — najpierw pytanie, „Zostań” przerywa
    if (this.explorer.state.open && !(await this.explorer.close())) return;
    const s = this.state;
    if (!s.serial) return;
    this.resetTransfer();
    this.resumeAfterScan = resume;
    Object.assign(s, { error: null, device: null, screen: 'main', phase: 'transfer_choose', stopping: false });
    const r = await this.call(this.api.transfer_inventory(s.serial, s.client.trim() || null));
    if (r) this.setJob(r.job_id, 'transfer_scan');
    else s.phase = 'connect';
  }

  /** Koniec odczytu po „Wznów”: kopia rusza, jeśli most znalazł ją do wznowienia, jest co kopiować i starczy
   *  miejsca. W przeciwnym razie zostaje ekran wyboru — tam baner i ostrzeżenia mówią, co dalej. */
  private continueResume(): void {
    const s = this.state;
    const tr = s.transfer;
    const resume = this.resumeAfterScan;
    this.resumeAfterScan = false;
    if (!resume || s.phase !== 'transfer_choose' || !tr.inventory || !tr.resumable) return;
    const totals = transferTotals(tr.inventory, tr.selection);
    if (totals.categories === 0 || transferNeed(totals.bytes, tr.resumable) > tr.inventory.free_pc) return;
    void this.startBackup();
  }

  /** Wiersz ekranu wyboru: kontakty, SMS i MMS (razem), połączenia, kategorie plików, inne foldery, aplikacje. */
  toggleTransfer(key: string): void {
    const tr = this.state.transfer;
    const inv = tr.inventory;
    const sel = { ...tr.selection };
    if (key === 'contacts' || key === 'calls') {
      sel[key] = !sel[key];
    } else if (key === 'sms') {
      const on = !(sel.sms || sel.mms);
      const fromFile = !!sel.exports?.sms;
      sel.sms = on && ((inv?.sms ?? 0) > 0 || fromFile);
      sel.mms = on && (inv?.mms ?? 0) > 0 && !fromFile;
    } else if (key === 'others') {
      sel.others = sel.others.length ? [] : (inv?.others ?? []).map((o) => o.name);
    } else if (key === 'apps') {
      // ponowne zaznaczenie: domyślne aplikacje, a gdy żadna nie jest domyślna — wszystkie (wiersz zawsze coś robi)
      const all = inv?.apps ?? [];
      const defaults = all.filter((a) => a.default_on);
      sel.apps = sel.apps.length ? [] : (defaults.length ? defaults : all).map((a) => a.package);
    } else if ((TRANSFER_CATEGORIES as readonly string[]).includes(key)) {
      const cat = key as TransferCategory;
      sel.categories = sel.categories.includes(cat) ? sel.categories.filter((c) => c !== cat)
        : TRANSFER_CATEGORIES.filter((c) => c === cat || sel.categories.includes(c));
    } else {
      return;
    }
    tr.selection = sel;
  }

  toggleTransferApp(pkg: string): void {
    const sel = this.state.transfer.selection;
    this.state.transfer.selection = { ...sel, apps: sel.apps.includes(pkg) ? sel.apps.filter((p) => p !== pkg) : [...sel.apps, pkg] };
  }

  toggleTransferOther(name: string): void {
    const sel = this.state.transfer.selection;
    this.state.transfer.selection = { ...sel,
      others: sel.others.includes(name) ? sel.others.filter((o) => o !== name) : [...sel.others, name] };
  }

  /** Inny plik eksportu z listy w banerze; wybór pliku zaznacza też jego wiersz (SMS z pliku — bez MMS). */
  chooseExport(kind: ExportKind, remote: string): void {
    const sel = this.state.transfer.selection;
    this.state.transfer.selection = { ...sel, [kind]: true, ...(kind === 'sms' ? { mms: false } : {}),
      exports: { ...sel.exports, [kind]: remote } };
  }

  /** „Sprawdź ponownie”: serwisant wyeksportował dane do pliku. Nowy inwentarz przychodzi jak zwykle
   *  (`transfer:inventory`) i zachowuje wybór — patrz `rescanSelection`. */
  async rescanTransfer(): Promise<void> {
    const s = this.state;
    if (s.phase !== 'transfer_choose' || !s.transfer.inventory || s.job) return;
    s.error = null;
    const r = await this.call(this.api.transfer_rescan());
    if (r) this.setJob(r.job_id, 'transfer_scan');
  }

  /** Automatyczne sprawdzanie pod otwartą instrukcją eksportu: tani odczyt (bez zadania), wynik wchodzi do
   *  bieżącego inwentarza, a wybór serwisanta zostaje (`rescanSelection`). */
  async checkExports(): Promise<void> {
    const s = this.state;
    if (s.phase !== 'transfer_choose' || !s.transfer.inventory || s.job) return;
    const r = await this.quiet(this.api.transfer_exports_check());
    const prev = s.transfer.inventory;
    if (!r || !prev || s.phase !== 'transfer_choose') return;
    const next = { ...prev, ...r };
    s.transfer.selection = rescanSelection(s.transfer.selection, prev, next);
    s.transfer.inventory = next;
  }

  /** Auto-sprawdzanie w tle (co `RECHECK_MS`): czy serwisant zrobił już kopię czatów WhatsApp na telefonie. Cichy. */
  async recheckWhatsapp(): Promise<void> {
    const r = await this.quiet(this.api.transfer_whatsapp());
    const inv = this.state.transfer.inventory;
    if (r && inv) this.state.transfer.inventory = { ...inv, whatsapp_backup: r.whatsapp_backup };
  }

  /** Kopia zaznaczonych danych; niedokończona kopia tego telefonu jest wznawiana przez most (z bieżącym wyborem). */
  async startBackup(): Promise<void> {
    const s = this.state;
    const sel = s.transfer.selection;
    s.error = null;
    // Plik eksportu tylko dla zaznaczonego wiersza (most odrzuca plik przy wyłączonej fladze).
    const exports = Object.fromEntries(Object.entries(sel.exports ?? {}).filter(([k]) => sel[k as ExportKind]));
    // Przed wywołaniem: `transfer:copy` z wątku kopii może przyjść, zanim wróci odpowiedź.
    s.transfer.copy = null;
    const r = await this.call(this.api.start_backup({
      contacts: sel.contacts, sms: sel.sms, mms: sel.mms && !exports.sms, calls: sel.calls,
      categories: [...sel.categories], others: [...sel.others], apps: [...sel.apps],
      ...(Object.keys(exports).length ? { exports } : {}),
    }));
    if (!r) return;
    Object.assign(s.transfer, { progress: null, waiting: false, result: null });
    s.stopping = false;
    s.phase = 'transfer_backup';
    this.setJob(r.job_id, 'backup');
  }

  /** „Przerwij” (także w czasie czekania na telefon): kopia kończy się `transfer:done` ze statusem „stopped”. */
  async stopBackup(): Promise<void> {
    const job = this.state.job;
    if (job?.kind !== 'backup') return;
    this.state.stopping = true;
    await this.call(this.api.stop(job.id));
  }

  /** Z przenoszenia z powrotem na ekran Połącz (odczyt inwentarza w toku jest przerywany). */
  leaveTransfer(): void {
    const s = this.state;
    if (s.job?.kind === 'transfer_scan') void this.call(this.api.stop(s.job.id));
    this.resetTransfer();
    Object.assign(s, { phase: 'connect', screen: 'main', device: null, stopping: false });
  }

  /** Po błędzie kopii jest ona niedokończona: baner „Wznów” dostaje najnowszą niedokończoną kopię tego telefonu
   *  (most wznowi właśnie ją — `find_resumable`). Bez trafienia zostaje dotychczasowa. */
  private async refreshResumable(): Promise<void> {
    const s = this.state;
    const r = await this.call(this.api.transfers());
    if (!r) return;
    s.transfer.copies = r.copies;
    const copy = resumableCopy(r.copies, s.device?.serial ?? s.serial);
    if (copy && s.phase === 'transfer_choose') s.transfer.resumable = copy;
  }

  // --- przenoszenie danych: wgrywanie kopii na nowy telefon ------------------------------------------

  /** „Wgraj” (Połącz albo Historia): plan wgrywania kopii na wybrany telefon, potem ekran wyboru. */
  async planRestore(copyId: string): Promise<void> {
    // ekran wychodzi z eksploratora (telefon wolny dla zadania); trwające zadania — najpierw pytanie, „Zostań” przerywa
    if (this.explorer.state.open && !(await this.explorer.close())) return;
    const s = this.state;
    if (!s.serial) return;
    this.resetTransfer();
    this.replanChoice = null;
    s.transfer.restore.copy = s.transfer.copies.find((c) => c.id === copyId) ?? null;
    Object.assign(s, { error: null, device: null, screen: 'main', phase: 'transfer_restore_plan', stopping: false });
    const r = await this.call(this.api.restore_plan(copyId, s.serial));
    if (r) this.setJob(r.job_id, 'restore_plan');
    else s.phase = 'connect';
  }

  /** Ponowny plan po braku miejsca: bez czyszczenia błędu i stanu (inaczej niż `planRestore`). */
  private async replanRestore(): Promise<void> {
    const s = this.state;
    const r = s.transfer.restore;
    if (!r.copy || !s.serial) return;
    this.replanChoice = r.choice;
    r.plan = null;
    const res = await this.call(this.api.restore_plan(r.copy.id, s.serial));
    if (res) this.setJob(res.job_id, 'restore_plan');
    else this.replanChoice = null;
  }

  /** Grupa plików (`photos`…, `other:<folder>`) albo `others` — wszystkie inne foldery naraz. */
  toggleUploadGroup(key: string): void {
    const r = this.state.transfer.restore;
    if (!r.plan) return;
    const groups = new Set(r.choice.groups);
    const others = r.plan.others.map((o) => otherGroup(o.name));
    const known = [...UPLOAD_GROUPS.filter((g) => g in r.plan!.groups), ...others]; // kolejność jak na ekranie
    if (key === 'others') {
      const on = !others.some((g) => groups.has(g));
      for (const g of others) if (on) groups.add(g); else groups.delete(g);
    } else if (known.includes(key)) {
      if (!groups.delete(key)) groups.add(key);
    } else {
      return;
    }
    r.choice = { ...r.choice, groups: known.filter((g) => groups.has(g)) };
  }

  /** Podejrzany APK (domyślnie odznaczony); szkodliwego nie da się zaznaczyć, domyślne idą z grupą. */
  toggleUploadApk(remote: string): void {
    const r = this.state.transfer.restore;
    const apk = r.plan?.apks.find((a) => a.remote === remote);
    if (!apk || apk.outcome === 'malicious' || apk.default_on) return;
    const on = r.choice.apks_on;
    r.choice = { ...r.choice, apks_on: on.includes(remote) ? on.filter((x) => x !== remote) : [...on, remote] };
  }

  /** Aplikacja z kopii; tej z powodem pominięcia (`skip`) nie da się zaznaczyć. */
  toggleRestoreApp(pkg: string): void {
    const r = this.state.transfer.restore;
    if (!installableApps(r.apps).some((a) => a.package === pkg)) return;
    const on = r.choice.apps;
    r.choice = { ...r.choice, apps: on.includes(pkg) ? on.filter((p) => p !== pkg) : [...on, pkg] };
  }

  /** Wiersz „Aplikacje”: odznacza wszystkie albo wraca do domyślnych (gdy żadna nie jest domyślna — wszystkie do wgrania). */
  toggleRestoreApps(): void {
    const r = this.state.transfer.restore;
    const all = installableApps(r.apps).map((a) => a.package);
    const defaults = defaultApps(r.apps);
    r.choice = { ...r.choice, apps: r.choice.apps.length ? [] : (defaults.length ? defaults : all) };
  }

  /** Automatyczne sprawdzanie blokady instalacji przez USB (Xiaomi): tani odczyt bez zadania; gdy blokady już nie
   *  ma, etykieta znika z planu. Nieznany wynik (`null`) nie zmienia niczego. */
  async checkInstall(): Promise<void> {
    const s = this.state;
    if (s.phase !== 'transfer_restore_plan' || !s.transfer.restore.apps?.block || s.job) return;
    const res = await this.quiet(this.api.install_check());
    const apps = s.transfer.restore.apps;
    if (res && res.blocked === false && s.phase === 'transfer_restore_plan' && apps?.block) {
      s.transfer.restore.apps = { ...apps, block: null };
    }
  }

  /** Ekran „Dane przeniesione”, blokada Xiaomi w wyniku: póki telefon jest podłączony, tani odczyt `install_check` w tle
   *  (wywoływany co `RECHECK_MS`). Gdy blokada zniknęła, raz uruchamia dokończenie samych pominiętych aplikacji.
   *  Cichy: żadnego błędu na ekran, nieznany wynik nic nie zmienia, zwykłych błędów instalacji nie ponawia. */
  async reinstallWhenUnblocked(): Promise<void> {
    const s = this.state;
    const r = s.transfer.restore;
    const order = r.order;
    const target = r.result?.target_serial;
    if (s.phase !== 'transfer_restored' || !order || !target || !r.appsResult?.blocked || r.reinstallDone || s.job) return;
    if (!s.devices.some((e) => e.serial === target && e.state === 'device')) return;
    try {
      const check = await this.api.install_check();
      if (isApiError(check)) return;
      if (check.blocked === true) r.awaitBlock = false;  // zobaczyliśmy blokadę: następne „odblokowane” to nowe przejście
      if (check.blocked !== false || r.awaitBlock) return;
      if (r.reinstallDone || s.phase !== 'transfer_restored' || s.job) return;
      r.reinstallDone = true;
      const res = await this.api.install_remaining_apps(order);
      if (!isApiError(res)) {
        r.appsError = null;
        this.setJob(res.job_id, 'restore_apps');
      } else if (REINSTALL_TRANSIENT.includes(res.error.key)) r.reinstallDone = false;
      else Object.assign(r, { appsError: res.error.key, reinstallGaveUp: true });  // np. kopia usunięta: bez obietnicy, powód w wierszu
    } catch {
      // następna próba za RECHECK_MS (jeśli zadanie jeszcze nie ruszyło)
    }
  }

  /** Pole „Czaty przywrócone” na ekranie wyniku: zapis w zleceniu (trafia do protokołu). */
  private whatsappSeq = 0;
  async setWhatsappRestored(on: boolean): Promise<void> {
    const r = this.state.transfer.restore;
    if (!r.order) return;
    const before = r.whatsappRestored;
    const seq = ++this.whatsappSeq;
    r.whatsappRestored = on;
    const res = await this.call(this.api.set_whatsapp_restored(r.order, on));
    if (seq !== this.whatsappSeq) return;  // późniejsze kliknięcie rozstrzyga o polu
    r.whatsappRestored = res ? res.whatsapp_restored : before;
  }

  /** Wiersz telefonii (kontakty, SMS z MMS, połączenia); bez rekordów do wgrania nie da się go zaznaczyć. */
  toggleTel(kind: TelKind): void {
    const r = this.state.transfer.restore;
    if (!TEL_KINDS.includes(kind) || !((telWrite(r.tel, kind) ?? 0) > 0)) return;
    const on = new Set(r.choice.tel);
    if (!on.delete(kind)) on.add(kind);
    r.choice = { ...r.choice, tel: TEL_KINDS.filter((k) => on.has(k)) };
  }

  /** „Pomiń (zostawię plik do importu)” przy prośbie o rolę SMS: wiadomości trafią do pliku. Oddania roli
   *  poprzedniej aplikacji pominąć się nie da (most odmawia `bad_request`/`restore_required` — baner zostaje);
   *  `no_tap` — prośba już minęła. */
  async skipTap(): Promise<void> {
    const r = this.state.transfer.restore;
    if (r.tap !== 'sms_role_grant') return;
    try {
      const res = await this.api.skip_tap();
      const reason = isApiError(res) && res.error.key === 'bad_request' ? res.error.message : null;
      if (!isApiError(res) || reason === 'no_tap') r.tap = null;
      else if (reason !== 'restore_required') this.state.error = res.error;
    } catch (e) {
      this.state.error = { key: 'internal', message: String(e) };
    }
  }

  /** Wgrywanie wybranych plików; przerwane wgrywanie tej kopii na ten telefon most wznawia sam. */
  async startRestore(): Promise<void> {
    const s = this.state;
    const choice = s.transfer.restore.choice;
    s.error = null;
    const r = await this.call(this.api.start_restore({ groups: [...choice.groups], apks_on: [...choice.apks_on],
      verify_hash: choice.verify_hash, tel: [...choice.tel], apps: [...choice.apps] }));
    if (!r) return;
    Object.assign(s.transfer.restore, { progress: null, result: null, telProgress: null, telResult: null, telError: null,
      tap: null, appsProgress: null, appsResult: null, appsError: null, order: null, whatsapp: null, whatsappRestored: false,
      reinstallDone: false, reinstallGaveUp: false, awaitBlock: false });
    s.transfer.waiting = false;
    s.stopping = false;
    s.phase = 'transfer_restore';
    this.setJob(r.job_id, 'restore');
  }

  /** „Przerwij” (także w czasie czekania na telefon): wgrywanie kończy się `transfer:restore_done` ze statusem „stopped”. */
  async stopRestore(): Promise<void> {
    const job = this.state.job;
    if (job?.kind !== 'restore') return;
    this.state.stopping = true;
    await this.call(this.api.stop(job.id));
  }

  async loadTransfers(): Promise<void> {
    const r = await this.call(this.api.transfers());
    if (!r) return;
    this.state.transfer.copies = r.copies;
    this.state.transfer.orders = r.orders ?? [];
  }

  async extendTransfer(id: string): Promise<void> {
    const r = await this.call(this.api.extend_transfer(id));
    if (!r) return;
    this.state.transfer.copies = this.state.transfer.copies.map((c) => (c.id === id ? r.copy : c));
    this.state.transfer.orders = this.state.transfer.orders.map((o) => (o.copy?.id === id && !o.copy.deleted_at
      ? { ...o, copy: { ...o.copy, days_left: r.copy.days_left } } : o));
  }

  /** „Czaty WhatsApp przywrócone” z menu wiersza w Historii: zapis w zleceniu (trafia do protokołu). */
  private historyWhatsappSeq = 0;
  async setOrderWhatsapp(number: string, on: boolean): Promise<void> {
    const apply = (value: boolean) => {
      this.state.transfer.orders = this.state.transfer.orders.map((o) => (o.number === number ? { ...o, whatsapp_restored: value } : o));
    };
    const before = this.state.transfer.orders.find((o) => o.number === number)?.whatsapp_restored ?? false;
    const seq = ++this.historyWhatsappSeq;
    apply(on);
    const res = await this.call(this.api.set_whatsapp_restored(number, on));
    if (seq !== this.historyWhatsappSeq) return;  // późniejsze kliknięcie rozstrzyga o polu
    apply(res ? res.whatsapp_restored : before);
  }

  /** „Doinstaluj aplikacje” z menu wiersza w Historii: tylko aplikacje pominięte z powodu blokady, na telefonie celu.
   *  Cicho: odmowa to krótka uwaga w wierszu (`transfer.appsNotes`), nie baner; wynik odświeża listę (`job:end`). */
  async reinstallFromHistory(number: string): Promise<string | null> {
    const tr = this.state.transfer;
    if (this.state.job) return null;
    tr.appsNotes = Object.fromEntries(Object.entries(tr.appsNotes).filter(([k]) => k !== number));
    let res;
    try {
      res = await this.api.install_remaining_apps(number);
    } catch {
      res = null;
    }
    if (!res || isApiError(res)) {
      const key = res ? res.error.key : 'internal';
      tr.appsNotes = { ...tr.appsNotes, [number]: key };
      return key;
    }
    tr.appsBusy = number;
    this.setJob(res.job_id, 'restore_apps');
    return null;
  }

  /** Zapis notatki do kopii; `true` po udanym zapisie (pole edycji się zamyka). */
  async setTransferNote(id: string, note: string | null): Promise<boolean> {
    const r = await this.call(this.api.set_transfer_note(id, note));
    if (!r) return false;
    const tr = this.state.transfer;
    tr.copies = tr.copies.map((c) => (c.id === id ? r.copy : c));
    if (tr.copy?.id === id) tr.copy = r.copy;
    return true;
  }

  async deleteTransfer(id: string): Promise<void> {
    const r = await this.call(this.api.delete_transfer(id));
    if (!r) return;
    this.state.transfer.copies = this.state.transfer.copies.filter((c) => c.id !== id);
    await this.loadTransfers();  // wiersz zlecenia zostaje („kopia usunięta DD.MM”), znika tylko kopia bez zlecenia
  }

  // --- aktualizacje ------------------------------------------------------------------------------

  /** Błąd `retired` przy zmianach na telefonie otwiera okno instalacji (jeśli jest co instalować). */
  private retiredToDialog(): void {
    const s = this.state;
    if (s.error?.key !== 'retired' || !s.update?.available) return;
    s.error = null;
    this.openUpdate();
  }

  openUpdate(): void {
    this.state.updateError = null;
    this.state.updateDialog = true;
  }

  closeUpdate(): void {
    if (this.state.job?.kind === 'update') return; // najpierw Anuluj pobieranie
    this.state.updateDialog = false;
  }

  async installUpdate(): Promise<void> {
    const s = this.state;
    s.updateError = null;
    const r = await this.call(this.api.install_update());
    if (!r) {
      s.updateError = s.error; // busy / update_none — w oknie, nie na karcie błędu
      s.error = null;
      return;
    }
    if ('job_id' in r) {
      s.updateProgress = { done: 0, total: null };
      this.setJob(r.job_id, 'update');
    } else {
      s.updateDialog = false; // wersja deweloperska: otwarto stronę pobierania
    }
  }

  async cancelUpdate(): Promise<void> {
    const job = this.state.job;
    if (job?.kind === 'update') await this.call(this.api.stop(job.id));
  }

  async dismissUpdate(): Promise<void> {
    const version = this.state.update?.available?.version;
    if (!version) return;
    const r = await this.call(this.api.dismiss_update(version));
    if (r) this.state.update = r;
  }

  dismissUpdated(): void {
    this.state.updatedSeen = true;
  }

  // --- raporty błędów (spec raportów błędów §5) -------------------------------------------
  // Błędy okna raportu zostają w oknie (crashError), nie trafiają na kartę błędu.

  async loadCrashes(): Promise<void> {
    const r = await this.call(this.api.crash_reports());
    if (r) this.state.crashStartup = r.startup;
  }

  private screenName(): string {
    const s = this.state;
    return s.screen !== 'main' ? s.screen : s.phase;
  }

  async captureUiError(message: string, stack: string | null): Promise<void> {
    if (this.state.fatalCrash || this.uiErrorSent) return; // kaskada błędów: jeden raport
    this.uiErrorSent = true;
    try {
      const r = await this.api.capture_ui_error(message, stack, this.screenName());
      if (!isApiError(r) && r.crash) this.state.fatalCrash = r.crash;
    } catch {
      // most nie działa — zostaje sam ekran błędu
    }
  }

  openCrash(id: string): void {
    const s = this.state;
    Object.assign(s, { crashDialog: id, crashAdb: false, crashComment: '', crashPreview: null,
      crashHasAdb: false, crashSending: false, crashSent: null, crashError: null });
    void this.previewCrash();
  }

  async previewCrash(): Promise<void> {
    const s = this.state;
    const id = s.crashDialog;
    if (!id) return;
    try {
      const r = await this.api.crash_preview(id, s.crashAdb, s.crashComment);
      if (s.crashDialog !== id) return;
      if (isApiError(r)) { s.crashError = r.error; return; }
      s.crashPreview = r.body;
      s.crashHasAdb = r.has_adb;
    } catch (e) {
      s.crashError = { key: 'internal', message: String(e) };
    }
  }

  async sendCrash(): Promise<void> {
    const s = this.state;
    const id = s.crashDialog;
    if (!id || s.crashSending || s.crashSent) return;
    s.crashSending = true;
    s.crashError = null;
    try {
      const r = await this.api.send_crash(id, s.crashAdb, s.crashComment);
      if (isApiError(r)) s.crashError = r.error;
      else { s.crashSent = r.sent_id; this.forgetCrash(id); }
    } catch (e) {
      s.crashError = { key: 'internal', message: String(e) };
    } finally {
      s.crashSending = false;
    }
  }

  closeCrash(): void {
    const s = this.state;
    if (s.crashSending) return;
    if (s.crashDialog) this.forgetCrash(s.crashDialog);
    s.crashDialog = null;
  }

  async discardCrash(id?: string): Promise<void> {
    const s = this.state;
    const target = id ?? s.crashDialog;
    if (!target) return;
    await this.call(this.api.discard_crash(target));
    this.forgetCrash(target);
    if (s.crashDialog === target) s.crashDialog = null;
    if (s.error?.crash === target) s.error = { ...s.error, crash: undefined };
    if (s.fatalCrash === target) s.fatalCrash = null;
  }

  private forgetCrash(id: string): void {
    this.state.crashStartup = this.state.crashStartup.filter((x) => x !== id);
  }

  // --- historia, ustawienia, konsola -------------------------------------------------------------

  async openHistory(serial: string | null = null, tab: HistoryTab = 'orders'): Promise<void> {
    const s = this.state;
    s.screen = 'history';
    s.historyTab = tab;
    s.undoResult = null;
    void this.loadTransfers();
    await this.refreshHistory(serial ?? s.history?.serial ?? s.device?.serial ?? null);
  }

  async refreshHistory(serial: string | null = this.state.history?.serial ?? null): Promise<void> {
    const r = await this.call(this.api.history(serial));
    if (r) this.state.history = r;
  }

  /** Baner przerwanego zlecenia znika do następnego skanu; zlecenie zostaje w Historii. */
  hideInterrupted(order: string): void {
    this.state.interrupted = this.state.interrupted.filter((o) => o !== order);
  }

  async deleteOrder(order: string): Promise<void> {
    const r = await this.call(this.api.delete_order(order));
    if (!r) return;
    this.state.interrupted = this.state.interrupted.filter((o) => o !== order);
    await this.refreshHistory();
  }

  /** Bez argumentu: ostatnia kategoria z tej sesji okna (na start „Ogólne”). */
  openSettings(category?: SettingsCategory): void {
    if (category) {
      this.state.settingsCategory = category;
      this.state.settingsOpened += 1;
    }
    this.state.screen = 'settings';
  }

  /** Z Historii i Ustawień: do otwartego eksploratora (sesja trwa), inaczej do głównego ekranu. */
  back(): void {
    this.state.screen = this.explorer.state.open ? 'explorer' : 'main';
  }

  /**
   * Nigdy nie odrzuca obietnicy: błąd mostu trafia na kartę błędu, a wynik to `null`
   * (przełączniki w Ustawieniach wracają wtedy do zapisanej wartości i nie ma „✓ Zapisano”).
   */
  async saveSettings(changes: Partial<Settings>): Promise<Settings | null> {
    const r = await this.call(this.api.save_settings(changes));
    if (!r) return null;
    this.applySettings(r);
    this.state.settingsSaved = Date.now();
    if ('explorer_dest_mode' in changes || 'explorer_dest_fixed' in changes) this.explorer.syncDest();
    if ('lang' in changes) {
      const view = await this.call(this.api.rerender());
      if (view?.scan) this.state.scan = view.scan;
      if (this.state.screen === 'history') await this.refreshHistory();
    }
    return r;
  }

  async acceptWelcome(telemetry: boolean, packages: boolean): Promise<void> {
    const r = await this.call(this.api.accept_welcome(telemetry, packages));
    if (r) this.applySettings(r);
  }

  async setTelemetry(telemetry: boolean, packages: boolean): Promise<void> {
    const r = await this.call(this.api.set_telemetry(telemetry, packages && telemetry));
    if (!r) return;
    this.applySettings(r);
    this.state.settingsSaved = Date.now();
  }

  telemetrySample(): Promise<TelemetrySample | null> {
    return this.call(this.api.telemetry_sample());
  }

  async openPrivacy(): Promise<void> {
    await this.call(this.api.open_privacy());
  }

  async openDonate(): Promise<void> {
    await this.call(this.api.open_donate());
  }

  async setDonateReminders(on: boolean): Promise<void> {
    const r = await this.call(this.api.set_donate_reminders(on));
    if (!r) return;
    this.applySettings(r);
    this.state.settingsSaved = Date.now();
  }

  closeDonate(): void {
    this.state.donateBanner = false;
  }

  setMode(mode: Mode): Promise<Settings | null> {
    this.state.openGroups = {}; // nowy tryb — jego domyślne rozwinięcie grup
    return this.saveSettings({ mode });
  }

  setLang(lang: Lang): Promise<Settings | null> {
    return this.saveSettings({ lang });
  }

  async answerApk(value: 'clear' | 'skip' | 'run'): Promise<void> {
    const q = this.state.apkQuestion;
    if (!q || q.kind !== 'no_space') return;
    this.state.apkQuestion = null;
    await this.call(this.api.answer(q.job_id, value));
  }

  async chooseApkMode(mode: 'full' | 'manual', remember: boolean): Promise<void> {
    const s = this.state;
    const q = s.apkQuestion;
    if (!q || q.kind !== 'mode') return;
    s.apkQuestion = null;
    if (mode === 'full') {
      s.apkFullChosen = true;
      // Werdykty heurystyk są od teraz widoczne: propozycje jak przed trybem ręcznym, zmiany serwisanta zostają.
      if (s.scan) s.selection = mergeSelection(s.selection, s.scan.apps, s.touched);
    }
    if (remember) await this.saveSettings({ apk_mode_default: mode });
    await this.call(this.api.answer(q.job_id, mode));
  }

  /** Wybrana pełna analiza skończyła się bez apk:done: raport szybkiego skanu z propozycjami jak przed trybem ręcznym. */
  private fullEndedWithoutReport(): void {
    const s = this.state;
    if (s.apkFullChosen && s.scan?.apk_mode === 'pending') s.selection = mergeSelection(s.selection, s.scan.apps, s.touched);
  }

  async analyzeSelected(): Promise<void> {
    const s = this.state;
    const pkgs = Object.keys(s.selection);
    if (!pkgs.length) return;
    const r = await this.call(this.api.analyze_selected(pkgs));
    if (!r) return;
    s.apk = { done: 0, total: pkgs.length, running: true, changed: [], eta: s.selectionEta?.eta_s ?? null };
    s.apkScope = 'selected';
    this.setJob(r.job_id, 'apk');
  }

  async analyzeAll(): Promise<void> {
    const s = this.state;
    const r = await this.call(this.api.analyze_all());
    if (!r) return;
    s.apk = { done: 0, total: 0, running: true, changed: [], eta: null };
    s.apkScope = 'all';
    this.setJob(r.job_id, 'apk');
  }

  async stopToManual(): Promise<void> {
    await this.call(this.api.stop_apk_to_manual());
  }

  /** Czas analizy zaznaczonych (tryb ręczny). Tylko dopisek przy przycisku: błąd nie trafia do banera. */
  async refreshSelectionEta(): Promise<void> {
    const s = this.state;
    const seq = ++this.etaSeq;
    const pkgs = Object.keys(s.selection);
    if (!isManual(s.scan) || !pkgs.length) {
      s.selectionEta = null;
      return;
    }
    let r: EtaView | ApiError | null = null;
    try {
      r = await this.api.selection_eta(pkgs);
    } catch {
      r = null;
    }
    // W międzyczasie mogło przyjść nowsze zapytanie, zmiana trybu albo zaznaczenia.
    const now = Object.keys(s.selection);
    if (seq !== this.etaSeq || !isManual(s.scan) || now.length !== pkgs.length || now.some((p) => !pkgs.includes(p))) return;
    s.selectionEta = r && !isApiError(r) ? r : null;
  }

  loadApkCache(): Promise<CacheUsage | null> {
    return this.call(this.api.apk_cache());
  }

  clearApkCache(): Promise<CacheCleared | null> {
    return this.call(this.api.clear_apk_cache());
  }

  /** „Ostatnio otwierane foldery” → „Wyczyść”: most zapomina foldery wszystkich telefonów (bez potwierdzenia). */
  /** Liczba telefonów z „Ostatnio” eksploratora: most zapisuje ją przy przeglądaniu, nie wysyłając
   *  ustawień, więc Ustawienia pytają o nią przy otwarciu kategorii (reszta ustawień bez zmian). */
  async loadExplorerRecents(): Promise<void> {
    // Błąd odczytu nie dostaje karty błędu: zostaje poprzednia liczba.
    const r = await this.api.get_settings().catch(() => null);
    if (r && !isApiError(r)) this.state.settings = { ...this.state.settings, explorer_recent_phones: r.explorer_recent_phones };
  }

  async clearExplorerRecents(): Promise<void> {
    const r = await this.call(this.api.explorer_clear_recents());
    if (r) this.state.settings = { ...this.state.settings, explorer_recent_phones: r.phones };
  }

  setTheme(theme: Theme): Promise<Settings | null> {
    return this.saveSettings({ theme });
  }

  runConsole(command: string) {
    return this.call(this.api.adb_shell(command));
  }

  whoIsShowing() {
    return this.call(this.api.who_is_showing());
  }

  checkAdb(path: string | null) {
    return this.call(this.api.check_adb(path));
  }

  pickFolder() {
    return this.call(this.api.pick_folder());
  }

  async report(order: string): Promise<void> {
    const s = this.state;
    s.reportBusy = order;
    try {
      const r = await this.call(this.api.report(order));
      if (r) s.reports = { ...s.reports, [order]: r };
    } finally {
      s.reportBusy = null;
    }
  }

  async loadService(): Promise<ServiceInfo | null> {
    const r = await this.call(this.api.service());
    if (r) this.state.serviceNameMissing = !r.name?.trim();
    return r;
  }

  async saveService(changes: Partial<ServiceInfo>): Promise<ServiceInfo | null> {
    const r = await this.call(this.api.save_service(changes));
    if (!r) return null;
    this.state.serviceNameMissing = !r.name?.trim();
    this.state.settingsSaved = Date.now();
    return r;
  }

  pickAdb() {
    return this.call(this.api.pick_adb());
  }

  pickLogo() {
    return this.call(this.api.pick_logo());
  }

  // --- podgląd ekranu i zrzuty (Plan 6b) ----------------------------------------------------------

  mirrorActive(serial: string): boolean {
    const m = this.state.mirror;
    return m.serial === serial && (m.state === 'starting' || m.state === 'running');
  }

  async mirrorStart(serial: string, name: string): Promise<void> {
    const s = this.state;
    s.mirror = { ...s.mirror, serial, state: 'starting', reason: null, blocked: false, awakeBlocked: false };
    // Stan przychodzi zdarzeniami `mirror:state` — wynik wywołania może być starszy niż one.
    const r = await this.call(this.api.mirror_start(serial, name));
    if (!r) {
      s.mirror = { ...s.mirror, state: 'stopped' };
      return;
    }
    // Powtórzony start (most zwraca dotychczasowy stan bez nowych zdarzeń) — nie zostaw "starting" na zawsze,
    // ale tylko jeśli w międzyczasie nic (np. zdarzenie) już nie zmieniło stanu tego samego telefonu.
    if (s.mirror.serial === serial && s.mirror.state === 'starting') {
      s.mirror = { ...s.mirror, state: r.state, reason: r.reason ?? null };
    }
  }

  async mirrorStop(): Promise<void> {
    await this.call(this.api.mirror_stop());
  }

  async takeScreenshot(serial: string): Promise<void> {
    const s = this.state;
    s.shotBusy = true;
    try {
      const r = await this.call(this.api.screenshot(serial));
      if (!r) return;
      s.lastShot = r.shot;
      s.lastShotSerial = serial;
      s.shotCount = r.count;
      if (s.order && s.shots[s.order]) await this.loadShots(s.order);
    } finally {
      s.shotBusy = false;
    }
  }

  async loadShots(order: string): Promise<void> {
    const r = await this.call(this.api.screenshots(order));
    if (r) this.state.shots = { ...this.state.shots, [order]: r };
  }

  async setShotInReport(order: string, id: number, on: boolean): Promise<void> {
    const r = await this.call(this.api.set_screenshot_in_report(id, on));
    const view = this.state.shots[order];
    if (r && view) {
      this.state.shots = { ...this.state.shots, [order]: { ...view, items: view.items.map((i) => (i.id === id ? r : i)) } };
    } else {
      await this.loadShots(order);  // odrzucone (limit): przełącznik wraca do stanu z dziennika
    }
  }

  async quit(): Promise<void> {
    this.state.closeRequested = false;
    const r = await this.call(this.api.quit());
    if (r?.closing_after_step) this.state.closingAfterStep = true;  // okno zamknie się samo
  }

  dismissError(): void {
    this.state.error = null;
  }
}
