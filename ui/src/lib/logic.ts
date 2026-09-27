import type { AppView, DeviceEntry, Level, StepEvent, Verdict } from './types';

export type Phase = 'connect' | 'scanning' | 'results' | 'executing' | 'done';
export type StageState = 'done' | 'now' | 'todo' | 'off';

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
  opts: { showAll: boolean; verdict: Verdict | 'all'; query: string }): AppView[] {
  const q = opts.query.trim().toLowerCase();
  return apps.filter((a) =>
    (opts.showAll || a.verdict !== 'safe')
    && (opts.verdict === 'all' || a.verdict === opts.verdict)
    && (!q || a.name.toLowerCase().includes(q) || a.package.toLowerCase().includes(q)));
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

export function stageStates(phase: Phase, scanStage: string | null): StageState[] {
  switch (phase) {
    case 'connect':
      return ['now', 'todo', 'todo', 'todo', 'off'];
    case 'scanning':
      return READ_STAGES.has(scanStage ?? 'identify')
        ? ['done', 'now', 'todo', 'todo', 'off']
        : ['done', 'done', 'now', 'todo', 'off'];
    case 'results':
    case 'executing':
      return ['done', 'done', 'done', 'now', 'off'];
    case 'done':
      return ['done', 'done', 'done', 'done', 'off'];
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

export function initial(name: string): string {
  return (name.trim()[0] ?? '?').toUpperCase();
}

export function modelName(model: string | null): string {
  return model ? model.replaceAll('_', ' ') : '?';
}
