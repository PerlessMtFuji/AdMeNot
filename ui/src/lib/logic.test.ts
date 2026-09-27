import { describe, expect, test } from 'vitest';
import {
  changedVerdicts,
  defaultSelection,
  flaggedApps,
  formatUptime,
  groupSteps,
  levelTag,
  mergeSelection,
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
    ad_sdks: null, ...extra,
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
        { rule_id: 'DM-ADMIN-01', class: 'position', weight: 20, text: '', text_expert: '', evidence: {} },
        { rule_id: 'DM-ADMIN-02', class: 'position', weight: 5, text: '', text_expert: '', evidence: {} },
        { rule_id: 'DM-BOOT-01', class: 'context', weight: 3, text: '', text_expert: '', evidence: {} },
      ],
    });
    expect(signalChips(a)).toEqual([{ label: 'admin', bad: true }, { label: 'boot', bad: false }]);
    expect(sourceKey(app('p', 'safe', { is_system: true }))).toBe('system');
    expect(sourceKey(app('p', 'safe', { from_play: false }))).toBe('sideload');
  });
});
