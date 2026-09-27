import { describe, expect, test, vi } from 'vitest';
import { isApiError } from './bridge';
import { createFakeBridge, scenarioNames } from './fakeBridge';
import type { EventName } from './types';

describe('fake bridge', () => {
  test('knows the recorded scenarios', () => {
    expect(scenarioNames().sort()).toEqual(
      ['adware', 'clean', 'disconnect', 'empty', 'many', 'unauthorized'].sort());
  });

  test('replays results and events of the adware scenario', async () => {
    const bridge = createFakeBridge('adware', { delay: 0 });
    const seen: EventName[] = [];
    for (const name of ['scan:device', 'scan:done', 'apk:done', 'exec:done'] as EventName[]) {
      bridge.on(name, () => seen.push(name));
    }
    const devices = await bridge.api.list_devices();
    expect(isApiError(devices)).toBe(false);
    if (!isApiError(devices)) expect(devices.devices[0].state).toBe('device');
    expect(await bridge.api.start_scan('R58T00TEST', 'Anna K.')).toEqual({ job_id: 'job-1' });
    expect(seen).toEqual([]); // zdarzenia przychodzą dopiero po wyniku
    await vi.waitFor(() => expect(seen).toContain('apk:done'));
    expect(seen).toEqual(['scan:device', 'scan:done', 'apk:done']);
    const rerender = await bridge.api.rerender();
    if (!isApiError(rerender)) expect(rerender.scan?.apps.length).toBeGreaterThan(0);
    await bridge.api.execute({ 'com.wlive.forecast': 'disable' }, []);
    await vi.waitFor(() => expect(seen.at(-1)).toBe('exec:done'));
    expect(bridge.calls.map((c) => c.method)).toEqual(
      ['list_devices', 'start_scan', 'rerender', 'execute']);
  });

  test('repeats the last recording and has defaults', async () => {
    const bridge = createFakeBridge('adware', { delay: 0 });
    const first = await bridge.api.history(null);
    const second = await bridge.api.history(null);
    const third = await bridge.api.history(null);
    expect(first).not.toEqual(second);
    expect(third).toEqual(second);
    expect(await bridge.api.save_settings({ lang: 'en' })).toMatchObject({ lang: 'en' });
    expect(await bridge.api.get_settings()).toMatchObject({ lang: 'en', mode: 'simple' });
    const shell = await bridge.api.adb_shell('id');
    expect(isApiError(shell)).toBe(false);
  });

  test('emit injects events for tests', () => {
    const bridge = createFakeBridge('empty', { delay: 0 });
    let got = '';
    bridge.on('exec:question', (q) => (got = q.package));
    bridge.emit('exec:question', { job_id: 'job-9', kind: 'admin_timeout', package: 'p', name: 'P' });
    expect(got).toBe('p');
  });
});
