import { describe, expect, test } from 'vitest';
import {
  changedVerdicts,
  dayKey,
  groupHistory,
  orderCounts,
  evidenceGroups,
  facetCounts,
  focusedApp,
  moveFocus,
  connectChecklist,
  defaultSelection,
  flaggedApps,
  formatUptime,
  groupSteps,
  guideHighlight,
  initial,
  levelTag,
  linkState,
  mergeSelection,
  modelName,
  planEntries,
  scanChecklist,
  signalChips,
  sourceKey,
  stageStates,
  upsertStep,
  visibleApps,
  formatGb,
  formatSize,
  verdictGroups,
  groupOpen,
  topReasons,
  notices,
} from './logic';
import type { AppView, Category, StepEvent, Finding, ScanView } from './types';

function app(pkg: string, verdict: AppView['verdict'], extra: Partial<AppView> = {}): AppView {
  const level = verdict === 'malicious' ? 'remove' : verdict === 'suspicious' ? 'disable' : null;
  return {
    package: pkg, name: pkg.split('.').at(-1)!, score: 0, verdict, verdict_label: verdict,
    confidence: 'high', confidence_label: 'high', gaps: [], scope: [],
    trusted: false, incomplete: false, is_system: false, from_play: true, installer: null,
    is_admin: false, default_level: level, problems: [], findings: [], apk_error: null, icon: null,
    ad_sdks: null, symptoms: [], source: { label: '', days: null }, capabilities: [], ...extra,
  };
}

const step = (id: number, pkg: string, status: StepEvent['status']): StepEvent => ({
  action_id: id, package: pkg, name: pkg, kind: 'enabled', label: 'x', status, error: null,
});

describe('selection', () => {
  const apps = [app('a.bad', 'malicious'), app('b.sus', 'suspicious'), app('c.rev', 'review'),
    app('d.ok', 'safe')];

  test('defaults follow the verdict', () => {
    expect(defaultSelection(apps)).toEqual({ 'a.bad': 'remove', 'b.sus': 'disable' });
  });

  test('merge keeps what the user touched', () => {
    const after = [app('a.bad', 'malicious'), app('b.sus', 'suspicious'),
      app('c.rev', 'suspicious'), app('d.ok', 'safe')];
    const merged = mergeSelection({ 'a.bad': 'silence' }, after, ['a.bad', 'b.sus']);
    expect(merged).toEqual({ 'a.bad': 'silence', 'c.rev': 'disable' });
    expect(changedVerdicts(apps, after)).toEqual(['c.rev']);
  });

  test('filters', () => {
    expect(flaggedApps(apps).map((a) => a.package)).toEqual(['a.bad', 'b.sus', 'c.rev']);
    const opts = { showAll: false, verdict: 'all' as const, query: '' };
    expect(visibleApps(apps, opts)).toHaveLength(3);
    expect(visibleApps(apps, { ...opts, showAll: true })).toHaveLength(4);
    expect(visibleApps(apps, { ...opts, verdict: 'suspicious' }).map((a) => a.package))
      .toEqual(['b.sus']);
    expect(visibleApps(apps, { ...opts, query: 'BAD' }).map((a) => a.package)).toEqual(['a.bad']);
  });

  const sy = (category: Category) => ({ category, severity: 'warn' as const, text: category });
  const faceted = [
    app('a.bad', 'malicious', { symptoms: [sy('ads'), sy('removal')], source: { label: 'Chrome', days: 1 } }),
    app('b.sus', 'suspicious', { symptoms: [sy('notif')], source: { label: 'Sklep Play', days: 3 } }),
    app('c.rev', 'review', { symptoms: [sy('ads')], source: { label: 'Sklep Play', days: 9 } }),
    app('d.ok', 'safe', { symptoms: [], source: { label: 'systemowa', days: null } }),
  ];

  test('category filter keeps apps with any of the chosen categories', () => {
    const opts = { showAll: true, verdict: 'all' as const, query: '' };
    expect(visibleApps(faceted, { ...opts, categories: ['ads'] }).map((a) => a.package))
      .toEqual(['a.bad', 'c.rev']);
    expect(visibleApps(faceted, { ...opts, categories: ['notif', 'removal'] }).map((a) => a.package))
      .toEqual(['a.bad', 'b.sus']);
    expect(visibleApps(faceted, { ...opts, categories: [] })).toHaveLength(4);
  });

  test('source filter keeps apps with that source label and combines with the others', () => {
    const opts = { showAll: true, verdict: 'all' as const, query: '' };
    expect(visibleApps(faceted, { ...opts, source: 'Sklep Play' }).map((a) => a.package))
      .toEqual(['b.sus', 'c.rev']);
    expect(visibleApps(faceted, { ...opts, source: 'Sklep Play', categories: ['ads'] })
      .map((a) => a.package)).toEqual(['c.rev']);
    expect(visibleApps(faceted, { ...opts, source: 'systemowa', showAll: false })).toHaveLength(0);
    expect(visibleApps(faceted, { ...opts, source: null })).toHaveLength(4);
  });

  test('facet counts: categories in fixed order, sources by count', () => {
    expect(facetCounts(faceted)).toEqual({
      categories: [{ value: 'ads', count: 2 }, { value: 'notif', count: 1 }, { value: 'removal', count: 1 }],
      sources: [{ value: 'Sklep Play', count: 2 }, { value: 'Chrome', count: 1 }, { value: 'systemowa', count: 1 }],
    });
  });
});

