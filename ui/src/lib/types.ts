// Kształt danych z src/admenot/app/present.py i zdarzeń z src/admenot/app/api.py.

export type Lang = 'pl' | 'en';
export type Mode = 'simple' | 'expert';
export type Verdict = 'safe' | 'review' | 'suspicious' | 'malicious';
export type Level = 'silence' | 'disable' | 'remove';
export type Theme = 'system' | 'light' | 'dark';
export type Category = 'ads' | 'notif' | 'removal' | 'data' | 'disguise' | 'background' | 'origin';
export type Severity = 'bad' | 'warn' | 'neutral';

export interface Settings {
  lang: Lang;
  mode: Mode;
  adb_path: string | null;
  backups_dir: string | null;
  theme: Theme;
  mirror_auto: boolean;
  apk_cache_limit_gb: number;
  apk_cache_clear_after_repair: boolean;
  select_level: Level;
  check_updates: boolean;
  dismissed_update: string | null;
  last_run_version: string | null;
}

export interface UpdateView {
  available: { version: string; notes: string; size: number } | null;
  dismissed: boolean;
  retired: { min_supported: string; reason: string | null } | null;
  updated_to: string | null;
  updated_notes: string | null;
  installable: boolean;
}

export interface CacheUsage {
  size_bytes: number; free_bytes: number; disk_bytes: number;
  limit_bytes: number; effective_bytes: number; path: string;
}

export interface ApkEstimate {
  to_fetch_bytes: number; total_bytes: number; apps: number; unknown: number; cached: number;
  largest_bytes: number; limit_bytes: number; effective_bytes: number; free_bytes: number;
}

export interface ApkQuestion extends ApkEstimate { job_id: string; kind: 'no_space' }

export interface Symptom {
  category: Category;
  severity: Severity;
  text: string;
}

export interface DeviceEntry {
  serial: string;
  state: string;
  model: string | null;
  name?: string | null; // nazwa handlowa z bazy telefonów (Api._identity); brak → kod modelu
  imei?: string | null;
}

export interface DevicesPayload {
  devices: DeviceEntry[];
  error: string | null;
}

export interface PhoneCard {
  serial: string;
  name: string;
  brand: string;
  manufacturer: string;
  model: string;
  market_name: string | null;
  android: string;
  sdk: number;
  patch: string | null;
  uptime_s: number;
  imei?: string | null;
  match: { confidence: string; step: string; matched: string | null } | null;
  image: string;
}

export interface Finding {
  rule_id: string;
  class: string;
  weight: number;
  text: string;
  text_expert: string;
  evidence: Record<string, unknown>;
  category: Category | 'combo';
  label: string;
  basis: 'declared' | 'static' | 'granted' | 'observed' | 'confirmed';
  source: 'phone' | 'apk' | 'ioc';
  locations: string[];
}

export type CapabilityLevels = Record<'declared' | 'code' | 'granted' | 'observed', boolean | null>;

export interface AppView {
  package: string;
  name: string;
  score: number;
  verdict: Verdict;
  verdict_label: string;
  confidence: 'low' | 'medium' | 'high';
  confidence_label: string;
  gaps: { key: string; label: string }[];
  scope: { key: string; label: string }[];
  trusted: boolean;
  incomplete: boolean;
  is_system: boolean;
  /** false: wyłączona na telefonie (`pm disable-user`) — przed tą naprawą albo wcześniej. */
  enabled: boolean;
  from_play: boolean;
  installer: string | null;
  is_admin: boolean;
  default_level: Level | null;
  problems: string[];
  findings: Finding[];
  apk_error: string | null;
  icon: string | null;
  ad_sdks: string[] | null;
  symptoms: Symptom[];
  source: { label: string; days: number | null };
  capabilities: { key: string; label: string; levels: CapabilityLevels }[];
}

export interface ScanCounts {
  malicious: number;
  suspicious: number;
  review: number;
  safe: number;
  non_play: number;
  admins: number;
  total: number;
  user: number;
}

export interface ScanView {
  collectors: {
    ok: number;
    total: number;
    failed: { name: string; error: string | null }[];
    /** Kolektory, które zadziałały, ale bez danych dla części aplikacji (starsze nagrania: brak). */
    partial?: { name: string; count: number }[];
  };
  low_behavior_data: boolean;
  apk: { requested: number; analyzed: number; failed: Record<string, string>; stopped_no_space: boolean } | null;
  apps: AppView[];
  profiles: { others: number[]; known: boolean };
  usage_window_h: number | null;
  counts: ScanCounts;
}

