import { describe, expect, test } from 'vitest';
import fixture from '../../../tests/fixtures/bridge/transfer_restore.json';
import type { CopyView, InventoryView, RestoreApk, RestorePlanView, RestoreResultView } from './types';
import {
  backupOutcome,
  defaultUploadChoice,
  keptUploadChoice,
  restoreOffer,
  restoreOutcome,
  restoreResumable,
  uploadNeed,
  changedVerdicts,
  defaultTransferSelection,
  exportDefaults,
  keptExport,
  rescanSelection,
  isXiaomi,
  APK_ESTIMATE,
  resumableCopy,
  transferProgress,
  resumeSelection,
  transferNeed,
  transferStages,
  transferTotals,

  whatsappStale,
  dayKey,
  groupHistory,
  siteState,
  orderCounts,
  evidenceGroups,
  facetCounts,
  SOURCE_NON_PLAY,
  focusedApp,
  moveFocus,
  connectChecklist,
  defaultSelection,
  flaggedApps,
  formatUptime,
  groupSteps,
  guidePath,
  guideTerms,
  initial,
  levelTag,
  linkState,
  mergeSelection,
  modelName,
  planEntries,
  planGroups,
  runnableApps,
  actedAfter,
  offeredFixes,
  shownChecks,
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
  updateBanner,
  needsWelcome,
  groupCheck,
  bulkNeedsConfirm,
  factTags,
  isManual,
  modeUndecided,
  manualRows,
  stableEta,
} from './logic';

const MB = 1024 ** 2;
import { CHECKS_SAMPLE } from './fakeBridge';
import type { AppView, Category, Level, PlanApp, PlanView, StepEvent, Finding, ScanView, Settings, UpdateView } from './types';

