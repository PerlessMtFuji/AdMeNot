import { describe, expect, test } from 'vitest';
import {
  changedVerdicts,
  evidenceGroups,
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
} from './logic';
import type { AppView, StepEvent } from './types';

function app(pkg: string, verdict: AppView['verdict'], extra: Partial<AppView> = {}): AppView {
  const level = verdict === 'malicious' ? 'remove' : verdict === 'suspicious' ? 'disable' : null;
  return {
    package: pkg, name: pkg.split('.').at(-1)!, score: 0, verdict, verdict_label: verdict,
    trusted: false, incomplete: false, is_system: false, from_play: true, installer: null,
    is_admin: false, default_level: level, problems: [], findings: [], apk_error: null,
    ad_sdks: null, symptoms: [], source: { label: '', days: null }, ...extra,
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
    expect(stageStates('connect', null)).toEqual(['now', 'todo', 'todo', 'todo', 'off']);
    expect(stageStates('scanning', 'collectors')).toEqual(['done', 'now', 'todo', 'todo', 'off']);
    expect(stageStates('scanning', 'score')).toEqual(['done', 'done', 'now', 'todo', 'off']);
    expect(stageStates('results', null)).toEqual(['done', 'done', 'done', 'now', 'off']);
    expect(stageStates('done', null)).toEqual(['done', 'done', 'done', 'done', 'off']);
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
        { rule_id: 'DM-ADMIN-01', class: 'position', weight: 20, text: '', text_expert: '', evidence: {}, category: 'removal', label: '' },
        { rule_id: 'DM-ADMIN-02', class: 'position', weight: 5, text: '', text_expert: '', evidence: {}, category: 'removal', label: '' },
        { rule_id: 'DM-BOOT-01', class: 'context', weight: 3, text: '', text_expert: '', evidence: {}, category: 'background', label: '' },
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
