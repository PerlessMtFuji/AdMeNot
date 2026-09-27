import { describe, expect, test, vi } from 'vitest';
import { Controller } from './controller';
import { createFakeBridge } from './fakeBridge';
import { i18n } from './i18n/index.svelte';
import { AppState } from './state.svelte';

function setup(scenario: string) {
  const bridge = createFakeBridge(scenario, { delay: 0 });
  const ctl = new Controller(new AppState(), bridge);
  return { bridge, ctl, s: ctl.state };
}

describe('controller with the adware scenario', () => {
  test('init picks the only ready phone, scan fills results and defaults', async () => {
    const { ctl, s } = setup('adware');
    await ctl.init();
    expect(s.serial).toBe('R58T00TEST');
    s.client = 'Anna K.';
    await ctl.startScan();
    expect(s.phase).toBe('scanning');
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    await vi.waitFor(() => expect(s.job).toBeNull()); // job:end przychodzi po apk:done
    expect(s.apk.running).toBe(false);
    expect(s.apk.total).toBeGreaterThan(0);
    expect(s.device?.serial).toBe('R58T00TEST');
    expect(s.selection['com.clean.pro.boost']).toBe('remove');
    expect(s.job).toBeNull();
  });

  test('plan, execute, history, undo', async () => {
    const { ctl, s } = setup('adware');
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    await ctl.openPlan();
    expect(s.plan?.runnable).toBeGreaterThan(0);
    await ctl.execute();
    await vi.waitFor(() => expect(s.phase).toBe('done'));
    expect(s.plan).toBeNull();
    expect(s.result?.apps.every((a) => a.outcome === 'ok')).toBe(true);
    expect(s.steps.length).toBeGreaterThan(0);
    await ctl.openHistory();
    expect(s.screen).toBe('history');
    expect(s.history?.orders[0].number).toBe(s.order);
    await ctl.undo(s.order!);
    await vi.waitFor(() => expect(s.undoResult?.status).toBe('undone'));
    await vi.waitFor(() => expect(s.history?.orders[0].status).toBe('undone'));
  });

  test('user choices survive the APK re-score and toggles work', async () => {
    const { ctl, s } = setup('adware');
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    ctl.setLevel('com.clean.pro.boost', 'silence');
    const app = s.scan!.apps.find((a) => a.package === 'com.clean.pro.boost')!;
    ctl.toggle(app);
    expect(s.selection['com.clean.pro.boost']).toBeUndefined();
    ctl.toggle(app);
    expect(s.selection['com.clean.pro.boost']).toBe('remove');
    expect(s.touched).toContain('com.clean.pro.boost');
  });

  test('language change re-renders the scan', async () => {
    const { ctl, s, bridge } = setup('adware');
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    await ctl.setLang('en');
    expect(i18n.lang).toBe('en');
    expect(bridge.calls.map((c) => c.method)).toContain('rerender');
    await ctl.setLang('pl');
  });
});

describe('controller edge cases', () => {
  test('disconnect during an order goes back to connect with the order to finish', async () => {
    const { ctl, s } = setup('disconnect');
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    s.selection = { 'com.wlive.forecast': 'disable' };
    await ctl.execute();
    await vi.waitFor(() => expect(s.disconnectedOrder).not.toBeNull());
    expect(s.phase).toBe('connect');
    expect(s.interrupted).toEqual([s.disconnectedOrder]);
    await ctl.resume(s.disconnectedOrder!);
    await vi.waitFor(() => expect(s.phase).toBe('done'));
    expect(s.interrupted).toEqual([]);
  });

  test('unauthorized and many phones do not auto-select', async () => {
    for (const name of ['unauthorized', 'many']) {
      const { ctl, s } = setup(name);
      await ctl.init();
      expect(s.serial).toBeNull();
      expect(s.devices.length).toBeGreaterThan(0);
    }
  });

  test('events: question, admin wait, job errors, console cap, close request', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    bridge.emit('exec:admin_wait', { package: 'p', name: 'P', timeout: 180 });
    expect(s.admin?.name).toBe('P');
    bridge.emit('exec:question', { job_id: 'job-3', kind: 'admin_timeout', package: 'p', name: 'P' });
    await ctl.answer('skip');
    expect(s.question).toBeNull();
    expect(bridge.calls.at(-1)).toEqual({ method: 'answer', args: ['job-3', 'skip'] });
    s.phase = 'scanning';
    bridge.emit('job:error', { job_id: 'job-1', kind: 'scan', key: 'disconnected', message: '' });
    expect(s.phase).toBe('connect');
    expect(s.error?.key).toBe('disconnected');
    for (let i = 0; i < 510; i++) {
      bridge.emit('adb:command', { time: '', serial: 'S', command: `c${i}`, status: 'ok',
        duration: 0, output: '', tag: null });
    }
    expect(s.console).toHaveLength(500);
    expect(s.console.at(-1)?.command).toBe('c509');
    bridge.emit('app:close_requested', { kind: 'exec' });
    expect(s.closeRequested).toBe(true);
  });

  test('a job that ended before its id arrived does not stay busy', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    bridge.emit('job:end', { job_id: 'job-7', kind: 'exec' });
    ctl.setJob('job-7', 'exec');
    expect(s.job).toBeNull();
  });
});