function app(pkg: string, verdict: AppView['verdict'], extra: Partial<AppView> = {}): AppView {
  const level = verdict === 'malicious' ? 'remove' : verdict === 'suspicious' ? 'disable' : null;
  return {
    package: pkg, name: pkg.split('.').at(-1)!, score: 0, verdict, verdict_label: verdict,
    confidence: 'high', confidence_label: 'high', gaps: [], scope: [],
    trusted: false, incomplete: false, is_system: false, enabled: true, from_play: true, installer: null,
    is_admin: false, default_level: level, problems: [], findings: [], apk_error: null, icon: null,
    ad_sdks: null, symptoms: [], source: { label: '', days: null }, capabilities: [], first_install: null, ...extra,
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

  test('synthetic “outside the Play Store” source: not Play and not system, with a count', () => {
    const mixed = [
      app('p.play', 'review', { from_play: true, is_system: false }),
      app('p.side', 'suspicious', { from_play: false, is_system: false }),
      app('p.side2', 'safe', { from_play: false, is_system: false }),
      app('p.sys', 'safe', { from_play: false, is_system: true }),
    ];
    const opts = { showAll: true, verdict: 'all' as const, query: '' };
    expect(visibleApps(mixed, { ...opts, source: SOURCE_NON_PLAY }).map((a) => a.package))
      .toEqual(['p.side', 'p.side2']);
    expect(facetCounts(mixed).nonPlay).toBe(2);
  });

  test('facet counts: categories in fixed order, sources by count', () => {
    expect(facetCounts(faceted)).toMatchObject({
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

  test('guideTerms marks every quoted on-screen name', () => {
    expect(guideTerms('Stuknij 7 razy „Wersja MIUI” albo „Wersja HyperOS”')).toEqual([
      { text: 'Stuknij 7 razy ', term: false }, { text: 'Wersja MIUI', term: true },
      { text: ' albo ', term: false }, { text: 'Wersja HyperOS', term: true },
    ]);
    expect(guideTerms('Tap “Build number” 7 times')).toEqual([
      { text: 'Tap ', term: false }, { text: 'Build number', term: true }, { text: ' 7 times', term: false },
    ]);
    expect(guideTerms('Włącz debugowanie USB')).toEqual([{ text: 'Włącz debugowanie USB', term: false }]);
  });

  test('guidePath splits the menu levels', () => {
    expect(guidePath('Ustawienia → Opcje programisty → Debugowanie USB'))
      .toEqual(['Ustawienia', 'Opcje programisty', 'Debugowanie USB']);
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

test('groupHistory: a site channel step left done can be restored', () => {
  const [row] = groupHistory([{ id: 1, package: 'c', level: 'fix', level_label: '', kind: 'channel', step_label: '',
    status: 'done', status_label: '', error: null }]);
  expect(row.canRestore).toBe(true);
});

test('siteState follows undo steps and the current wait', () => {
  const site = (action_id: number) => ({ action_id, package: 'c', browser: 'Chrome', site: 'a.example' });
  const step = (action_id: number, status: 'undone' | 'failed' | 'running', error_key: string | null = null) =>
    ({ action_id, package: 'c', name: 'Chrome', kind: 'channel', label: '', status, error: error_key ? 'tekst' : null, error_key });
  const steps = [step(1, 'undone'), step(2, 'failed', 'site_skipped'), step(3, 'failed', 'channel_gone'), step(4, 'running'),
    step(6, 'failed', 'user_timeout')];
  const wait = { package: 'c', name: 'Chrome', kind: 'channel' as const, timeout: 180, action_id: 4 };
  expect([1, 2, 3, 4, 5, 6].map((id) => siteState(site(id), steps, wait)))
    .toEqual(['done', 'skipped', 'gone', 'current', 'waiting', 'skipped']);
  expect(siteState(site(4), steps, null)).toBe('waiting');
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

test('update banner priority', () => {
  const none: UpdateView = { available: null, dismissed: false, retired: null, updated_to: null, updated_notes: null, installable: true };
  const available = { ...none, available: { version: '9.9.9', notes: 'n', size: 1 } };
  expect(updateBanner(null, false)).toBeNull();
  expect(updateBanner(none, false)).toBeNull();
  expect(updateBanner(available, false)).toBe('available');
  expect(updateBanner({ ...available, dismissed: true }, false)).toBeNull();
  expect(updateBanner({ ...available, dismissed: true, retired: { min_supported: '9.0.0', reason: null } }, false)).toBe('retired');
  expect(updateBanner({ ...none, updated_to: '0.9.3' }, false)).toBe('updated');
  expect(updateBanner({ ...none, updated_to: '0.9.3' }, true)).toBeNull();
});

describe('needsWelcome', () => {
  const base = { welcome_version: 1, welcome_current: 1 } as Settings;
  test('pokazuje ekran przed akceptacją i po podniesieniu wersji', () => {
    expect(needsWelcome({ ...base, welcome_version: null })).toBe(true);
    expect(needsWelcome({ ...base, welcome_current: 2 })).toBe(true);
    expect(needsWelcome(base)).toBe(false);
  });
});

describe('plan groups', () => {
  const app = (name: string, level: Level, steps: string[], extra: Partial<PlanApp> = {}): PlanApp => ({
    package: `p.${name}`, name, level, level_label: '', blocked: false, reason: null, reason_text: null,
    steps, warnings: [], ...extra });

  test('groups by action, strongest first, skipped last, names sorted by the UI language', () => {
    const groups = planGroups([
      app('Żaba', 'silence', ['a']), app('Ala', 'remove', ['x']), app('Ćma', 'silence', ['a']),
      app('Cebula', 'silence', ['a']), app('System', 'remove', [], { blocked: true }), app('Bęben', 'disable', ['d']),
    ], 'pl');
    expect(groups.map((g) => g.key)).toEqual(['remove', 'disable', 'silence', 'blocked']);
    expect(groups.map((g) => g.apps.map((a) => a.name))).toEqual([['Ala'], ['Bęben'], ['Cebula', 'Ćma', 'Żaba'], ['System']]);
  });

  test('one step list per group in execution order, steps not for every app name their apps', () => {
    const [g] = planGroups([
      app('Ultimate', 'disable', ['powiadomienia', 'zatrzymanie', 'wyłączenie'], { warnings: ['konto'] }),
      app('IntelliClean', 'disable', ['zatrzymanie', 'wyłączenie'], { warnings: [] }),
    ], 'pl');
    expect(g.apps.map((a) => a.name)).toEqual(['IntelliClean', 'Ultimate']);
    expect(g.steps).toEqual([
      { text: 'powiadomienia', only: ['Ultimate'] }, { text: 'zatrzymanie', only: [] }, { text: 'wyłączenie', only: [] },
    ]);
    expect(g.warnings).toEqual([{ text: 'konto', only: ['Ultimate'] }]);
  });

  test('a step only some apps have keeps its place between the shared ones', () => {
    const [g] = planGroups([
      app('A', 'remove', ['zgoda', 'stop', 'odinstalowanie']),
      app('B', 'remove', ['zgoda', 'okna', 'stop', 'odinstalowanie']),
    ], 'pl');
    expect(g.steps.map((x) => x.text)).toEqual(['zgoda', 'okna', 'stop', 'odinstalowanie']);
    expect(g.steps[1].only).toEqual(['B']);
  });
});

describe('group select-all (bulk actions)', () => {
  const apps = [app('a', 'malicious'), app('b', 'malicious'), app('c', 'malicious')];

  test('the group checkbox is empty, partial or full; removed apps do not count', () => {
    expect(groupCheck(apps, {}, {})).toBe('none');
    expect(groupCheck(apps, { a: 'disable' }, {})).toBe('some');
    expect(groupCheck(apps, { a: 'disable', b: 'silence', c: 'remove' }, {})).toBe('all');
    expect(groupCheck(apps, { a: 'disable', b: 'silence' }, { c: 'remove' })).toBe('all');
    expect(groupCheck(apps, {}, { a: 'remove', b: 'remove', c: 'remove' })).toBe('none');
  });

  test('only disable and remove ask for confirmation; silence is the mild one', () => {
    expect(bulkNeedsConfirm({ a: 'silence', b: 'silence' })).toBe(false);
    expect(bulkNeedsConfirm({ a: 'silence', b: 'disable' })).toBe(true);
    expect(bulkNeedsConfirm({ a: 'remove' })).toBe(true);
    expect(bulkNeedsConfirm({})).toBe(false);
  });
});

describe('tryb ręczny', () => {
  const scan = (apk_mode: ScanView['apk_mode']) => ({ apk_mode }) as ScanView;

  test('isManual', () => {
    expect(isManual(null)).toBe(false);
    expect(isManual(scan('pending'))).toBe(false);
    expect(isManual(scan('full'))).toBe(false);
    expect(isManual(scan('manual'))).toBe(true);
    expect(isManual(scan('partial'))).toBe(true);
  });

  test('modeUndecided: tylko przy trwającej analizie raportu „pending”, bez „zawsze pełna” i bez wyboru pełnej', () => {
    const base = { scan: scan('pending'), setting: 'ask' as const, running: true, fullChosen: false };
    expect(modeUndecided(base)).toBe(true);
    expect(modeUndecided({ ...base, setting: 'manual' })).toBe(true);
    expect(modeUndecided({ ...base, setting: 'full' })).toBe(false);
    expect(modeUndecided({ ...base, fullChosen: true })).toBe(false);
    expect(modeUndecided({ ...base, running: false })).toBe(false);
    expect(modeUndecided({ ...base, scan: scan('manual') })).toBe(false);
    expect(modeUndecided({ ...base, scan: null })).toBe(false);
  });

  test('manualRows: najświeższe pierwsze, bez daty na końcu, systemowe ukryte', () => {
    const apps = [
      app('a', 'safe', { first_install: '2026-10-01T10:00:00' }),
      app('b', 'safe', { first_install: null }),
      app('c', 'safe', { first_install: '2026-10-15T10:00:00' }),
      app('d', 'safe', { first_install: '2026-10-16T10:00:00', is_system: true }),
    ];
    expect(manualRows(apps, { query: '', showSystem: false, source: null }).map((a) => a.package)).toEqual(['c', 'a', 'b']);
    expect(manualRows(apps, { query: '', showSystem: true, source: null })[0].package).toBe('d');
    expect(manualRows(apps, { query: 'c', showSystem: false, source: null }).map((a) => a.package)).toEqual(['c']);
  });

  test('factTags tylko z faktów szybkiego skanu', () => {
    const cap = (key: string, levels: Partial<AppView['capabilities'][number]['levels']>) =>
      ({ key, label: '', levels: { declared: null, code: null, granted: null, observed: null, ...levels } });
    const tags = factTags(app('x', 'safe', { from_play: false, is_admin: true, enabled: false, is_system: false,
      capabilities: [cap('accessibility', { granted: true }), cap('overlay', { declared: true })] }));
    expect(tags).toEqual(['non_play', 'admin', 'accessibility', 'disabled']); // overlay tylko zadeklarowany — bez znacznika
  });

  test('stableEta nie podnosi czasu o mniej niż minutę', () => {
    expect(stableEta(null, 300)).toBe(300);
    expect(stableEta(300, 280)).toBe(280);
    expect(stableEta(300, 340)).toBe(300);
    expect(stableEta(300, 380)).toBe(380);
    expect(stableEta(300, null)).toBeNull();
  });
});

describe('phone checks', () => {
  const fixApp = (pkg: string, over: Partial<PlanApp> = {}): PlanApp => ({ package: pkg, name: pkg, level: 'fix',
    level_label: 'Ustawienia witryn', blocked: false, reason: null, reason_text: null, steps: ['a'], warnings: [], ...over });

  test('plan groups put site fixes after silence and before the skipped ones', () => {
    const groups = planGroups([fixApp('b.chrome'), fixApp('x', { blocked: true, reason: 'browser_removed', reason_text: '…' }),
      { ...fixApp('a.app'), level: 'silence' }], 'pl');
    expect(groups.map((g) => g.key)).toEqual(['silence', 'fix', 'blocked']);
  });

  test('runnableApps: one row per browser with its app level, the fix steps kept', () => {
    const plan = { runnable: 3, code: 'K7F3', apps: [
      fixApp('com.android.chrome', { steps: ['site a'] }),
      { ...fixApp('com.android.chrome'), level: 'silence', level_label: 'WYCISZ', steps: ['notif'] },
      fixApp('org.mozilla.firefox', { steps: ['site b'] }),
      fixApp('x', { blocked: true, reason: 'protected', reason_text: '…' })] } as PlanView;
    const rows = runnableApps(plan);
    expect(rows.map((a) => [a.package, a.level, a.steps])).toEqual([
      ['com.android.chrome', 'silence', ['site a', 'notif']], ['org.mozilla.firefox', 'fix', ['site b']]]);
    expect(runnableApps(null)).toEqual([]);
    // Wyciszenie przeglądarki z poprawką liczy się jako wyciszenie (do „Wróć do naprawy”).
    const result = { order: 'Z', status: 'done', status_label: '', stopped: false,
      apps: [{ package: 'com.android.chrome', name: 'Chrome', outcome: 'ok' as const, errors: [], kinds: [] }] };
    expect(actedAfter({}, plan, result)).toEqual({ 'com.android.chrome': [{ order: 'Z', level: 'silence' }] });
  });

  test('offeredFixes lists every site fix and every all-sites fix', () => {
    expect(offeredFixes([CHECKS_SAMPLE])).toEqual([
      CHECKS_SAMPLE.browsers[0].sites[0].fix, CHECKS_SAMPLE.browsers[0].sites[1].fix, CHECKS_SAMPLE.browsers[1].all_fix]);
  });

  test('an unreadable check becomes a notice, a readable one does not', () => {
    const scan = (state: 'ok' | 'unrecognized') => ({ collectors: { ok: 8, total: 8, failed: [] }, low_behavior_data: false,
      profiles: { others: [], known: true }, apps: [],
      device_checks: [{ id: 'site_notifications', state, state_label: '', browsers: [] }] }) as unknown as ScanView;
    const base = { sdk: 34, selectLevel: 'silence' as const, missing: [], withGaps: 0 };
    expect(notices({ ...base, scan: scan('unrecognized') }).map((n) => n.key)).toEqual(['checks_unreadable']);
    expect(notices({ ...base, scan: scan('ok') })).toEqual([]);
    expect(shownChecks(scan('unrecognized'))).toEqual([]);
  });

  test('history: a fix-only order counts as site settings, and a channel step has no automatic restore', () => {
    const action = (id: number, level: string, kind: string, manual: string | null) => ({ id, package: 'chrome', level, level_label: '', kind,
      step_label: '', status: 'done', status_label: '', error: null, manual_undo: manual });
    const rows = groupHistory([action(1, 'fix', 'channel', 'Ustawienia › Powiadomienia')]);
    expect(orderCounts(rows)).toEqual([['fix', 1]]);
    expect(rows[0].canRestore).toBe(false);
    const mixed = groupHistory([action(1, 'fix', 'channel', 'x'), action(2, 'silence', 'notif', null)]);
    expect(mixed[0].level).toBe('silence');
    expect(mixed[0].canRestore).toBe(true);
    // Po cofnięciu kanał zostaje „done” (przywraca się go ręcznie): aplikacja jest przywrócona.
    const undone = groupHistory([action(1, 'fix', 'channel', 'x'), { ...action(2, 'silence', 'notif', null), status: 'undone' }]);
    expect(undone[0].state).toBe('restored');
    expect(undone[0].canRestore).toBe(false);
  });
});

describe('data transfer', () => {
  const inv = (over: Partial<InventoryView> = {}): InventoryView => ({
    contacts: 2, sms: 5, mms: 1, mms_bytes: 3000, calls: 4,
    categories: { media: { files: 2, bytes: 5000 }, downloads: { files: 0, bytes: 0 }, whatsapp: { files: 1, bytes: 800 } },
    others: [{ name: '', files: 1, bytes: 10 }, { name: 'Music', files: 1, bytes: 400 }],
    apps: [
      { package: 'a.ok', label: 'A', verdict: 'safe', default_on: true, bytes: null },
      { package: 'b.sus', label: 'B', verdict: 'suspicious', default_on: false, bytes: null },
    ],
    skipped_apps: [{ package: 'c.bad', label: 'C' }],
    whatsapp_backup: null, storage: null, free_pc: 10 ** 12, unreadable: 0, denied: [], exports: {}, ...over,
  });

  test('default selection: everything readable, no other folders, suspicious apps off', () => {
    expect(defaultTransferSelection(inv())).toEqual({
      contacts: true, sms: true, mms: true, calls: true, categories: ['media', 'whatsapp'], others: [], apps: ['a.ok'], exports: {},
    });
  });

  test('unreadable or empty phone data starts unticked', () => {
    const sel = defaultTransferSelection(inv({ sms: null, mms: 0, contacts: null }));
    expect([sel.contacts, sel.sms, sel.mms, sel.calls]).toEqual([false, false, false, true]);
  });

  test('totals sum the selected bytes and count the ticked rows', () => {
    const data = inv();
    const sel = defaultTransferSelection(data);
    // kontakty, SMS i MMS, połączenia, zdjęcia, WhatsApp, aplikacje; MMS na dysku × 2,4 (jak w silniku)
    expect(transferTotals(data, sel)).toEqual({ bytes: 3000 * 2.4 + 5000 + 800, categories: 6, etaMin: 1 });
    const more = { ...sel, mms: false, sms: false, others: ['Music', ''], apps: [] };
    expect(transferTotals(data, more)).toEqual({ bytes: 5000 + 800 + 410, categories: 5, etaMin: 1 });
  });

  test('ETA assumes 25 MB/s and never drops below a minute', () => {
    const big = inv({ categories: { media: { files: 1, bytes: 25 * 1024 ** 2 * 60 * 10 }, downloads: { files: 0, bytes: 0 },
      whatsapp: { files: 0, bytes: 0 } } });
    expect(transferTotals(big, defaultTransferSelection(big)).etaMin).toBe(10);
  });

  test('a resumed copy starts from its stored selection, narrowed to what the phone still has', () => {
    const data = inv();
    expect(resumeSelection(data, undefined)).toEqual(defaultTransferSelection(data));
    expect(resumeSelection(data, {})).toEqual(defaultTransferSelection(data));
    expect(resumeSelection(data, { contacts: false, sms: true, mms: false, calls: true,
      categories: ['downloads', 'media'], others: ['Music', 'Gone'], apps: ['b.sus', 'x.removed'] })).toEqual({
      contacts: false, sms: true, mms: false, calls: true, categories: ['media'], others: ['Music'], apps: ['b.sus'], exports: {} });
    expect(resumeSelection(inv({ sms: null }), { sms: true }).sms).toBe(false);
  });

  const file = (remote: string, count: number | null = 3) =>
    ({ remote, name: remote.split('/').at(-1)!, size: 100, mtime: '2026-10-27T20:41:00', count });
  const denied = (contacts: string[], sms: string[] = []) => inv({
    contacts: null, sms: sms.length ? null : 5, mms: sms.length ? null : 1, denied: sms.length ? ['contacts', 'sms'] : ['contacts'],
    exports: { contacts: contacts.map((r) => file(r)), ...(sms.length ? { sms: sms.map((r) => file(r)) } : {}) },
  });

  test('export defaults: the newest file of each kind', () => {
    expect(exportDefaults(inv())).toEqual({});
    expect(exportDefaults(denied(['/sdcard/new.vcf', '/sdcard/old.vcf'], ['/sdcard/sms.xml'])))
      .toEqual({ contacts: '/sdcard/new.vcf', sms: '/sdcard/sms.xml' });
  });

  test('a denied category with an export file starts ticked from the newest file; SMS from a file has no MMS', () => {
    const sel = defaultTransferSelection(denied(['/sdcard/new.vcf', '/sdcard/old.vcf'], ['/sdcard/sms.xml']));
    expect([sel.contacts, sel.sms, sel.mms, sel.calls]).toEqual([true, true, false, true]);
    expect(sel.exports).toEqual({ contacts: '/sdcard/new.vcf', sms: '/sdcard/sms.xml' });
    expect(defaultTransferSelection(denied([])).contacts).toBe(false);
  });

  test('after a rescan the newest file wins unless the technician picked an older one that is still there', () => {
    const before = denied(['/sdcard/a.vcf', '/sdcard/b.vcf']);
    const newer = denied(['/sdcard/new.vcf', '/sdcard/a.vcf', '/sdcard/b.vcf']);
    // wybrany był najnowszy — pojawił się nowszy
    expect(keptExport({ contacts: '/sdcard/a.vcf' }, before, newer)).toEqual({ contacts: '/sdcard/new.vcf' });
    // wybrany starszy plik nadal jest na liście
    expect(keptExport({ contacts: '/sdcard/b.vcf' }, before, newer)).toEqual({ contacts: '/sdcard/b.vcf' });
    // wybrany plik zniknął
    expect(keptExport({ contacts: '/sdcard/b.vcf' }, before, denied(['/sdcard/new.vcf', '/sdcard/a.vcf'])))
      .toEqual({ contacts: '/sdcard/new.vcf' });
    // pierwszy plik po ponownym skanie
    expect(keptExport({}, denied([]), newer)).toEqual({ contacts: '/sdcard/new.vcf' });
    expect(keptExport({ contacts: '/sdcard/a.vcf' }, before, denied([]))).toEqual({});
  });

  test('a rescan keeps the other choices and ticks a category whose first export file just appeared', () => {
    const before = denied([]);
    const prev = { ...defaultTransferSelection(before), calls: false, categories: ['media' as const] };
    const sel = rescanSelection(prev, before, denied(['/sdcard/new.vcf']));
    expect(sel).toEqual({ ...prev, contacts: true, exports: { contacts: '/sdcard/new.vcf' } });
    // odznaczony wiersz z plikiem zostaje odznaczony
    const had = denied(['/sdcard/a.vcf']);
    const off = { ...defaultTransferSelection(had), contacts: false };
    expect(rescanSelection(off, had, denied(['/sdcard/new.vcf', '/sdcard/a.vcf'])).contacts).toBe(false);
  });

  test('a resumed copy reuses its stored export file when it is still offered, else the newest', () => {
    const data = denied(['/sdcard/new.vcf', '/sdcard/old.vcf']);
    const stored = (remote: string) => ({ contacts: true, exports: [{ kind: 'contacts' as const, remote, size: 1, mtime: 1 }] });
    expect(resumeSelection(data, stored('/sdcard/old.vcf')).exports).toEqual({ contacts: '/sdcard/old.vcf' });
    expect(resumeSelection(data, stored('/sdcard/gone.vcf')).exports).toEqual({ contacts: '/sdcard/new.vcf' });
    expect(resumeSelection(data, stored('/sdcard/old.vcf')).contacts).toBe(true);
  });

  test('copy progress counts apps with an estimated size, so copied files alone do not fill the bar', () => {
    const p = (done_files: number, done_bytes: number, done_apps: number, total_apps: number) =>
      ({ stage: 'files', done_files, total_files: 10, done_bytes, total_bytes: 1000 * MB, current: '', done_apps, total_apps }) as const;
    expect(transferProgress(null)).toBe(0);
    expect(transferProgress(p(5, 500 * MB, 0, 0))).toBeCloseTo(0.5);
    expect(transferProgress(p(10, 1000 * MB, 0, 10))).toBeCloseTo(1000 / (1000 + 10 * APK_ESTIMATE / MB));
    expect(transferProgress(p(10, 1000 * MB, 10, 10))).toBe(1);
    // same aplikacje, bez plików: liczba aplikacji
    expect(transferProgress({ ...p(0, 0, 3, 4), total_files: 0, total_bytes: 0 })).toBeCloseTo(0.75);
    // starszy most bez liczników aplikacji
    expect(transferProgress({ stage: 'files', done_files: 2, total_files: 4, done_bytes: 0, total_bytes: 0, current: '' } as never))
      .toBeCloseTo(0.5);
  });

  test('the copy to resume is the newest unfinished one of this very phone, not just the same model', () => {
    const copy = (id: string, serial: string, status: 'in_progress' | 'complete' | 'incomplete') =>
      ({ id, serial, model: 'SM-A137F', status }) as never;
    const copies = [copy('A/3', 'A', 'complete'), copy('B/2', 'B', 'in_progress'), copy('A/2', 'A', 'in_progress'),
      copy('A/1', 'A', 'in_progress')];
    expect(resumableCopy(copies, 'A')?.id).toBe('A/2');
    expect(resumableCopy(copies, 'C')).toBeNull();
    expect(resumableCopy(copies, null)).toBeNull();
    expect(resumableCopy([copy('A/1', 'A', 'incomplete')], 'A')).toBeNull();
  });

  test('Xiaomi, Redmi and POCO phones are recognised by maker or brand', () => {
    expect(isXiaomi({ manufacturer: 'Xiaomi' })).toBe(true);
    expect(isXiaomi({ manufacturer: 'unknown', brand: 'POCO' })).toBe(true);
    expect(isXiaomi({ manufacturer: 'samsung', brand: 'samsung' })).toBe(false);
    expect(isXiaomi(null)).toBe(false);
  });

  test('transfer stages follow the transfer phases', () => {
    expect(transferStages('transfer_choose')).toEqual(['done', 'now', 'todo', 'todo', 'todo']);
    expect(transferStages('transfer_backup')).toEqual(['done', 'now', 'todo', 'todo', 'todo']);
    expect(transferStages('transfer_done')).toEqual(['done', 'done', 'now', 'todo', 'todo']);
  });

  test('a WhatsApp chat backup older than an hour (or missing) needs a fresh one', () => {
    const now = new Date('2026-10-25T14:00:00');
    expect(whatsappStale(null, now)).toBe(true);
    expect(whatsappStale('2026-10-25T12:30:00', now)).toBe(true);
    expect(whatsappStale('2026-10-25T13:30:00', now)).toBe(false);
  });

  test('backup verdict: only a complete copy with all phone data is clean', () => {
    const r = (status: 'complete' | 'incomplete' | 'stopped', sms: 'ok' | 'unavailable' | 'failed' = 'ok') => ({
      status, copy_id: 'x', files_done: 1, files_failed: 0, apps_done: 0, apps_failed: 0, bytes: 1, seconds: 1,
      telephony: { contacts: { status: 'ok' as const, count: 1 }, sms: { status: sms, count: 0 } } });
    expect(backupOutcome(r('complete'))).toBe('ok');
    expect(backupOutcome(r('complete', 'unavailable'))).toBe('warn');
    expect(backupOutcome(r('complete', 'failed'))).toBe('warn');
    expect(backupOutcome(r('incomplete'))).toBe('warn');
    expect(backupOutcome(r('stopped'))).toBe('stopped');
    // pliki, których skan nie odczytał, nie trafiły do kopii — nie zielone
    expect(backupOutcome(r('complete'), 2)).toBe('warn');
    expect(backupOutcome(r('stopped'), 2)).toBe('stopped');
  });

  test('resuming needs space only for what is not copied yet', () => {
    expect(transferNeed(10_000, null)).toBe(10_000);
    expect(transferNeed(10_000, { bytes: 7_000 })).toBe(3_000);
    expect(transferNeed(10_000, { bytes: 12_000 })).toBe(0);
  });
});

describe('uploading a copy to the new phone', () => {
  const FIXTURE = (fixture as { calls: { method: string; events: unknown[][] }[] }).calls;
  const recorded = FIXTURE.find((c) => c.method === 'restore_plan')!.events
    .find(([name]) => name === 'transfer:restore_plan')![1] as { plan: RestorePlanView };
  const restore = (serial: string, status: string, resumable: boolean) => ({ serial, status, updated: null, resumable });
  const copy = (id: string, serial: string, status: CopyView['status'], created: string,
    restores: CopyView['restores'] = []): CopyView => ({
    id, serial, model: 'M', manufacturer: 'm', client: null, created, expires: created, days_left: 7, status, bytes: 1,
    counts: {}, restores });

  test('the offer is the newest finished copy of another phone, complete before incomplete', () => {
    const copies = [
      copy('NEW/3', 'NEW', 'complete', '2026-10-26T12:00:00'),  // kopia podłączonego telefonu
      copy('B/2', 'B', 'in_progress', '2026-10-26T11:00:00'),   // niedokończona
      copy('C/1', 'C', 'incomplete', '2026-10-26T10:00:00'),
      copy('D/1', 'D', 'complete', '2026-10-25T14:00:00'),
      copy('A/1', 'A', 'complete', '2026-10-25T15:00:00'),
    ];
    const now = new Date('2026-10-26T13:00:00');
    expect(restoreOffer(copies, 'NEW', now)?.id).toBe('A/1');
    expect(restoreOffer([copies[2]], 'NEW', now)?.id).toBe('C/1');
    expect(restoreOffer(copies.slice(0, 2), 'NEW', now)).toBeNull();
    expect(restoreOffer(copies, null, now)).toBeNull();
    expect(restoreOffer([], 'NEW', now)).toBeNull();
  });

  test('only a fresh copy (under 24 h) is offered; older ones stay in History', () => {
    const one = [copy('A/1', 'A', 'complete', '2026-10-26T12:00:00')];
    expect(restoreOffer(one, 'NEW', new Date('2026-10-26T13:00:00'))?.id).toBe('A/1');  // 1 h
    expect(restoreOffer(one, 'NEW', new Date('2026-10-27T13:00:00'))).toBeNull();       // 25 h
  });

  test('a copy already fully uploaded to this phone is not offered again', () => {
    const copies = [copy('A/2', 'A', 'complete', '2026-10-26T10:00:00', [restore('NEW', 'complete', false)]),
      copy('A/1', 'A', 'complete', '2026-10-25T20:00:00')];
    const now = new Date('2026-10-26T12:00:00');
    expect(restoreOffer(copies, 'NEW', now)?.id).toBe('A/1');
    expect(restoreOffer(copies, 'OTHER', now)?.id).toBe('A/2');
  });

  test('an interrupted upload is resumable only from the per-phone resumable flag', () => {
    const copies = [
      copy('A/2', 'A', 'complete', '2026-10-26T10:00:00', [restore('NEW', 'stopped', false)]),  // nic do wgrania
      copy('A/1', 'A', 'complete', '2026-10-25T10:00:00', [restore('OTHER', 'stopped', true), restore('NEW', 'phone_full', true)]),
    ];
    expect(restoreResumable(copies, 'NEW')?.id).toBe('A/1');
    expect(restoreResumable(copies, 'OTHER')?.id).toBe('A/1');
    expect(restoreResumable(copies, 'THIRD')).toBeNull();
    expect(restoreResumable(copies, null)).toBeNull();
    expect(restoreResumable([copy('X/1', 'X', 'complete', '2026-10-25T10:00:00', undefined)], 'NEW')).toBeNull();
  });

  test('default choice: every group with files and every other folder, no suspicious APK', () => {
    const groups = { ...recorded.plan.groups };
    delete groups.whatsapp;  // grupy bez plików mogą nie przyjść
    const plan: RestorePlanView = { ...recorded.plan, groups,
      others: [...recorded.plan.others, { name: '', files: 2, bytes: 5, exists: 0, rename: 0 }] };
    expect(defaultUploadChoice(plan)).toEqual({ groups: ['photos', 'downloads', 'other:Music', 'other:'], apks_on: [], verify_hash: false });
  });

  test('a kept choice keeps only groups and suspicious APK files the new plan still has', () => {
    const plan = recorded.plan;
    expect(keptUploadChoice(plan, { groups: ['photos', 'other:Music', 'other:Gone', 'videos'],
      apks_on: ['/sdcard/Download/gra.apk', '/sdcard/Download/szybki-cleaner.apk', '/sdcard/x.apk'], verify_hash: true }))
      .toEqual({ groups: ['photos', 'other:Music', 'videos'], apks_on: ['/sdcard/Download/gra.apk'], verify_hash: true });
  });

  test('upload need mirrors RestorePlan.need: group totals already hold default APKs, suspicious only when ticked', () => {
    const plan = recorded.plan;  // downloads: 504 B; oba APK (902 podejrzany, 702 szkodliwy) są poza tą sumą
    const all = defaultUploadChoice(plan);
    expect(uploadNeed(plan, all)).toEqual({ need: 5000 + 504 + 800 + 400, fits: true, missing: 0 });
    // podejrzany zaznaczony: +902; szkodliwy nigdy, nawet gdyby przyszedł w apks_on
    expect(uploadNeed(plan, { ...all, apks_on: ['/sdcard/Download/gra.apk', '/sdcard/Download/szybki-cleaner.apk'] }).need)
      .toBe(5000 + 504 + 800 + 400 + 902);
    // podejrzany zaznaczony w odznaczonej grupie nie liczy się
    expect(uploadNeed(plan, { ...all, groups: ['photos'], apks_on: ['/sdcard/Download/gra.apk'] }).need).toBe(5000);
    expect(uploadNeed(plan, { groups: [], apks_on: [], verify_hash: false }).need).toBe(0);
  });

  test('upload need: clean APK bytes are not counted twice, a ticked one already on the phone adds nothing', () => {
    const apk = (remote: string, outcome: RestoreApk['outcome'], default_on: boolean, action: RestoreApk['action'] = 'push'): RestoreApk =>
      ({ remote, name: remote, group: 'downloads', bytes: 100, action, outcome, level: 'static', default_on });
    const plan: RestorePlanView = { groups: { downloads: { files: 3, bytes: 100, exists: 2, rename: 0 } }, others: [],
      apks: [apk('a.apk', 'clean', true), apk('b.apk', 'suspicious', false, 'exists'), apk('c.apk', 'unknown', true, 'exists')],
      space: { free: 10_000, total: null }, reserve: 1_000, missing: 0 };
    expect(uploadNeed(plan, { groups: ['downloads'], apks_on: ['b.apk'], verify_hash: false }).need).toBe(100);
  });

  test('fits keeps the reserve free and reports what is missing', () => {
    const plan: RestorePlanView = { groups: { photos: { files: 1, bytes: 9_000, exists: 0, rename: 0 },
      videos: { files: 1, bytes: 3_000, exists: 0, rename: 0 } }, others: [], apks: [],
      space: { free: 10_000, total: 20_000 }, reserve: 1_000, missing: 0 };
    expect(uploadNeed(plan, { groups: ['photos'], apks_on: [], verify_hash: false })).toEqual({ need: 9_000, fits: true, missing: 0 });
    expect(uploadNeed(plan, { groups: ['photos', 'videos'], apks_on: [], verify_hash: false }))
      .toEqual({ need: 12_000, fits: false, missing: 3_000 });
  });

  test('transfer stages for the upload phases', () => {
    expect(transferStages('transfer_restore_plan')).toEqual(['done', 'done', 'now', 'todo', 'todo']);
    expect(transferStages('transfer_restore')).toEqual(['done', 'done', 'done', 'now', 'todo']);
    expect(transferStages('transfer_restored')).toEqual(['done', 'done', 'done', 'done', 'todo']);
  });

  test('upload outcome: green when every file went in; a failed gallery scan has its own outcome', () => {
    const r = (over: Partial<RestoreResultView> = {}): RestoreResultView => ({ status: 'complete', target_serial: 'N', files_done: 5,
      files_exists: 0, files_renamed: 1, files_denied: 0, files_failed: 0, files_unselected: 0, apk_skipped: 1,
      apk_suspicious_skipped: 0, bytes: 1, seconds: 1, hashed: false, media_scan: 'done', files_missing: 0, ...over });
    expect(restoreOutcome(r())).toBe('ok');
    expect(restoreOutcome(r({ files_denied: 2 }))).toBe('warn');
    expect(restoreOutcome(r({ files_failed: 1 }))).toBe('warn');
    expect(restoreOutcome(r({ files_missing: 1 }))).toBe('warn');
    expect(restoreOutcome(r({ media_scan: 'failed' }))).toBe('scan');
    expect(restoreOutcome(r({ media_scan: 'restart' }))).toBe('ok');  // Android < 10: osobny baner o restarcie
    expect(restoreOutcome(r({ media_scan: 'failed', files_denied: 1 }))).toBe('warn');
    expect(restoreOutcome(r({ status: 'incomplete' }))).toBe('warn');
    expect(restoreOutcome(r({ status: 'stopped', media_scan: 'skipped' }))).toBe('stopped');
  });
});