describe('steps and stages', () => {
  test('upsert and group', () => {
    let steps = upsertStep([], step(1, 'p', 'running'));
    steps = upsertStep(steps, step(2, 'q', 'running'));
    steps = upsertStep(steps, step(1, 'p', 'done'));
    expect(steps.map((s) => s.status)).toEqual(['done', 'running']);
    expect(groupSteps(steps).map((g) => g.package)).toEqual(['p', 'q']);
  });

  test('stage states per phase', () => {
    expect(stageStates('connect', null)).toEqual(['now', 'todo', 'todo', 'todo', 'todo']);
    expect(stageStates('scanning', 'collectors')).toEqual(['done', 'now', 'todo', 'todo', 'todo']);
    expect(stageStates('scanning', 'score')).toEqual(['done', 'done', 'now', 'todo', 'todo']);
    expect(stageStates('results', null)).toEqual(['done', 'done', 'done', 'now', 'todo']);
    expect(stageStates('done', null)).toEqual(['done', 'done', 'done', 'done', 'now']);
    expect(stageStates('done', null, true)).toEqual(['done', 'done', 'done', 'done', 'done']);
  });
});

describe('formatting', () => {
  test('uptime', () => {
    expect(formatUptime(3 * 86400 + 4 * 3600 + 60)).toBe('3 d 4 h');
    expect(formatUptime(5 * 3600 + 12 * 60)).toBe('5 h 12 min');
    expect(formatUptime(8 * 60 + 5)).toBe('8 min');
  });

  test('tags, chips and source', () => {
    expect(levelTag('remove')).toBe('tag-bad');
    expect(levelTag('disable')).toBe('tag-warn');
    expect(levelTag(null)).toBe('tag-gray');
    const a = app('x.y', 'malicious', {
      findings: [
        { rule_id: 'DM-ADMIN-01', class: 'position', weight: 20, text: '', text_expert: '', evidence: {}, category: 'removal', label: '', basis: 'granted', source: 'phone', locations: [] },
        { rule_id: 'DM-ADMIN-02', class: 'position', weight: 5, text: '', text_expert: '', evidence: {}, category: 'removal', label: '', basis: 'granted', source: 'phone', locations: [] },
        { rule_id: 'DM-BOOT-01', class: 'context', weight: 3, text: '', text_expert: '', evidence: {}, category: 'background', label: '', basis: 'declared', source: 'phone', locations: [] },
      ],
    });
    expect(signalChips(a)).toEqual([{ label: 'admin', bad: true }, { label: 'boot', bad: false }]);
    expect(sourceKey(app('p', 'safe', { is_system: true }))).toBe('system');
    expect(sourceKey(app('p', 'safe', { from_play: false }))).toBe('sideload');
  });
});

