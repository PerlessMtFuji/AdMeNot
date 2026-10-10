import { actedLevels, type ActedLog, type OpenGroups, type Phase } from './logic';
import type {
  ApiErrorBody, ApkEstimate, ApkQuestion, Category, ConsoleEntry, DeviceEntry, HistoryView, IncidentDone, Level, MirrorState, OrderResult, PhoneCard,
  PlanView, Question, ReportResult, ScanView, Settings, ShotsView, ShotView, StepEvent, UndoDone, UpdateView, Verdict, WhoView,
} from './types';

export type Screen = 'main' | 'history' | 'settings';
const ORDER_KINDS = ['exec', 'resume', 'undo'];

export class AppState {
  phase = $state<Phase>('connect');
  screen = $state<Screen>('main');
  settings = $state<Settings>({ lang: 'pl', mode: 'simple', adb_path: null, backups_dir: null, theme: 'system', mirror_auto: false,
    apk_cache_limit_gb: 10, apk_cache_clear_after_repair: false, select_level: 'silence',
    check_updates: true, dismissed_update: null, last_run_version: null,
    welcome_version: 1, welcome_current: 1, telemetry: false, telemetry_packages: false, telemetry_id: null,
    telemetry_delete_pending: false, donate_reminders: true });
  settingsLoaded = $state(false);  // ekran powitalny dopiero po odczycie ustawień
  devices = $state<DeviceEntry[]>([]);
  devicesError = $state<string | null>(null);
  knownSerials = $state<string[]>([]);
  serial = $state<string | null>(null);
  client = $state('');
  scanStage = $state<string | null>(null);
  device = $state<PhoneCard | null>(null);
  scan = $state<ScanView | null>(null);
  apk = $state({ done: 0, total: 0, running: false, changed: [] as string[] });
  apkEstimate = $state<ApkEstimate | null>(null);
  apkQuestion = $state<ApkQuestion | null>(null);
  interrupted = $state<string[]>([]);
  selection = $state<Record<string, Level>>({});
  touched = $state<string[]>([]);
  unlocked = $state<string[]>([]);
  verdictFilter = $state<Verdict | 'all'>('all');
  query = $state('');
  categoryFilter = $state<Category[]>([]);
  sourceFilter = $state<string | null>(null);
  expanded = $state<string[]>([]);
  focused = $state<string | null>(null);
  /** Rozwinięte/zwinięte grupy werdyktu na ekranie Naprawa; puste = domyślne trybu (logic.groupOpen). */
  openGroups = $state<OpenGroups>({});
  /** Prawy panel pokazuje „Znajdź źródło reklamy" zamiast planu / szczegółów. */
  diagnostics = $state(false);
  who = $state<WhoView | null>(null); // wynik „Kto to wyświetla?” — żyje do nowego skanu
  /** „Szczegóły techniczne" w panelu Eksperta — pamiętane do zamknięcia programu. */
  detailsOpen = $state(false);
  plan = $state<PlanView | null>(null);
  job = $state<{ id: string; kind: string } | null>(null);
  incident = $state<{ recording: boolean; marks: number; result: IncidentDone | null }>({ recording: false, marks: 0, result: null });
  order = $state<string | null>(null);
  execPlan = $state<PlanView | null>(null);
  steps = $state<StepEvent[]>([]);
  admin = $state<{ package: string; name: string; timeout: number; since: number } | null>(null);
  question = $state<Question | null>(null);
  verifying = $state(false);
  stopping = $state(false);
  stopped = $state(false);
  result = $state<OrderResult | null>(null);
  donateBanner = $state(false); // przypomnienie o wsparciu na ekranie wyniku (spec kroku J §6.1)
  /** Co już zrobiono na tym telefonie od skanu, zlecenie po zleceniu (powrót do naprawy, cofanie aplikacji). */
  actedLog = $state<ActedLog>({});
  /** Trwające cofanie (undo:done zdejmuje cofnięte z actedLog); action_id → null, bo cofa tylko krok. */
  undoing = $state<{ order: string; pkg: string | null } | null>(null);
  /** Aplikacja cofana z listy wyników — tam pokazujemy postęp i błędy. */
  undoTarget = $state<string | null>(null);
  get acted(): Record<string, Level> {
    return actedLevels(this.actedLog);
  }
  disconnectedOrder = $state<string | null>(null);
  history = $state<HistoryView | null>(null);
  undoSteps = $state<StepEvent[]>([]);
  undoResult = $state<UndoDone | null>(null);
  reportBusy = $state<string | null>(null);
  reports = $state<Record<string, ReportResult>>({});
  mirror = $state<{ available: boolean; serial: string | null; state: MirrorState; reason: string | null; blocked: boolean; awakeBlocked: boolean }>(
    { available: false, serial: null, state: 'stopped', reason: null, blocked: false, awakeBlocked: false });
  shots = $state<Record<string, ShotsView>>({});
  lastShot = $state<ShotView | null>(null);
  lastShotSerial = $state<string | null>(null);
  shotCount = $state(0);
  shotBusy = $state(false);
  consoleOpen = $state(false);
  console = $state<ConsoleEntry[]>([]);
  consoleWarned = $state(false);
  error = $state<ApiErrorBody | null>(null);
  closeRequested = $state(false);
  update = $state<UpdateView | null>(null);
  updateDialog = $state(false);
  updateProgress = $state<{ done: number; total: number | null } | null>(null);
  updateError = $state<ApiErrorBody | null>(null);
  /** „Zaktualizowano do …” zamknięte w tej sesji. */
  updatedSeen = $state(false);
  fatal = $state<string | null>(null);
  crashStartup = $state<string[]>([]);
  crashDialog = $state<string | null>(null);
  crashAdb = $state(false);
  crashComment = $state('');
  crashPreview = $state<Record<string, unknown> | null>(null);
  crashHasAdb = $state(false);
  crashSending = $state(false);
  crashSent = $state<string | null>(null);
  crashError = $state<ApiErrorBody | null>(null);
  fatalCrash = $state<string | null>(null);

  get orderRunning(): boolean {
    return this.job !== null && ORDER_KINDS.includes(this.job.kind);
  }
}
