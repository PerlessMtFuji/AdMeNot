import { CATEGORY_ORDER } from './categories';
import type { AppView, Category, DeviceEntry, Finding, HistoryAction, Level, StepEvent, Verdict } from './types';

export type Phase = 'connect' | 'scanning' | 'results' | 'executing' | 'done';
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
    && (!opts.source || a.source.label === opts.source));
}

// Opcje filtrów tabeli eksperta: kategorie w stałej kolejności, źródła od najczęstszego.
export function facetCounts(apps: AppView[]): {
  categories: { value: Category; count: number }[];
  sources: { value: string; count: number }[];
} {
  const categories = CATEGORY_ORDER
    .map((value) => ({ value, count: apps.filter((a) => a.symptoms.some((sy) => sy.category === value)).length }))
    .filter((c) => c.count > 0);
  const bySource = new Map<string, number>();
  for (const a of apps) bySource.set(a.source.label, (bySource.get(a.source.label) ?? 0) + 1);
  const sources = [...bySource].map(([value, count]) => ({ value, count }))
    .sort((x, y) => y.count - x.count || x.value.localeCompare(y.value));
  return { categories, sources };
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

/** Termin do podświetlenia na miniaturze ekranu: tekst w cudzysłowie albo ostatni poziom menu. */
export function guideHighlight(text: string): string {
  const quoted = text.match(/[„“"]([^”"]+)[”"]/);
  if (quoted) return quoted[1];
  const parts = text.split('→');
  return parts[parts.length - 1].trim();
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

export const LEVEL_TONE: Record<Level, 'accent' | 'warn' | 'bad'> = { silence: 'accent', disable: 'warn', remove: 'bad' };
export const VERDICT_TONE: Record<Verdict, 'bad' | 'warn' | 'neutral' | 'ok'> = {
  malicious: 'bad', suspicious: 'warn', review: 'neutral', safe: 'ok',
};

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
  level: Level;
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
      row = { package: a.package, level: a.level as Level, state: 'done', actions: [], backup: false, canRestore: false };
      rows.push(row);
    }
    row.actions.push(a);
  }
  for (const r of rows) {
    const statuses = r.actions.map((a) => a.status);
    // Po cofnięciu zostają „failed” tylko kroki, które niczego nie zmieniły (np. pominięte).
    const restored = statuses.includes('undone') && !statuses.includes('done') && !statuses.includes('pending');
    r.state = restored ? 'restored'
      : statuses.includes('pending') ? 'pending' : statuses.includes('failed') ? 'failed' : 'done';
    r.backup = r.actions.some((a) => a.kind === 'backup' && a.status === 'done');
    r.canRestore = statuses.includes('done');
  }
  return rows;
}

export function orderCounts(rows: HistoryAppRow[]): [Level, number][] {
  const out: [Level, number][] = [];
  for (const level of ['remove', 'disable', 'silence'] as Level[]) {
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