describe('connect logic', () => {
  const dev = (serial: string, state: string) => ({ serial, state, model: null });

  test('linkState', () => {
    expect(linkState([], 'adb_missing')).toBe('adb_missing');
    expect(linkState([], null)).toBe('none');
    expect(linkState([dev('A', 'unauthorized')], null)).toBe('unauthorized');
    expect(linkState([dev('A', 'offline')], null)).toBe('offline');
    expect(linkState([dev('A', 'device'), dev('B', 'unauthorized')], null)).toBe('ready');
    expect(linkState([dev('A', 'device'), dev('B', 'device')], null)).toBe('many');
  });

  test('connectChecklist', () => {
    expect(connectChecklist('none')).toEqual(['on', 'todo', 'todo']);
    expect(connectChecklist('unauthorized')).toEqual(['done', 'on', 'todo']);
    expect(connectChecklist('ready')).toEqual(['done', 'done', 'done']);
  });

  test('guideHighlight takes the quoted term or the last menu level', () => {
    expect(guideHighlight('Stuknij 7× „Numer wersji”')).toBe('Numer wersji');
    expect(guideHighlight('Tap “Build number” 7 times')).toBe('Build number');
    expect(guideHighlight('Ustawienia → O telefonie')).toBe('O telefonie');
  });

  test('initial and modelName', () => {
    expect(initial('  cleaner')).toBe('C');
    expect(initial('')).toBe('?');
    expect(modelName('SM_A145R')).toBe('SM A145R');
    expect(modelName(null)).toBe('?');
  });

  test('scanChecklist marks earlier stages done and the current one running', () => {
    expect(scanChecklist(null)).toEqual(['on', 'todo', 'todo', 'todo']);
    expect(scanChecklist('collectors')).toEqual(['done', 'done', 'on', 'todo']);
    expect(scanChecklist('score')).toEqual(['done', 'done', 'done', 'on']);
    expect(scanChecklist('apk')).toEqual(['done', 'done', 'done', 'done']);
  });
});

test('planEntries lists the selected apps in scan order', () => {
  const app = (pkg: string, name: string) => ({ package: pkg, name }) as never;
  expect(planEntries([app('a', 'A'), app('b', 'B'), app('c', 'C')], { c: 'remove', a: 'silence' }))
    .toEqual([{ package: 'a', name: 'A', level: 'silence' }, { package: 'c', name: 'C', level: 'remove' }]);
});

test('moveFocus stays inside the list and recovers a hidden row', () => {
  expect(moveFocus([], 'a', 1)).toBeNull();
  expect(moveFocus(['a', 'b', 'c'], 'a', -1)).toBe('a');
  expect(moveFocus(['a', 'b', 'c'], 'c', 1)).toBe('c');
  expect(moveFocus(['a', 'b', 'c'], 'b', 1)).toBe('c');
  expect(moveFocus(['a', 'b'], 'hidden', 1)).toBe('a');
  expect(focusedApp(['a', 'b'], 'b')).toBe('b');
  expect(focusedApp(['a', 'b'], 'x')).toBe('a');
  expect(focusedApp([], 'x')).toBeNull();
});

test('evidenceGroups: category order by heaviest rule, combos apart', () => {
  const f = (rule_id: string, category: string, weight: number) =>
    ({ rule_id, category, weight, label: rule_id, class: 'behavior', text: '', text_expert: '', evidence: {} }) as never;
  const out = evidenceGroups([f('S', 'origin', 8), f('O', 'ads', 25), f('A', 'removal', 25),
    f('H', 'removal', 15), f('C', 'combo', 15)]);
  expect(out.groups.map((g) => [g.category, g.items.map((i) => i.rule_id)])).toEqual([
    ['ads', ['O']], ['removal', ['A', 'H']], ['origin', ['S']]]);
  expect(out.combos.map((c) => c.rule_id)).toEqual(['C']);
});