export interface PlanApp {
  package: string;
  name: string;
  level: Level;
  level_label: string;
  blocked: boolean;
  reason: string | null;
  reason_text: string | null;
  steps: string[];
  warnings: string[];
}

export interface PlanView {
  apps: PlanApp[];
  runnable: number;
}

export type StepStatus = 'running' | 'done' | 'failed' | 'skipped' | 'undone';

export interface StepEvent {
  action_id: number;
  package: string;
  name: string;
  kind: string;
  label: string;
  status: StepStatus;
  error: string | null;
  restore_bytes?: number | null; // cofnięcie usunięcia: instalacja z kopii (UI: „to potrwa”)
}

export type Outcome = 'ok' | 'still_active' | 'failed' | 'stopped';

export interface OrderResult {
  order: string;
  status: string;
  status_label: string;
  stopped: boolean;
  apps: { package: string; name: string; outcome: Outcome; errors: string[]; kinds: string[] }[];
}

export interface UndoDone {
  order: string;
  status: string;
  status_label: string;
  errors: string[];
  admin_not_restored: boolean;
}

export interface HistoryAction {
  id: number;
  package: string;
  level: string;
  level_label: string;
  kind: string;
  step_label: string;
  status: string;
  status_label: string;
  error: string | null;
}

export interface HistoryOrder {
  id: number;
  number: string;
  created_at: string;
  status: string;
  status_label: string;
  client: string | null;
  model: string | null;
  interrupted: boolean;
  actions: HistoryAction[];
  /** Nazwy i ikony z migawki zlecenia; brak przy zleceniach sprzed migawek. */
  apps?: Record<string, { name: string | null; icon: string | null }>;
  screenshots: number;
}

export interface HistoryView {
  serial: string | null;
  serials: string[];
  orders: HistoryOrder[];
  devices: { serial: string; name: string; model: string | null; image: string; imei?: string | null }[];
}

export interface ConsoleEntry {
  time: string;
  serial: string | null;
  command: string;
  status: string;
  duration: number;
  output: string;
  tag: string | null;
}

export interface Question {
  job_id: string;
  kind: 'admin_timeout';
  package: string;
  name: string;
}

export interface ServiceInfo {
  name: string | null;
  address: string | null;
  phone: string | null;
  logo: string | null;
}

export interface ReportResult {
  order: string;
  html: string;
  pdf: string | null;
  error: 'no_browser' | 'timeout' | 'failed' | 'locked' | null;
  opened: string | null; // null: zapisany, ale Windows nie ma programu, który go otworzy
}

export type MirrorState = 'starting' | 'running' | 'stopped' | 'failed';

export interface MirrorView {
  serial: string | null;
  state: MirrorState;
  reason?: string | null;
}

export interface ShotView {
  id: number;
  taken_at: string;
  caption: string;
  black: boolean;
  in_report: boolean;
  image: string | null;
}

export interface ShotsView {
  order: string;
  limit: number;
  items: ShotView[];
}

export type AdbSource = 'settings' | 'bundled' | 'path' | 'missing';

export interface ApiErrorBody {
  key: string;
  message: string;
  /** Lokalny raport błędu do wysłania (internal). */
  crash?: string;
  serial?: string;
  /** Nazwa telefonu (wrong_device), jak na ekranie historii. */
  device?: string;
  imei?: string | null;
  log?: string;
  /** Strona pobierania (update_launch_failed). */
  page?: string;
  /** Najstarsza wspierana wersja (retired). */
  min_supported?: string;
}

export interface ApiError {
  error: ApiErrorBody;
}

export type JobError = ApiErrorBody & { job_id: string; kind: string };

type R<T> = Promise<T | ApiError>;

export interface CrashSummary { id: string; kind: 'error' | 'ui' | 'thread' | 'exit'; created: string; type: string; sent_id: string | null }
export interface CrashPreview { body: Record<string, unknown>; has_adb: boolean }

export interface WhoEntry { package: string; name: string }
export interface IncidentHit { mark: number; package: string; name: string; kind: 'overlay' | 'new_notification' | 'foreground'; over: string | null; over_name: string | null }
export interface IncidentDone { marks: number; hits: IncidentHit[]; error?: ApiErrorBody }
export interface WhoView { resumed: WhoEntry | null; overlays: WhoEntry[] | null; errors: string[] }

