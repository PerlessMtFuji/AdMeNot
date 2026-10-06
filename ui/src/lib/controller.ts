import { type Bridge, isApiError } from './bridge';
import { i18n } from './i18n/index.svelte';
import { actedAfter, changedVerdicts, defaultSelection, mergeSelection, notificationsManual, upsertStep, withoutUndone } from './logic';
import type { AppState } from './state.svelte';
import { applyTheme } from './theme';
import type {
  ApiError, AppView, CacheUsage, DevicesPayload, Lang, Level, Mode, ServiceInfo, Settings, Theme, Verdict,
} from './types';

const CONSOLE_LIMIT = 500;

export class Controller {
  private ended = new Set<string>();
  private knownLoaded = false;
  private autoMirrored = new Set<string>();

  constructor(readonly state: AppState, readonly bridge: Bridge) {}

  private get api() {
    return this.bridge.api;
  }

  private async call<T>(promise: Promise<T | ApiError>): Promise<T | null> {
    try {
      const result = await promise;
      if (isApiError(result)) {
        this.state.error = result.error;
        return null;
      }
      return result;
    } catch (e) {
      this.state.error = { key: 'internal', message: String(e) };
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
  }

  private onDevices(d: DevicesPayload): void {
    const s = this.state;
    s.devices = d.devices;
    s.devicesError = d.error;
    if (s.serial && !d.devices.some((e) => e.serial === s.serial && e.state === 'device')) {
      s.serial = null;
    }
    const ready = d.devices.filter((e) => e.state === 'device');
    if (!s.serial && ready.length === 1) s.serial = ready[0].serial;
    const picked = s.serial ? d.devices.find((e) => e.serial === s.serial && e.state === 'device') : undefined;
    if (picked && s.settings.mirror_auto && s.mirror.available && !this.autoMirrored.has(picked.serial)
        && !this.mirrorActive(picked.serial)) {
      this.autoMirrored.add(picked.serial);  // raz na uruchomienie: zamknięte okno nie wraca samo
      void this.mirrorStart(picked.serial, picked.model?.replaceAll('_', ' ') ?? picked.serial);
    }
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
      s.selection = defaultSelection(d.scan.apps);
      s.actedLog = {};
      s.undoTarget = null;
      s.touched = [];
      s.unlocked = [];
      s.expanded = [];
      s.openGroups = {};
      s.diagnostics = false;
      s.apk = { done: 0, total: 0, running: true, changed: [] };
      s.apkEstimate = null;
      s.apkQuestion = null;
      s.phase = 'results';
    });
    on('apk:estimate', (d) => { s.apkEstimate = d; });
    on('apk:question', (d) => { s.apkQuestion = d; });
    on('apk:progress', (d) => { s.apk = { ...s.apk, done: d.done, total: d.total, running: true }; });
    on('apk:done', (d) => {
      const changed = changedVerdicts(s.scan?.apps ?? [], d.scan.apps);
      s.selection = mergeSelection(s.selection, d.scan.apps, s.touched);
      s.scan = d.scan;
      s.apkQuestion = null;
      s.apk = { ...s.apk, running: false, changed };
    });
    on('incident:state', (d) => { s.incident = { recording: d.recording, marks: 0, result: null }; });
    on('incident:done', (d) => {
      s.incident = { recording: false, marks: d.marks, result: d };
      if (d.error) s.error = d.error;
    });
    on('apk:stopped', () => { s.apkQuestion = null; s.apk = { ...s.apk, running: false }; });
    on('exec:order', (d) => {
      s.order = d.order;
      s.execPlan = d.plan;
      s.steps = [];
      s.result = null;
      s.stopped = false;
      s.stopping = false;
      s.verifying = false;
      s.disconnectedOrder = null;
      s.interrupted = s.interrupted.filter((o) => o !== d.order);
      s.plan = null;
      s.screen = 'main';
      s.phase = 'executing';
    });
    on('exec:step', (d) => { s.steps = upsertStep(s.steps, d); });
    on('exec:admin_wait', (d) => { s.admin = { ...d, since: Date.now() }; });
    on('exec:admin_done', () => { s.admin = null; });
    on('exec:question', (d) => { s.question = d; });
    on('exec:verify', () => { s.verifying = true; });
    on('exec:stopped', () => { s.stopped = true; });
    on('exec:done', (d) => {
      s.result = d;
      s.actedLog = actedAfter(s.actedLog, s.execPlan, d);
      s.verifying = false;
      s.admin = null;
      s.question = null;
      s.stopping = false;
      s.interrupted = d.stopped ? [d.order] : s.interrupted.filter((o) => o !== d.order);
      s.phase = 'done';
      void this.loadShots(d.order);
    });
    on('exec:disconnected', (d) => {
      s.disconnectedOrder = d.order;
      s.interrupted = [d.order];
      s.admin = null;
      s.question = null;
      s.verifying = false;
      s.device = null;
      s.scan = null;
      s.phase = 'connect';
    });
    on('undo:step', (d) => { s.undoSteps = upsertStep(s.undoSteps, d); });
    on('undo:done', (d) => {
      s.undoResult = d;
      if (s.undoing && d.errors.length === 0) {
        s.actedLog = withoutUndone(s.actedLog, s.undoing.order, s.undoing.pkg);
        s.undoTarget = null;
      }
      s.undoing = null;
      void this.refreshHistory();
    });
    on('adb:command', (d) => { s.console = [...s.console.slice(-(CONSOLE_LIMIT - 1)), d]; });
    on('job:error', (d) => {
      s.error = d;
      // Każdy błąd zadania musi zostawić ekran, z którego da się wyjść (ponowny skan,
      // dokończenie albo cofnięcie zlecenia), niezależnie od klucza błędu.
      if (d.kind === 'scan' && s.phase === 'scanning') {
        s.phase = 'connect';
        s.device = null;
      } else if (d.kind === 'apk' || d.kind === 'deep') {
        s.apkQuestion = null;
        s.apk = { ...s.apk, running: false };
      } else if ((d.kind === 'exec' || d.kind === 'resume') && s.phase === 'executing') {
        if (s.order && !s.interrupted.includes(s.order)) s.interrupted = [...s.interrupted, s.order];
        s.admin = null;
        s.question = null;
        s.verifying = false;
        s.stopping = false;
        s.phase = 'connect';
      } else if (d.kind === 'undo') {
        void this.refreshHistory();
      }
    });
    on('job:end', (d) => {
      this.ended.add(d.job_id);
      if (s.job?.id === d.job_id) s.job = null;
    });
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
  }

  async startScan(): Promise<void> {
    const s = this.state;
    if (!s.serial) return;
    Object.assign(s, {
      error: null, phase: 'scanning', scanStage: 'identify', device: null, scan: null, plan: null,
      result: null, order: null, disconnectedOrder: null, steps: [], screen: 'main',
    });
    s.apk = { done: 0, total: 0, running: false, changed: [] };
    s.apkEstimate = null;
    s.apkQuestion = null;
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
    s.apk = { ...s.apk, done: 0, total: 1, running: true, changed: [] };
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
      openGroups: {}, diagnostics: false,
    });
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
  }

  /** Cofa jedną aplikację w jej najnowszym zleceniu, bez wychodzenia z listy wyników. */
  async undoApp(pkg: string): Promise<void> {
    const entry = this.state.actedLog[pkg]?.at(-1);
    if (!entry || this.state.orderRunning) return;
    this.state.undoTarget = pkg; // ustawiane przed undo: zdarzenia mogą przyjść, zanim wróci wywołanie
    await this.undo(entry.order, null, pkg);
  }

  // --- wybór akcji i plan ------------------------------------------------------------------------

  setLevel(pkg: string, level: Level | null): void {
    const s = this.state;
    if (level && s.acted[pkg] === 'remove') return; // usunięta w tym zleceniu: nie ma czego zmieniać
    const next = { ...s.selection };
    if (level) next[pkg] = level;
    else delete next[pkg];
    s.selection = next;
    if (!s.touched.includes(pkg)) s.touched = [...s.touched, pkg];
  }

  toggle(app: AppView): void {
    this.setLevel(app.package, this.state.selection[app.package] ? null : app.default_level ?? this.selectLevel(app));
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
    const r = await this.call(this.api.preview_plan({ ...s.selection }, [...s.unlocked]));
    if (r) s.plan = r;
  }

  closePlan(): void {
    this.state.plan = null;
  }

  async unlock(pkg: string): Promise<void> {
    this.state.unlocked = [...this.state.unlocked, pkg];
    await this.openPlan();
  }

  // --- wykonanie ------------------------------------------------------------------------------------

  async execute(): Promise<void> {
    const s = this.state;
    s.error = null;
    const r = await this.call(this.api.execute({ ...s.selection }, [...s.unlocked]));
    if (r) this.setJob(r.job_id, 'exec');
  }

  async stop(): Promise<void> {
    const job = this.state.job;
    if (!job) return;
    this.state.stopping = true;
    await this.call(this.api.stop(job.id));
  }

  async answer(value: 'retry' | 'skip'): Promise<void> {
    const q = this.state.question;
    if (!q) return;
    this.state.question = null;
    await this.call(this.api.answer(q.job_id, value));
  }

  async resume(order: string): Promise<void> {
    const s = this.state;
    s.error = null;
    // zlecenie znika z „przerwanych” dopiero z `exec:order`: nieudane wznowienie zostawia je
    const r = await this.call(this.api.resume(order));
    if (r) this.setJob(r.job_id, 'resume');
  }

  async undo(order: string, actionId: number | null = null, pkg: string | null = null): Promise<void> {
    const s = this.state;
    s.error = null;
    s.undoSteps = [];
    s.undoResult = null;
    s.undoing = actionId === null ? { order, pkg } : null;
    const r = await this.call(this.api.undo(order, actionId, pkg));
    if (r) this.setJob(r.job_id, 'undo');
    else s.undoing = s.undoTarget = null;
  }

  // --- historia, ustawienia, konsola -------------------------------------------------------------

  async openHistory(serial: string | null = null): Promise<void> {
    const s = this.state;
    s.screen = 'history';
    s.undoResult = null;
    await this.refreshHistory(serial ?? s.history?.serial ?? s.device?.serial ?? null);
  }

  async refreshHistory(serial: string | null = this.state.history?.serial ?? null): Promise<void> {
    const r = await this.call(this.api.history(serial));
    if (r) this.state.history = r;
  }

  openSettings(): void {
    this.state.screen = 'settings';
  }

  back(): void {
    this.state.screen = 'main';
  }

  async saveSettings(changes: Partial<Settings>): Promise<Settings | null> {
    const r = await this.call(this.api.save_settings(changes));
    if (!r) return null;
    this.applySettings(r);
    if ('lang' in changes) {
      const view = await this.call(this.api.rerender());
      if (view?.scan) this.state.scan = view.scan;
      if (this.state.screen === 'history') await this.refreshHistory();
    }
    return r;
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
    if (!q) return;
    this.state.apkQuestion = null;
    await this.call(this.api.answer(q.job_id, value));
  }

  loadApkCache(): Promise<CacheUsage | null> {
    return this.call(this.api.apk_cache());
  }

  clearApkCache(): Promise<{ freed_bytes: number } | null> {
    return this.call(this.api.clear_apk_cache());
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

  loadService() {
    return this.call(this.api.service());
  }

  saveService(changes: Partial<ServiceInfo>) {
    return this.call(this.api.save_service(changes));
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
    await this.call(this.api.quit());
  }

  dismissError(): void {
    this.state.error = null;
  }
}
