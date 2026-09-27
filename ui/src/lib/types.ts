// Kształt danych z src/demalware/app/present.py i zdarzeń z src/demalware/app/api.py.

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
}

export interface Symptom {
  category: Category;
  severity: Severity;
  text: string;
}

export interface DeviceEntry {
  serial: string;
  state: string;
  model: string | null;
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
  basis: 'declared' | 'granted' | 'observed' | 'confirmed';
}

export interface AppView {
  package: string;
  name: string;
  score: number;
  verdict: Verdict;
  verdict_label: string;
  confidence: 'low' | 'medium' | 'high';
  trusted: boolean;
  incomplete: boolean;
  is_system: boolean;
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
  collectors: { ok: number; total: number; failed: { name: string; error: string | null }[] };
  low_behavior_data: boolean;
  apk: { requested: number; analyzed: number; failed: Record<string, string> } | null;
  apps: AppView[];
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
}

export interface HistoryView {
  serial: string | null;
  serials: string[];
  orders: HistoryOrder[];
  devices: { serial: string; model: string | null }[];
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

export interface ApiErrorBody {
  key: string;
  message: string;
  serial?: string;
  log?: string;
}

export interface ApiError {
  error: ApiErrorBody;
}

export type JobError = ApiErrorBody & { job_id: string; kind: string };

type R<T> = Promise<T | ApiError>;

export interface Api {
  get_settings(): R<Settings>;
  save_settings(changes: Partial<Settings>): R<Settings>;
  list_devices(): R<DevicesPayload>;
  watch_devices(on: boolean): R<{ ok: boolean }>;
  start_scan(serial: string, client: string | null): R<{ job_id: string }>;
  rerender(): R<{ scan: ScanView | null }>;
  preview_plan(requests: Record<string, Level>, unlocked: string[]): R<PlanView>;
  execute(requests: Record<string, Level>, unlocked: string[]): R<{ job_id: string }>;
  resume(order: string): R<{ job_id: string }>;
  undo(order: string, actionId: number | null, pkg: string | null): R<{ job_id: string }>;
  stop(jobId: string): R<{ ok: boolean }>;
  answer(jobId: string, value: string): R<{ ok: boolean }>;
  history(serial: string | null): R<HistoryView>;
  adb_shell(command: string): R<{ ok: boolean; output: string }>;
  check_adb(path: string | null): R<{ ok: boolean; version: string | null; message: string }>;
  pick_folder(): R<{ path: string | null }>;
  quit(): R<{ ok: boolean }>;
}

export interface EventMap {
  devices: DevicesPayload;
  'scan:stage': { stage: string };
  'scan:device': { device: PhoneCard };
  'scan:done': { scan: ScanView; interrupted: string[]; client: string | null };
  'apk:progress': { done: number; total: number; package: string };
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
}

export type EventName = keyof EventMap;