export interface Api {
  get_settings(): R<Settings>;
  save_settings(changes: Partial<Settings>): R<Settings>;
  apk_cache(): R<CacheUsage>;
  clear_apk_cache(): R<{ freed_bytes: number }>;
  list_devices(): R<DevicesPayload>;
  watch_devices(on: boolean): R<{ ok: boolean }>;
  start_scan(serial: string, client: string | null): R<{ job_id: string }>;
  deep_analyze(pkg: string): R<{ job_id: string }>;
  start_incident(seconds: number): R<{ ok: boolean }>;
  mark_incident(): R<{ ok: boolean }>;
  rerender(): R<{ scan: ScanView | null }>;
  preview_plan(requests: Record<string, Level>, unlocked: string[]): R<PlanView>;
  execute(requests: Record<string, Level>, unlocked: string[]): R<{ job_id: string }>;
  resume(order: string): R<{ job_id: string }>;
  undo(order: string, actionId: number | null, pkg: string | null): R<{ job_id: string }>;
  stop(jobId: string): R<{ ok: boolean }>;
  answer(jobId: string, value: string): R<{ ok: boolean }>;
  history(serial: string | null): R<HistoryView>;
  adb_shell(command: string): R<{ ok: boolean; output: string }>;
  who_is_showing(): R<WhoView>;
  check_adb(path: string | null): R<{ ok: boolean; version: string | null; message: string; source: AdbSource; path: string | null }>;
  mirror_status(): R<MirrorView & { available: boolean }>;
  mirror_start(serial: string, name: string | null): R<MirrorView>;
  mirror_stop(): R<{ ok: boolean }>;
  screenshot(serial: string): R<{ shot: ShotView; count: number }>;
  close_order(serial: string): R<{ ok: boolean }>;
  screenshots(order: string): R<ShotsView>;
  set_screenshot_in_report(id: number, on: boolean): R<ShotView>;
  pick_folder(): R<{ path: string | null }>;
  report(order: string): R<ReportResult>;
  service(): R<ServiceInfo>;
  save_service(changes: Partial<ServiceInfo>): R<ServiceInfo>;
  pick_logo(): R<{ path: string | null }>;
  update_state(): R<UpdateView>;
  dismiss_update(version: string): R<UpdateView>;
  install_update(): R<{ job_id: string } | { opened: boolean }>;
  capture_ui_error(message: string, stack: string | null, screen: string | null): R<{ crash: string | null }>;
  crash_reports(): R<{ reports: CrashSummary[]; startup: string[] }>;
  crash_preview(id: string, include_adb: boolean, comment: string): R<CrashPreview>;
  send_crash(id: string, include_adb: boolean, comment: string): R<{ sent_id: string }>;
  discard_crash(id: string): R<Record<string, never>>;
  quit(): R<{ ok: boolean }>;
}

export interface EventMap {
  devices: DevicesPayload;
  'scan:stage': { stage: string };
  'scan:device': { device: PhoneCard };
  'scan:done': { scan: ScanView; interrupted: string[]; client: string | null };
  'apk:progress': { done: number; total: number; package: string };
  'apk:estimate': ApkEstimate;
  'apk:question': ApkQuestion;
  'apk:done': { scan: ScanView };
  'apk:stopped': Record<string, never>;
  'exec:order': { order: string; plan: PlanView | null };
  'exec:step': StepEvent;
  'exec:admin_wait': { package: string; name: string; timeout: number };
  'exec:admin_done': { package: string; status: string };
  'exec:question': Question;
  'exec:verify': Record<string, never>;
  'exec:stopped': { order: string };
  'exec:done': OrderResult;
  'exec:disconnected': { order: string };
  'undo:step': StepEvent;
  'undo:done': UndoDone;
  'adb:command': ConsoleEntry;
  'job:error': JobError;
  'job:end': { job_id: string; kind: string };
  'app:close_requested': { kind: string };
  'update:state': UpdateView;
  'update:progress': { done: number; total: number | null };
  'mirror:state': MirrorView;
  'mirror:warning': { serial: string; code: 'control_blocked' | 'stay_awake_blocked' };
  'incident:state': { recording: boolean; seconds: number };
  'incident:done': IncidentDone;
}

export type EventName = keyof EventMap;
