import { CATEGORY_ORDER } from './categories';
import type { AppView, BackupResultView, Category, CopyView, DeviceCheck, DeviceEntry, EtaView, Finding, HistoryAction, HistoryOrder, Level, Mode, OrderResult, PlanApp, PlanLevel, PlanView, ScanView, Settings, StepEvent, TransferCategory, TransferProgress, TransferSelection, InventoryView, RestorePlanView, RestoreResultView, UndoSite, UploadChoiceView, UploadGroup, UpdateView, UserWait, Verdict } from './types';

export type Phase = 'connect' | 'scanning' | 'results' | 'executing' | 'done'
  | 'transfer_choose' | 'transfer_backup' | 'transfer_done'
  | 'transfer_restore_plan' | 'transfer_restore' | 'transfer_restored';
export type StageState = 'done' | 'now' | 'todo';

export function defaultSelection(apps: AppView[]): Record<string, Level> {
  const out: Record<string, Level> = {};
  for (const a of apps) if (a.default_level) out[a.package] = a.default_level;
  return out;
}

export function mergeSelection(selection: Record<string, Level>, apps: AppView[],
  touched: string[]): Record<string, Level> {
  const out = { ...selection };
  for (const a of apps) {
    if (!touched.includes(a.package) && a.default_level && !(a.package in out)) {
      out[a.package] = a.default_level;
    }
  }
  return out;
}

export function changedVerdicts(before: AppView[], after: AppView[]): string[] {
  const old = new Map(before.map((a) => [a.package, a.verdict]));
  return after.filter((a) => old.has(a.package) && old.get(a.package) !== a.verdict)
    .map((a) => a.package);
}

export function flaggedApps(apps: AppView[]): AppView[] {
  return apps.filter((a) => a.verdict !== 'safe');
}

// Syntetyczna opcja filtra źródła „Spoza Sklepu Play”: ten sam warunek co dawny licznik non_play
// (nie systemowa i nie ze Sklepu Play).
export const SOURCE_NON_PLAY = '__non_play__';
const isNonPlay = (a: AppView) => !a.is_system && !a.from_play;

export function visibleApps(apps: AppView[],
  opts: { showAll: boolean; verdict: Verdict | 'all'; query: string; categories?: Category[];
    source?: string | null }): AppView[] {
  const q = opts.query.trim().toLowerCase();
  const cats = opts.categories ?? [];
  return apps.filter((a) =>
    (opts.showAll || a.verdict !== 'safe')
    && (opts.verdict === 'all' || a.verdict === opts.verdict)
    && (!q || a.name.toLowerCase().includes(q) || a.package.toLowerCase().includes(q))
    && (!cats.length || a.symptoms.some((sy) => cats.includes(sy.category)))
    && (!opts.source || (opts.source === SOURCE_NON_PLAY ? isNonPlay(a) : a.source.label === opts.source)));
}

// Opcje filtrów tabeli eksperta: kategorie w stałej kolejności, źródła od najczęstszego.
export function facetCounts(apps: AppView[]): {
  categories: { value: Category; count: number }[];
  sources: { value: string; count: number }[];
  nonPlay: number;
} {
  const categories = CATEGORY_ORDER
    .map((value) => ({ value, count: apps.filter((a) => a.symptoms.some((sy) => sy.category === value)).length }))
    .filter((c) => c.count > 0);
  const bySource = new Map<string, number>();
  for (const a of apps) bySource.set(a.source.label, (bySource.get(a.source.label) ?? 0) + 1);
  const sources = [...bySource].map(([value, count]) => ({ value, count }))
    .sort((x, y) => y.count - x.count || x.value.localeCompare(y.value));
  return { categories, sources, nonPlay: apps.filter(isNonPlay).length };
}

export function upsertStep(steps: StepEvent[], step: StepEvent): StepEvent[] {
  const i = steps.findIndex((s) => s.action_id === step.action_id);
  if (i < 0) return [...steps, step];
  const copy = [...steps];
  copy[i] = step;
  return copy;
}

export function groupSteps(steps: StepEvent[]): { package: string; name: string; steps: StepEvent[] }[] {
  const groups: { package: string; name: string; steps: StepEvent[] }[] = [];
  for (const s of steps) {
    let g = groups.find((x) => x.package === s.package);
    if (!g) {
      g = { package: s.package, name: s.name, steps: [] };
      groups.push(g);
    }
    g.steps.push(s);
  }
  return groups;
}

const READ_STAGES = new Set(['identify', 'packages', 'collectors']);

export function stageStates(phase: Phase, scanStage: string | null, reported = false): StageState[] {
  switch (phase) {
    case 'connect':
      return ['now', 'todo', 'todo', 'todo', 'todo'];
    case 'scanning':
      return READ_STAGES.has(scanStage ?? 'identify')
        ? ['done', 'now', 'todo', 'todo', 'todo']
        : ['done', 'done', 'now', 'todo', 'todo'];
    case 'results':
    case 'executing':
      return ['done', 'done', 'done', 'now', 'todo'];
    case 'done':
      return ['done', 'done', 'done', 'done', reported ? 'done' : 'now'];
    default: // przenoszenie danych ma własne etapy (transferStages)
      return ['now', 'todo', 'todo', 'todo', 'todo'];
  }
}

