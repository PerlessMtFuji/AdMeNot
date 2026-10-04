import { actedLevels, type ActedLog, type Phase } from './logic';
import type {
  ApiErrorBody, ApkEstimate, ApkQuestion, Category, ConsoleEntry, DeviceEntry, HistoryView, IncidentDone, Level, MirrorState, OrderResult, PhoneCard,
  PlanView, Question, ReportResult, ScanView, Settings, ShotsView, ShotView, StepEvent, UndoDone, Verdict,
} from './types';

export type Screen = 'main' | 'history' | 'settings';
const ORDER_KINDS = ['exec', 'resume', 'undo'];

export class AppState {
  phase = $state<Phase>('connect');
  screen = $state<Screen>('main');
  settings = $state<Settings>({ lang: 'pl', mode: 'simple', adb_path: null, backups_dir: null, theme: 'system', mirror_auto: false,
    apk_cache_limit_gb: 10, apk_cache_clear_after_repair: false, select_level: 'silence' });
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
  showAll = $state(false);
  verdictFilter = $state<Verdict | 'all'>('all');
  query = $state('');
  categoryFilter = $state<Category[]>([]);
  sourceFilter = $state<string | null>(null);
  expanded = $state<string[]>([]);
  focused = $state<string | null>(null);
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
  fatal = $state<string | null>(null);

  get orderRunning(): boolean {
    return this.job !== null && ORDER_KINDS.includes(this.job.kind);
  }
}