test('groupHistory: one row per app with its state', () => {
  const a = (id: number, pkg: string, level: string, kind: string, status: string) =>
    ({ id, package: pkg, level, level_label: '', kind, step_label: kind, status, status_label: status, error: null }) as never;
  const rows = groupHistory([a(1, 'x', 'remove', 'backup', 'done'), a(2, 'x', 'remove', 'installed', 'done'),
    a(3, 'y', 'disable', 'enabled', 'undone'), a(4, 'z', 'disable', 'enabled', 'pending'),
    a(5, 'w', 'silence', 'notif', 'failed')]);
  expect(rows.map((r) => [r.package, r.state, r.backup, r.canRestore])).toEqual([
    ['x', 'done', true, true], ['y', 'restored', false, false], ['z', 'pending', false, false], ['w', 'failed', false, false]]);
  expect(orderCounts(rows)).toEqual([['remove', 1], ['disable', 2], ['silence', 1]]);
});

test('groupHistory: an app is restored when undo leaves only never-applied failed steps', () => {
  const a = (id: number, kind: string, status: string, error: string | null = null) =>
    ({ id, package: 'x', level: 'remove', level_label: '', kind, step_label: kind, status, status_label: status, error }) as never;
  const [row] = groupHistory([a(1, 'backup', 'undone'), a(2, 'admin', 'failed', 'declined'),
    a(3, 'enabled', 'failed', 'skipped'), a(4, 'installed', 'failed', 'skipped')]);
  expect([row.state, row.canRestore]).toEqual(['restored', false]);
});

test('dayKey', () => {
  const now = new Date(2026, 8, 27, 12, 0);
  expect(dayKey('2026-09-27T08:15', now)).toBe('today');
  expect(dayKey('2026-09-26T23:59', now)).toBe('yesterday');
  expect(dayKey('2026-08-12T09:12', now)).toBe('date');
});

test('formatGb uses one decimal and the language separator', () => {
  expect(formatGb(7.2 * 1024 ** 3, 'pl')).toBe('7,2');
  expect(formatGb(7.2 * 1024 ** 3, 'en')).toBe('7.2');
  expect(formatGb(0, 'pl')).toBe('0,0');
});

test('formatSize switches to MB below a tenth of a gigabyte', () => {
  expect(formatSize(30 * 1024 ** 2, 'pl')).toBe('30 MB');
  expect(formatSize(1, 'en')).toBe('1 MB');
  expect(formatSize(0, 'pl')).toBe('0,0 GB');
  expect(formatSize(7.2 * 1024 ** 3, 'en')).toBe('7.2 GB');
});

describe('repair screen grouping', () => {
  const apps = [app('a.rev', 'review'), app('b.bad', 'malicious'), app('c.ok', 'safe'), app('d.rev', 'review')];

  test('verdictGroups: four groups in fixed order, empty ones included, input order kept', () => {
    const g = verdictGroups(apps);
    expect(g.map((x) => x.verdict)).toEqual(['malicious', 'suspicious', 'review', 'safe']);
    expect(g[1].apps).toEqual([]);
    expect(g[2].apps.map((a) => a.package)).toEqual(['a.rev', 'd.rev']);
  });

  test('groupOpen: defaults per mode, saved choice wins, search opens everything', () => {
    expect(groupOpen('malicious', 'simple', {}, false)).toBe(true);
    expect(groupOpen('suspicious', 'expert', {}, false)).toBe(true);
    expect(groupOpen('review', 'expert', {}, false)).toBe(true);
    expect(groupOpen('review', 'simple', {}, false)).toBe(false);
    expect(groupOpen('safe', 'expert', {}, false)).toBe(false);
    expect(groupOpen('safe', 'simple', {}, false)).toBe(false);
    expect(groupOpen('review', 'simple', { review: true }, false)).toBe(true);
    expect(groupOpen('malicious', 'expert', { malicious: false }, false)).toBe(false);
    expect(groupOpen('safe', 'simple', { safe: false }, true)).toBe(true);
  });
});