export function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d} d ${h} h`;
  if (h > 0) return `${h} h ${m} min`;
  return `${m} min`;
}

export function levelTag(level: Level | null): 'tag-bad' | 'tag-warn' | 'tag-gray' {
  if (level === 'remove') return 'tag-bad';
  if (level === 'disable') return 'tag-warn';
  return 'tag-gray';
}

export function verdictColor(verdict: Verdict): string {
  return { malicious: '#dc2626', suspicious: '#f59e0b', review: '#94a3b8', safe: '#16a34a' }[verdict];
}

export function signalChips(app: AppView): { label: string; bad: boolean }[] {
  const out: { label: string; bad: boolean }[] = [];
  for (const f of app.findings) {
    const label = f.rule_id.replace(/^DM-/, '').replace(/-\d+$/, '').toLowerCase();
    const found = out.find((c) => c.label === label);
    if (found) found.bad ||= f.weight >= 15;
    else out.push({ label, bad: f.weight >= 15 });
  }
  return out;
}

export function sourceKey(app: AppView): 'play' | 'system' | 'sideload' {
  if (app.is_system) return 'system';
  return app.from_play ? 'play' : 'sideload';
}

export type LinkState = 'adb_missing' | 'none' | 'unauthorized' | 'offline' | 'ready' | 'many';
export type CheckStatus = 'todo' | 'on' | 'done';

export function linkState(devices: DeviceEntry[], error: string | null): LinkState {
  if (error === 'adb_missing') return 'adb_missing';
  const ready = devices.filter((d) => d.state === 'device').length;
  if (ready > 1) return 'many';
  if (ready === 1) return 'ready';
  if (devices.some((d) => d.state === 'unauthorized')) return 'unauthorized';
  if (devices.some((d) => d.state === 'offline')) return 'offline';
  return 'none';
}

export function connectChecklist(link: LinkState): CheckStatus[] {
  if (link === 'ready' || link === 'many') return ['done', 'done', 'done'];
  if (link === 'unauthorized' || link === 'offline') return ['done', 'on', 'todo'];
  return ['on', 'todo', 'todo'];
}

/** Polecenie kroku instrukcji USB pocięte na zwykły tekst i nazwy z ekranu telefonu (w cudzysłowie). */
export function guideTerms(text: string): { text: string; term: boolean }[] {
  return text.split(/[„“"]([^”"]+)[”"]/)
    .map((part, i) => ({ text: part, term: i % 2 === 1 }))
    .filter((p) => p.text);
}

/** Poziomy menu ze ścieżki „Ustawienia → … → cel”. */
export function guidePath(path: string): string[] {
  return path.split('→').map((s) => s.trim()).filter(Boolean);
}

export const SCAN_STEPS = ['identify', 'packages', 'collectors', 'score'] as const;

export function scanChecklist(stage: string | null): CheckStatus[] {
  const at = stage === 'apk' ? SCAN_STEPS.length : Math.max(0, SCAN_STEPS.indexOf((stage ?? 'identify') as never));
  return SCAN_STEPS.map((_, i) => (i < at ? 'done' : i === at ? 'on' : 'todo'));
}

export function initial(name: string): string {
  return (name.trim()[0] ?? '?').toUpperCase();
}

export function modelName(model: string | null): string {
  return model ? model.replaceAll('_', ' ') : '?';
}

/** Android ≤12: powiadomień nie wyłączy się przez ADB (planner.NOTIF_PERMISSION_MIN_SDK) — tylko ręcznie na telefonie. */
export const NOTIF_PERMISSION_MIN_SDK = 33;
export function notificationsManual(sdk: number | undefined): boolean {
  return !!sdk && sdk < NOTIF_PERMISSION_MIN_SDK;
}

export const LEVEL_TONE: Record<Level, 'accent' | 'warn' | 'bad'> = { silence: 'accent', disable: 'warn', remove: 'bad' };
/** Poprawki „Stanu telefonu” mają ten sam kolor co wyciszenie: nic nie jest usuwane. */
export const PLAN_TONE: Record<PlanLevel, 'accent' | 'warn' | 'bad'> = { ...LEVEL_TONE, fix: 'accent' };
export const VERDICT_TONE: Record<Verdict, 'bad' | 'warn' | 'neutral' | 'ok'> = {
  malicious: 'bad', suspicious: 'warn', review: 'neutral', safe: 'ok',
};

export type PlanGroupKey = PlanLevel | 'blocked';
/** Krok albo ostrzeżenie w grupie; only: nazwy aplikacji, których dotyczy (pusta = wszystkich w grupie). */
export interface PlanGroupLine { text: string; only: string[] }
export interface PlanGroup { key: PlanGroupKey; apps: PlanApp[]; steps: PlanGroupLine[]; warnings: PlanGroupLine[] }

const PLAN_GROUPS: PlanGroupKey[] = ['remove', 'disable', 'silence', 'fix', 'blocked']; // od najmocniejszej zmiany

/** Jedna lista dla grupy w kolejności wykonania: krok, którego część aplikacji nie ma, zostaje między
 *  sąsiadami z ich listy (planista układa kroki zawsze w tej samej kolejności). */
function mergeLines(apps: PlanApp[], pick: (a: PlanApp) => string[]): PlanGroupLine[] {
  const order: string[] = [];
  for (const a of apps) {
    let at = -1;
    for (const text of pick(a)) {
      const found = order.indexOf(text);
      if (found >= 0) at = found;
      else order.splice(++at, 0, text);
    }
  }
  return order.map((text) => {
    const having = apps.filter((a) => pick(a).includes(text));
    return { text, only: having.length === apps.length ? [] : having.map((a) => a.name) };
  });
}

/** Podsumowanie przed naprawą pogrupowane wg akcji, jak strona planu dla klienta. */
export function planGroups(apps: PlanApp[], lang: string): PlanGroup[] {
  const order = new Intl.Collator(lang);
  return PLAN_GROUPS.flatMap((key) => {
    const list = apps.filter((a) => (a.blocked ? 'blocked' : a.level) === key).sort((a, b) => order.compare(a.name, b.name));
    return list.length === 0 ? []
      : [{ key, apps: list, steps: mergeLines(list, (a) => a.steps), warnings: mergeLines(list, (a) => a.warnings) }];
  });
}

/** Plan wykonania, jeden wiersz na pakiet: przeglądarka z poprawkami ustawień i własnym poziomem ma w
 *  planie dwa wpisy — liczy się poziom aplikacji (jak w `groupHistory`), kroki obu zostają w kolejności. */
export function runnableApps(plan: PlanView | null): PlanApp[] {
  const rows: PlanApp[] = [];
  for (const a of plan?.apps ?? []) {
    if (a.blocked) continue;
    const i = rows.findIndex((r) => r.package === a.package);
    if (i < 0) { rows.push(a); continue; }
    const app = rows[i].level === 'fix' ? a : rows[i];
    rows[i] = { ...app, steps: [...rows[i].steps, ...a.steps], warnings: [...rows[i].warnings, ...a.warnings] };
  }
  return rows;
}

export function planEntries(apps: AppView[], selection: Record<string, Level>):
  { package: string; name: string; level: Level }[] {
  return apps.filter((a) => a.package in selection)
    .map((a) => ({ package: a.package, name: a.name, level: selection[a.package] }));
}

export function moveFocus(rows: string[], current: string | null, delta: 1 | -1): string | null {
  if (rows.length === 0) return null;
  const at = current === null ? -1 : rows.indexOf(current);
  if (at < 0) return rows[0];
  return rows[Math.min(rows.length - 1, Math.max(0, at + delta))];
}

export function focusedApp(rows: string[], focused: string | null): string | null {
  if (focused !== null && rows.includes(focused)) return focused;
  return rows[0] ?? null;
}

export function evidenceGroups(findings: Finding[]):
  { groups: { category: Category; items: Finding[] }[]; combos: Finding[] } {
  const byCategory = new Map<Category, Finding[]>();
  const combos: Finding[] = [];
  for (const f of findings) {
    if (f.category === 'combo') combos.push(f);
    else byCategory.set(f.category, [...(byCategory.get(f.category) ?? []), f]);
  }
  const groups = [...byCategory.entries()]
    .map(([category, items]) => ({ category, items: [...items].sort((a, b) => b.weight - a.weight) }))
    .sort((a, b) => (b.items[0].weight - a.items[0].weight)
      || (CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category)));
  return { groups, combos };
}

// Progi werdyktu z scoring.verdict_for (25 / 50 / 75).
export const SCORE_ZONES: { from: number; to: number; verdict: Verdict }[] = [
  { from: 0, to: 25, verdict: 'safe' }, { from: 25, to: 50, verdict: 'review' },
  { from: 50, to: 75, verdict: 'suspicious' }, { from: 75, to: 100, verdict: 'malicious' },
];

export type AppHistoryState = 'done' | 'restored' | 'pending' | 'failed';
export interface HistoryAppRow {
  package: string;
  level: PlanLevel;
  state: AppHistoryState;
  actions: HistoryAction[];
  backup: boolean;
  canRestore: boolean;
}

export function groupHistory(actions: HistoryAction[]): HistoryAppRow[] {
  const rows: HistoryAppRow[] = [];
  for (const a of actions) {
    let row = rows.find((r) => r.package === a.package);
    if (!row) {
      row = { package: a.package, level: a.level as PlanLevel, state: 'done', actions: [], backup: false, canRestore: false };
      rows.push(row);
    }
    // Poprawki ustawień przeglądarki i jej wyciszenie w jednym zleceniu to jeden wiersz: liczy się poziom aplikacji.
    if (row.level === 'fix' && a.level !== 'fix') row.level = a.level as PlanLevel;
    row.actions.push(a);
  }
  for (const r of rows) {
    // `manual_undo` ma tylko kanał nie do przywrócenia (`channel_gone`): zostaje „done”, więc stan
    // aplikacji liczą pozostałe kroki, a sama taka poprawka to wciąż „ustawienia witryn zmienione”.
    const auto = r.actions.filter((a) => !a.manual_undo);
    const statuses = (auto.length ? auto : r.actions).map((a) => a.status);
    // Po cofnięciu zostają „failed” tylko kroki, które niczego nie zmieniły (np. pominięte).
    const restored = statuses.includes('undone') && !statuses.includes('done') && !statuses.includes('pending');
    r.state = restored ? 'restored'
      : statuses.includes('pending') ? 'pending' : statuses.includes('failed') ? 'failed' : 'done';
    r.backup = r.actions.some((a) => a.kind === 'backup' && a.status === 'done');
    // Kanał nie do przywrócenia (`manual_undo`) nie daje nic do cofnięcia; zwykły kanał „done” tak.
    r.canRestore = r.actions.some((a) => a.status === 'done' && !a.manual_undo);
  }
  return rows;
}

export type SiteState = 'done' | 'current' | 'waiting' | 'skipped' | 'gone';

/** Stan pozycji kolejki witryn w cofaniu: z kroku `undo:step` tej witryny, potem z bieżącego oczekiwania. */
export function siteState(site: UndoSite, steps: StepEvent[], wait: UserWait | null): SiteState {
  const step = steps.find((a) => a.action_id === site.action_id);
  if (step?.status === 'undone') return 'done';
  if (step?.status === 'failed') return step.error_key === 'channel_gone' ? 'gone' : 'skipped';
  return wait?.action_id === site.action_id ? 'current' : 'waiting';
}

/** Nazwa i ikona aplikacji w historii: z migawki zlecenia, potem z bieżącego skanu, na końcu pakiet. */
export function historyApp(order: HistoryOrder, pkg: string, scanned: AppView[] = []): { name: string; icon: string | null } {
  const saved = order.apps?.[pkg];
  const now = scanned.find((a) => a.package === pkg);
  return { name: saved?.name || now?.name || pkg, icon: saved?.icon ?? now?.icon ?? null };
}

export function orderCounts(rows: HistoryAppRow[]): [PlanLevel, number][] {
  const out: [PlanLevel, number][] = [];
  for (const level of ['remove', 'disable', 'silence', 'fix'] as PlanLevel[]) {
    const n = rows.filter((r) => r.level === level).length;
    if (n) out.push([level, n]);
  }
  return out;
}

export function dayKey(iso: string, now: Date): 'today' | 'yesterday' | 'date' {
  const d = new Date(iso);
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const diff = Math.round((today - day) / 86_400_000);
  return diff === 0 ? 'today' : diff === 1 ? 'yesterday' : 'date';
}

export function formatGb(bytes: number, lang: string): string {
  return new Intl.NumberFormat(lang === 'pl' ? 'pl-PL' : 'en-US',
    { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(bytes / 1024 ** 3);
}

// Poniżej 0,1 GB w MB (co najmniej 1 MB), żeby kilka małych aplikacji nie dawało „0,0 GB”.
export function formatSize(bytes: number, lang: string): string {
  if (bytes > 0 && bytes < 1024 ** 3 / 10) return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;
  return `${formatGb(bytes, lang)} GB`;
}

const LEVEL_RANK: Record<Level, number> = { silence: 1, disable: 2, remove: 3 };

export type ActedLog = Record<string, { order: string; level: Level }[]>;

/** Dopisuje aplikacje wykonane w zleceniu (bez zatrzymanych i nieudanych), najnowsze zlecenie na końcu. */
export function actedAfter(log: ActedLog, plan: PlanView | null, result: OrderResult): ActedLog {
  const next = { ...log };
  const levels = new Map(runnableApps(plan).map((a) => [a.package, a.level]));
  for (const app of result.apps) {
    const level = levels.get(app.package);
    if (app.outcome !== 'ok' || !level || level === 'fix') continue; // poprawka ustawień to nie poziom aplikacji
    next[app.package] = [...(next[app.package] ?? []), { order: result.order, level }];
  }
  return next;
}

/** Najmocniejszy poziom, który wciąż obowiązuje na każdej aplikacji. */
export function actedLevels(log: ActedLog): Record<string, Level> {
  const out: Record<string, Level> = {};
  for (const [pkg, entries] of Object.entries(log)) {
    for (const { level } of entries) {
      if (!out[pkg] || LEVEL_RANK[level] > LEVEL_RANK[out[pkg]]) out[pkg] = level;
    }
  }
  return out;
}

/** Po udanym cofnięciu: całe zlecenie (pkg null) albo jedna aplikacja w tym zleceniu. */
export function withoutUndone(log: ActedLog, order: string, pkg: string | null): ActedLog {
  const next: ActedLog = {};
  for (const [p, entries] of Object.entries(log)) {
    const kept = entries.filter((e) => e.order !== order || (pkg !== null && p !== pkg));
    if (kept.length) next[p] = kept;
  }
  return next;
}

// --- ekran Naprawa: grupy, rozwinięcie, powody, komunikaty -----------------------------------------

export const VERDICT_ORDER: Verdict[] = ['malicious', 'suspicious', 'review', 'safe'];

/** Zawsze cztery grupy, także puste; kolejność aplikacji jak w skanie (wynik malejąco). */
export function verdictGroups(apps: AppView[]): { verdict: Verdict; apps: AppView[] }[] {
  return VERDICT_ORDER.map((verdict) => ({ verdict, apps: apps.filter((a) => a.verdict === verdict) }));
}

export type OpenGroups = Partial<Record<Verdict, boolean>>;

/** Wyszukiwanie lub filtr rozwija wszystko; inaczej wybór użytkownika, a bez niego domyślne trybu. */
export function groupOpen(verdict: Verdict, mode: Mode, open: OpenGroups, searching: boolean): boolean {
  if (searching) return true;
  const saved = open[verdict];
  if (saved !== undefined) return saved;
  if (verdict === 'safe') return false;
  return !(verdict === 'review' && mode === 'simple');
}

export interface Reason { category: Category; label: string }

/** Najmocniejsze znalezisko z każdej kategorii (bez combo i zerowych wag); bez znalezisk — nazwy kategorii objawów. */
export function topReasons(app: AppView, n: number, categoryLabel: (c: Category) => string):
  { items: Reason[]; more: Category[] } {
  const best = new Map<Category, Finding>();
  for (const f of app.findings) {
    if (f.category === 'combo' || f.weight <= 0) continue;
    const cur = best.get(f.category);
    if (!cur || f.weight > cur.weight) best.set(f.category, f);
  }
  let all: Reason[] = [...best.entries()]
    .sort(([ca, a], [cb, b]) => b.weight - a.weight || CATEGORY_ORDER.indexOf(ca) - CATEGORY_ORDER.indexOf(cb))
    .map(([category, f]) => ({ category, label: f.label }));
  if (!all.length) all = app.symptoms.map((sy) => ({ category: sy.category, label: categoryLabel(sy.category) }));
  return { items: all.slice(0, n), more: all.slice(n).map((r) => r.category) };
}

export type NoticeKey = 'low_data' | 'incomplete' | 'profiles' | 'profiles_unknown' | 'notifications_manual'
  | 'select_level_disable' | 'checks_unreadable';
export interface Notice { key: NoticeKey; tone: 'warn' | 'info'; params: Record<string, string | number> }

/** Komunikaty informacyjne nad listą: najpierw ostrzeżenia, potem informacje (spec §3). */
export function notices(input: { scan: ScanView | null; sdk: number | undefined; selectLevel: Level;
  missing: string[]; withGaps: number }): Notice[] {
  const { scan } = input;
  const out: Notice[] = [];
  if (scan?.low_behavior_data) out.push({ key: 'low_data', tone: 'warn', params: { hours: scan.usage_window_h?.toFixed(1) ?? '?' } });
  if (input.missing.length) out.push({ key: 'incomplete', tone: 'warn', params: { count: input.withGaps, names: input.missing.join(', ') } });
  if (scan?.profiles.others.length) out.push({ key: 'profiles', tone: 'warn', params: { ids: scan.profiles.others.join(', ') } });
  else if (scan && !scan.profiles.known) out.push({ key: 'profiles_unknown', tone: 'warn', params: {} });
  if (notificationsManual(input.sdk)) {
    out.push({ key: 'notifications_manual', tone: 'info', params: {} });
    if (input.selectLevel === 'silence') out.push({ key: 'select_level_disable', tone: 'info', params: {} });
  }
  if (scan?.device_checks?.some((c) => c.state === 'unrecognized')) out.push({ key: 'checks_unreadable', tone: 'info', params: {} });
  return out;
}

/** Który baner aktualizacji pokazać; wycofanie ma pierwszeństwo i nie da się go zamknąć (spec aktualizacji §7). */
export function updateBanner(u: UpdateView | null, updatedSeen: boolean): 'retired' | 'available' | 'updated' | null {
  if (!u) return null;
  if (u.retired) return 'retired';
  if (u.available && !u.dismissed) return 'available';
  if (u.updated_to && !updatedSeen) return 'updated';
  return null;
}

/** Ekran powitalny: ostrzeżenie jeszcze niezaakceptowane albo w starszej wersji (spec kroku H §3.1). */
export function needsWelcome(s: Settings): boolean {
  return s.welcome_version === null || s.welcome_version < s.welcome_current;
}

/** Grupy z polem „zaznacz wszystkie” i akcją zbiorczą; „Bez uwag” nie, żeby nie zaznaczyć setek aplikacji naraz. */
export const BULK_VERDICTS: Verdict[] = ['malicious', 'suspicious', 'review'];

/** Stan pola „zaznacz wszystkie”: liczą się tylko aplikacje, które można jeszcze zmienić (nieusunięte). */
export function groupCheck(apps: AppView[], selection: Record<string, Level>,
  acted: Record<string, Level>): 'none' | 'some' | 'all' {
  const open = apps.filter((a) => acted[a.package] !== 'remove');
  const picked = open.filter((a) => selection[a.package]).length;
  return picked === 0 ? 'none' : picked === open.length ? 'all' : 'some';
}

/** „Wyłącz” i „Usuń” dla wielu aplikacji naraz wymagają potwierdzenia; „Wycisz” jest najłagodniejsze. */
export function bulkNeedsConfirm(levels: Record<string, Level>): boolean {
  return Object.values(levels).some((l) => l !== 'silence');
}

export type FactTag = 'non_play' | 'admin' | 'accessibility' | 'overlay' | 'disabled';

export function isManual(scan: ScanView | null): boolean {
  return scan?.apk_mode === 'manual' || scan?.apk_mode === 'partial';
}

/** Tryb analizy jeszcze nierozstrzygnięty: werdykty heurystyk ukryte do wyboru „pełna” (albo „zawsze pełna”). */
export function modeUndecided(o: { scan: ScanView | null; setting: Settings['apk_mode_default']; running: boolean;
  fullChosen: boolean }): boolean {
  return o.scan?.apk_mode === 'pending' && o.setting !== 'full' && o.running && !o.fullChosen;
}

const installedAt = (a: AppView): number => (a.first_install ? Date.parse(a.first_install) : -Infinity);

export function manualRows(apps: AppView[], opts: { query: string; showSystem: boolean; source: string | null }): AppView[] {
  const found = visibleApps(apps, { showAll: true, verdict: 'all', query: opts.query, source: opts.source });
  return found.filter((a) => opts.showSystem || !a.is_system)
    .sort((a, b) => installedAt(b) - installedAt(a) || a.name.localeCompare(b.name));
}

// Tylko to, co telefon pokazuje bez analizy APK: przyznane albo zaobserwowane, nie zadeklarowane.
const live = (a: AppView, key: string): boolean =>
  a.capabilities.some((c) => c.key === key && (c.levels.granted === true || c.levels.observed === true));

export function factTags(a: AppView): FactTag[] {
  const out: FactTag[] = [];
  if (!a.is_system && !a.from_play) out.push('non_play');
  if (a.is_admin) out.push('admin');
  if (live(a, 'accessibility')) out.push('accessibility');
  if (live(a, 'overlay')) out.push('overlay');
  if (!a.enabled) out.push('disabled');
  return out;
}

export function stableEta(shown: number | null, next: number | null): number | null {
  if (next === null || shown === null) return next;
  return next > shown && next - shown < 60 ? shown : next;
}

/** Poprawki oferowane przez kontrole „Stanu telefonu”: każda witryna z poprawką i „wszystkie witryny” przeglądarki. */
export function offeredFixes(checks: DeviceCheck[]): string[] {
  return checks.flatMap((c) => c.browsers.flatMap((b) => [
    ...(b.all_fix ? [b.all_fix] : []), ...b.sites.flatMap((s) => (s.fix ? [s.fix] : []))]));
}

/** Kontrole do pokazania w sekcji: nieodczytane (`unrecognized`) idą do linii uwag, nie do sekcji. */
export function shownChecks(scan: ScanView | null): DeviceCheck[] {
  return (scan?.device_checks ?? []).filter((c) => c.state !== 'unrecognized');
}

// --- przenoszenie danych ---------------------------------------------------------------------

export const TRANSFER_CATEGORIES: readonly TransferCategory[] = ['media', 'downloads', 'whatsapp'];
const TRANSFER_RATE = 25 * 1024 ** 2; // B/s — zgrubnie, kopia przez USB 2.0 / adb pull
const readable = (n: number | null): boolean => n !== null && n > 0;

/** Wszystko, co telefon dał odczytać, poza innymi folderami i aplikacjami odznaczonymi przez silnik (podejrzane). */
export function defaultTransferSelection(inv: InventoryView): TransferSelection {
  return {
    contacts: readable(inv.contacts), sms: readable(inv.sms), mms: readable(inv.mms), calls: readable(inv.calls),
    categories: TRANSFER_CATEGORIES.filter((c) => (inv.categories[c]?.files ?? 0) > 0),
    others: [],
    apps: inv.apps.filter((a) => a.default_on).map((a) => a.package),
  };
}

/** Wybór przerwanej kopii (wznowienie dokłada do niej i nadpisuje jej wybór), zawężony do tego, co telefon
 *  ma teraz; kopia bez zapisanego wyboru — wybór domyślny. */
export function resumeSelection(inv: InventoryView, stored: Partial<TransferSelection> | undefined): TransferSelection {
  if (!stored || !Object.keys(stored).length) return defaultTransferSelection(inv);
  const others = new Set(inv.others.map((o) => o.name));
  const apps = new Set(inv.apps.map((a) => a.package));
  return {
    contacts: !!stored.contacts && readable(inv.contacts), sms: !!stored.sms && readable(inv.sms),
    mms: !!stored.mms && readable(inv.mms), calls: !!stored.calls && readable(inv.calls),
    categories: TRANSFER_CATEGORIES.filter((c) => (stored.categories ?? []).includes(c) && (inv.categories[c]?.files ?? 0) > 0),
    others: (stored.others ?? []).filter((o) => others.has(o)),
    apps: (stored.apps ?? []).filter((p) => apps.has(p)),
  };
}

/** Xiaomi, Redmi i POCO ukrywają odczyt SMS-ów i kontaktów za osobnym przełącznikiem w opcjach programisty. */
export function isXiaomi(device: { manufacturer?: string; brand?: string } | null | undefined): boolean {
  return /xiaomi|redmi|poco/i.test(`${device?.manufacturer ?? ''} ${device?.brand ?? ''}`);
}

/** MMS na dysku: załączniki jako pliki + te same dane w base64 w mms.xml (jak `MMS_FACTOR` w silniku). */
export const MMS_FACTOR = 2.4;

/** Rozmiar zaznaczonych danych, liczba zaznaczonych wierszy ekranu (SMS i MMS to jeden) i czas w minutach.
 *  Aplikacje liczą się tylko z rozmiarem z inwentarza — dziś go nie ma (`bytes: null`), więc ich nie wliczamy. */
export function transferTotals(inv: InventoryView, sel: TransferSelection): { bytes: number; categories: number; etaMin: number } {
  const others = new Set(sel.others);
  const apps = new Set(sel.apps);
  const bytes = (sel.mms ? Math.round(inv.mms_bytes * MMS_FACTOR) : 0)
    + sel.categories.reduce((n, c) => n + (inv.categories[c]?.bytes ?? 0), 0)
    + inv.others.filter((o) => others.has(o.name)).reduce((n, o) => n + o.bytes, 0)
    + inv.apps.filter((a) => apps.has(a.package)).reduce((n, a) => n + (a.bytes ?? 0), 0);
  const categories = [sel.contacts, sel.sms || sel.mms, sel.calls].filter(Boolean).length + sel.categories.length
    + (sel.others.length ? 1 : 0) + (sel.apps.length ? 1 : 0);
  return { bytes, categories, etaMin: Math.max(1, Math.round(bytes / TRANSFER_RATE / 60)) };
}

/** Szacowany rozmiar kopii jednej aplikacji (base + splity) — inwentarz nie zna rozmiarów aplikacji, a bez nich
 *  pasek dochodzi do 100% na plikach, choć APK jeszcze się kopiują. Próba 2026-10-25: 35 aplikacji, 3,3 GB. */
export const APK_ESTIMATE = 100 * 1024 ** 2;

/** Postęp kopii 0–1: bajty plików plus aplikacje po `APK_ESTIMATE`; bez bajtów — liczba plików i aplikacji. */
export function transferProgress(p: TransferProgress | null): number {
  if (!p) return 0;
  const doneApps = p.done_apps ?? 0;
  const totalApps = p.total_apps ?? 0;
  if (p.total_bytes > 0) {
    return (p.done_bytes + doneApps * APK_ESTIMATE) / (p.total_bytes + totalApps * APK_ESTIMATE);
  }
  const total = p.total_files + totalApps;
  return total > 0 ? (p.done_files + doneApps) / total : 0;
}

/** Etapy przenoszenia: stary telefon, kopia, nowy telefon, wgrywanie, protokół. */
export function transferStages(phase: Phase): StageState[] {
  switch (phase) {
    case 'transfer_choose':
    case 'transfer_backup':
      return ['done', 'now', 'todo', 'todo', 'todo'];
    case 'transfer_done':
    case 'transfer_restore_plan':
      return ['done', 'done', 'now', 'todo', 'todo'];
    case 'transfer_restore':
      return ['done', 'done', 'done', 'now', 'todo'];
    case 'transfer_restored':
      return ['done', 'done', 'done', 'done', 'todo'];
    default:
      return ['now', 'todo', 'todo', 'todo', 'todo'];
  }
}

export const isTransferPhase = (phase: Phase): boolean => phase.startsWith('transfer_');

/** Kopia czatów WhatsApp starsza niż godzina (albo jej brak): serwisant powinien zrobić nową na telefonie. */
export function whatsappStale(iso: string | null, now: Date): boolean {
  return iso === null || now.getTime() - new Date(iso).getTime() > 3_600_000;
}

/** Zielone „gotowe i sprawdzone” tylko dla pełnej kopii ze wszystkimi danymi telefonu i bez plików,
 *  których skan nie odczytał (`unreadable` z `copy.counts`). */
export function backupOutcome(r: BackupResultView, unreadable = 0): 'ok' | 'warn' | 'stopped' {
  if (r.status === 'stopped') return 'stopped';
  if (r.status !== 'complete' || unreadable > 0 || Object.values(r.telephony).some((c) => c.status !== 'ok')) return 'warn';
  return 'ok';
}

/** Kopia do wznowienia: najnowsza niedokończona tego egzemplarza (numer seryjny, nie model), jak `find_resumable`
 *  w mostku. `copies` przychodzą najnowsze pierwsze. */
export function resumableCopy(copies: CopyView[], serial: string | null): CopyView | null {
  return (serial && copies.find((c) => c.status === 'in_progress' && c.serial === serial)) || null;
}

/** Ile miejsca potrzeba jeszcze na kopię: przy wznowieniu tylko reszta (skopiowane już leży na dysku,
 *  a wolne miejsce zmalało właśnie o nie). Prawdziwą strażą jest sprawdzanie przed każdą paczką w silniku. */
export function transferNeed(selectedBytes: number, resumable: { bytes: number } | null): number {
  return Math.max(0, selectedBytes - (resumable?.bytes ?? 0));
}

// --- przenoszenie danych: wgrywanie kopii na nowy telefon ----------------------------------------

export const UPLOAD_GROUPS: readonly UploadGroup[] = ['photos', 'videos', 'downloads', 'whatsapp'];
export const otherGroup = (name: string): string => `other:${name}`;
const finished = (c: CopyView): boolean => c.status === 'complete' || c.status === 'incomplete';
const newest = (a: CopyView, b: CopyView): number => b.created.localeCompare(a.created);

/** Propozycja na ekranie Połącz: najnowsza skończona kopia innego telefonu niż podłączony (pełna przed niepełną).
 *  Kopia już w całości wgrana na ten telefon nie wraca jako propozycja. */
export function restoreOffer(copies: CopyView[], serial: string | null): CopyView | null {
  if (!serial) return null;
  const candidates = copies.filter((c) => finished(c) && c.serial !== serial
    && !(c.restores ?? []).some((r) => r.serial === serial && r.status === 'complete')).sort(newest);
  return candidates.find((c) => c.status === 'complete') ?? candidates[0] ?? null;
}

/** Kopia z przerwanym wgrywaniem na ten telefon (flaga `resumable` z mostu: zostały pliki do wgrania). */
export function restoreResumable(copies: CopyView[], serial: string | null): CopyView | null {
  if (!serial) return null;
  return [...copies].sort(newest).find((c) => (c.restores ?? []).some((r) => r.serial === serial && r.resumable)) ?? null;
}

/** Wszystkie grupy z plikami i wszystkie inne foldery kopii (każdy był w niej wybrany); podejrzane APK odznaczone. */
export function defaultUploadChoice(plan: RestorePlanView): UploadChoiceView {
  return {
    groups: [...UPLOAD_GROUPS.filter((g) => (plan.groups[g]?.files ?? 0) > 0),
      ...plan.others.filter((o) => o.files > 0).map((o) => otherGroup(o.name))],
    apks_on: [],
    verify_hash: false,
  };
}

/** Ta sama reguła co `RestorePlan.need/fits` w silniku. Sumy grup mają już APK według domyślnego wyboru
 *  (czyste i „nie do oceny”), bez szkodliwych i bez podejrzanych — dokładamy tylko zaznaczone podejrzane
 *  (`default_on` fałsz, nie szkodliwe), których jeszcze nie ma na telefonie. `missing`: ile brakuje do zapasu. */
export function uploadNeed(plan: RestorePlanView, choice: UploadChoiceView): { need: number; fits: boolean; missing: number } {
  const groups = new Set(choice.groups);
  const on = new Set(choice.apks_on);
  const base = UPLOAD_GROUPS.filter((g) => groups.has(g)).reduce((n, g) => n + (plan.groups[g]?.bytes ?? 0), 0)
    + plan.others.filter((o) => groups.has(otherGroup(o.name))).reduce((n, o) => n + o.bytes, 0);
  const ticked = plan.apks.filter((a) => groups.has(a.group) && a.action !== 'exists' && a.outcome !== 'malicious'
    && !a.default_on && on.has(a.remote)).reduce((n, a) => n + a.bytes, 0);
  const need = base + ticked;
  const missing = Math.max(0, need + plan.reserve - plan.space.free);
  return { need, fits: missing === 0, missing };
}

/** Zielone „Pliki wgrane” tylko, gdy wszystko weszło i galeria została odświeżona. */
export function restoreOutcome(r: RestoreResultView): 'ok' | 'warn' | 'stopped' {
  if (r.status === 'stopped') return 'stopped';
  if (r.status !== 'complete' || r.files_denied > 0 || r.files_failed > 0 || r.files_missing > 0 || r.media_scan !== 'done') {
    return 'warn';
  }
  return 'ok';
}