describe('topReasons', () => {
  const f = (rule_id: string, category: Finding['category'], label: string, weight: number) =>
    ({ rule_id, category, label, weight, class: '', text: '', text_expert: '', evidence: {}, basis: 'observed',
      source: 'phone', locations: [] }) as Finding;
  const label = (c: Category) => `cat:${c}`;

  test('one label per category, by weight, combos and zero weights skipped, rest counted', () => {
    const a = app('x.y', 'suspicious', { findings: [
      f('A1', 'ads', 'Wiele sieci reklamowych', 25), f('A2', 'ads', 'Okna nad innymi', 10),
      f('D1', 'data', 'Czyta powiadomienia', 10), f('C1', 'combo', 'Kombinacja', 30),
      f('O1', 'origin', 'Świeża instalacja', 0), f('S1', 'disguise', 'Niewidoczne znaki', 8),
    ] });
    const r = topReasons(a, 2, label);
    expect(r.items).toEqual([{ category: 'ads', label: 'Wiele sieci reklamowych' },
      { category: 'data', label: 'Czyta powiadomienia' }]);
    expect(r.more).toEqual(['disguise']);
  });

  test('equal weights fall back to the category order', () => {
    const a = app('x.y', 'review', { findings: [f('B', 'background', 'Tło', 5), f('A', 'ads', 'Reklamy', 5)] });
    expect(topReasons(a, 1, label).items[0].category).toBe('ads');
  });

  test('no findings: symptom categories by name, never an empty reason', () => {
    const a = app('x.y', 'review', { symptoms: [{ category: 'notif', severity: 'warn', text: '…' },
      { category: 'origin', severity: 'neutral', text: '…' }] });
    expect(topReasons(a, 1, label)).toEqual({ items: [{ category: 'notif', label: 'cat:notif' }], more: ['origin'] });
  });
});

describe('notices', () => {
  const scan = (extra: Partial<ScanView> = {}) => ({
    collectors: { ok: 8, total: 8, failed: [] }, low_behavior_data: false, apk: null, apps: [],
    profiles: { others: [], known: true }, usage_window_h: 1.5,
    counts: { malicious: 0, suspicious: 0, review: 0, safe: 0, non_play: 0, admins: 0, total: 0, user: 0 }, ...extra,
  }) as ScanView;
  const base = { sdk: 34, selectLevel: 'silence' as const, missing: [], withGaps: 0 };

  test('nothing to say on a modern phone with full data', () => {
    expect(notices({ ...base, scan: scan() })).toEqual([]);
  });

  test('warnings first, then info; params for the full texts', () => {
    const n = notices({ ...base, sdk: 31, scan: scan({ low_behavior_data: true, profiles: { others: [10], known: true } }),
      missing: ['device_policy'], withGaps: 3 });
    expect(n.map((x) => x.key)).toEqual(['low_data', 'incomplete', 'profiles', 'notifications_manual', 'select_level_disable']);
    expect(n.map((x) => x.tone)).toEqual(['warn', 'warn', 'warn', 'info', 'info']);
    expect(n[0].params).toEqual({ hours: '1.5' });
    expect(n[1].params).toEqual({ count: 3, names: 'device_policy' });
    expect(n[2].params).toEqual({ ids: '10' });
  });

  test('unknown profile list; disable as the default action needs no swap note', () => {
    const n = notices({ ...base, sdk: 31, selectLevel: 'disable', scan: scan({ profiles: { others: [], known: false } }) });
    expect(n.map((x) => x.key)).toEqual(['profiles_unknown', 'notifications_manual']);
  });
});
