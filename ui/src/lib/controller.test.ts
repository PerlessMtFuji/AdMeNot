import { describe, expect, test, vi } from 'vitest';
import { setupCtl } from '../test-utils';
import { Controller } from './controller';
import { createFakeBridge } from './fakeBridge';
import { i18n } from './i18n/index.svelte';
import { AppState } from './state.svelte';

function setup(scenario: string) {
  const bridge = createFakeBridge(scenario, { delay: 0 });
  const ctl = new Controller(new AppState(), bridge);
  return { bridge, ctl, s: ctl.state };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

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

  test('back to repair after an order keeps the scan and remembers what was done', async () => {
    const { ctl, s, bridge } = setup('adware');
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    const scan = s.scan;
    await ctl.openPlan();
    await ctl.execute();
    await vi.waitFor(() => expect(s.phase).toBe('done'));
    const levels = Object.fromEntries(s.execPlan!.apps.map((a) => [a.package, a.level]));
    expect(levels['com.clean.pro.boost']).toBe('remove');
    ctl.backToRepair();
    expect(s.phase).toBe('results');
    expect(s.scan).toBe(scan); // bez ponownego skanu
    expect([s.result, s.order, s.plan]).toEqual([null, null, null]);
    expect(s.selection).toEqual({}); // propozycje silnika już wykonane — nie zaznaczamy ich znowu
    expect(s.acted).toEqual(levels);
    expect(bridge.calls.map((c) => c.method)).toContain('close_order'); // zrzuty idą do następnego zlecenia
    const app = (pkg: string) => s.scan!.apps.find((a) => a.package === pkg)!;
    ctl.toggle(app('com.clean.pro.boost'));
    expect(s.selection['com.clean.pro.boost']).toBeUndefined(); // usuniętej nie ma już czego zmieniać
    ctl.setLevel('com.wlive.forecast', 'remove');
    expect(s.selection['com.wlive.forecast']).toBe('remove'); // wyłączoną można jeszcze usunąć
    ctl.newScan();
    expect(s.acted).toEqual({});
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

  test('selecting an app without an engine proposal uses the action from settings', async () => {
    const { ctl, s } = setup('adware');
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    const app = (pkg: string) => s.scan!.apps.find((a) => a.package === pkg)!;
    ctl.toggle(app('com.wlive.forecast'));
    expect(s.selection['com.wlive.forecast']).toBe('silence');
    await ctl.saveSettings({ select_level: 'remove' });
    ctl.toggle(app('com.wlive.forecast'));
    ctl.toggle(app('com.wlive.forecast'));
    expect(s.selection['com.wlive.forecast']).toBe('remove');
    ctl.toggle(app('com.sec.android.app.launcher'));
    expect(s.selection['com.sec.android.app.launcher']).toBe('disable'); // producenta nie usuwamy domyślnie
    ctl.toggle(app('com.clean.pro.boost'));
    ctl.toggle(app('com.clean.pro.boost'));
    expect(s.selection['com.clean.pro.boost']).toBe('remove'); // propozycja silnika ma pierwszeństwo
  });

  test('on Android 12 and older the silence default from settings becomes disable', async () => {
    const { ctl, s } = setup('adware');
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    s.device = { ...s.device!, sdk: 31 };
    ctl.toggle(s.scan!.apps.find((a) => a.package === 'com.wlive.forecast')!);
    expect(s.selection['com.wlive.forecast']).toBe('disable');
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

  test('job:error during a scan always returns to connect so the user can rescan', async () => {
    for (const key of ['timeout', 'adb_error', 'adb_missing', 'internal']) {
      const { ctl, s, bridge } = setup('empty');
      await ctl.init();
      s.phase = 'scanning';
      s.device = { serial: 'S' } as never;
      bridge.emit('job:error', { job_id: 'job-1', kind: 'scan', key, message: 'x' });
      expect(s.phase).toBe('connect');
      expect(s.device).toBeNull();
      expect(s.error?.key).toBe(key);
    }
  });

  test('job:error during the APK analysis stops its progress', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    s.phase = 'results';
    s.apk = { done: 3, total: 9, running: true, changed: [] };
    bridge.emit('job:error', { job_id: 'job-2', kind: 'apk', key: 'timeout', message: '' });
    expect(s.apk.running).toBe(false);
    expect(s.phase).toBe('results');
    expect(s.error?.key).toBe('timeout');
  });

  test('job:error after exec:order leaves the order to finish or undo', async () => {
    for (const kind of ['exec', 'resume']) {
      const { ctl, s, bridge } = setup('empty');
      await ctl.init();
      bridge.emit('exec:order', { order: 'ZS/2026/0926/03', plan: null });
      s.job = { id: 'job-5', kind };
      s.verifying = true;
      bridge.emit('job:error', { job_id: 'job-5', kind, key: 'internal', message: 'boom' });
      bridge.emit('job:end', { job_id: 'job-5', kind });
      expect(s.phase).toBe('connect');
      expect(s.interrupted).toEqual(['ZS/2026/0926/03']);
      expect(s.verifying).toBe(false);
      expect(s.job).toBeNull();
      expect(s.error?.key).toBe('internal');
    }
  });

  test('a failed resume keeps the order offered for resuming', async () => {
    const bridge = createFakeBridge('empty', { delay: 0 });
    const api = new Proxy(bridge.api, {
      get: (target, method: string) => (method === 'resume'
        ? async () => ({ job_id: 'job-6' })
        : target[method as keyof typeof target]),
    });
    const ctl = new Controller(new AppState(), { ...bridge, api });
    const s = ctl.state;
    await ctl.init();
    s.interrupted = ['ZS/2026/0926/04'];
    await ctl.resume('ZS/2026/0926/04');
    expect(s.job).toEqual({ id: 'job-6', kind: 'resume' });
    bridge.emit('job:error', { job_id: 'job-6', kind: 'resume', key: 'wrong_device', message: '' });
    expect(s.interrupted).toEqual(['ZS/2026/0926/04']);
  });

  test('job:error during an undo refreshes the history', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    s.phase = 'done';
    const before = bridge.calls.filter((c) => c.method === 'history').length;
    bridge.emit('job:error', { job_id: 'job-8', kind: 'undo', key: 'internal', message: '' });
    expect(s.phase).toBe('done');
    await vi.waitFor(() =>
      expect(bridge.calls.filter((c) => c.method === 'history').length).toBe(before + 1));
  });

  test('a job that ended before its id arrived does not stay busy', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    bridge.emit('job:end', { job_id: 'job-7', kind: 'exec' });
    ctl.setJob('job-7', 'exec');
    expect(s.job).toBeNull();
  });
});

describe('screen mirror and screenshots (Plan 6b)', () => {
  test('mirror: status on init, start follows events, stop', async () => {
    const { ctl, s, bridge } = await setupCtl('empty');
    expect(s.mirror.available).toBe(true);
    await ctl.mirrorStart('R58T00TEST', 'Galaxy A14');
    expect(bridge.calls.at(-1)).toEqual({ method: 'mirror_start', args: ['R58T00TEST', 'Galaxy A14'] });
    await flush();
    expect(s.mirror.state).toBe('running');
    expect(ctl.mirrorActive('R58T00TEST')).toBe(true);
    expect(ctl.mirrorActive('OTHER')).toBe(false);
    bridge.emit('mirror:warning', { serial: 'R58T00TEST', code: 'control_blocked' });
    expect(s.mirror.blocked).toBe(true);
    bridge.emit('mirror:warning', { serial: 'R58T00TEST', code: 'stay_awake_blocked' });
    expect(s.mirror.awakeBlocked).toBe(true);
    await ctl.mirrorStop();
    await flush();
    expect(s.mirror.state).toBe('stopped');
    expect(s.mirror.blocked).toBe(false);
    expect(s.mirror.awakeBlocked).toBe(false);
  });

  test('mirror failure becomes an error card', async () => {
    const { s, bridge } = await setupCtl('empty');
    bridge.emit('mirror:state', { serial: 'S', state: 'failed', reason: 'ERROR: Server connection failed' });
    expect(s.error).toEqual({ key: 'mirror_failed', message: 'ERROR: Server connection failed' });
    expect(s.mirror.state).toBe('failed');
  });

  test('screenshot updates the counter and the order strip', async () => {
    const { ctl, s } = await setupCtl('empty');
    await ctl.takeScreenshot('R58T00TEST');
    expect(s.shotCount).toBe(1);
    expect(s.lastShotSerial).toBe('R58T00TEST');
    expect(s.lastShot?.caption).toContain('Na pierwszym planie');
    await ctl.loadShots('ZS/2026/0926/01');
    const id = s.shots['ZS/2026/0926/01'].items[0].id;
    await ctl.setShotInReport('ZS/2026/0926/01', id, false);
    expect(s.shots['ZS/2026/0926/01'].items[0].in_report).toBe(false);
  });

  test('new scan leaves the order: the phone stops collecting shots for it, the counter resets', async () => {
    const { ctl, s, bridge } = await setupCtl('adware');
    await ctl.startScan();
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    await ctl.takeScreenshot('R58T00TEST');
    expect(s.lastShot).not.toBeNull();
    ctl.newScan();
    await flush();
    expect(bridge.calls.filter((c) => c.method === 'close_order').map((c) => c.args)).toEqual([['R58T00TEST']]);
    expect(s.lastShot).toBeNull();
    expect(s.shotCount).toBe(0);
  });

  test('auto mirror starts once for the ready phone when enabled', async () => {
    const { ctl, s, bridge } = await setupCtl('empty');
    await ctl.saveSettings({ mirror_auto: true });
    const ready = { devices: [{ serial: 'R58T00TEST', state: 'device', model: 'SM_A145R' }], error: null };
    bridge.emit('devices', ready);
    bridge.emit('devices', { devices: [], error: null });
    bridge.emit('devices', ready);
    await flush();
    expect(bridge.calls.filter((c) => c.method === 'mirror_start')).toHaveLength(1);
    expect(s.mirror.serial).toBe('R58T00TEST');
  });

  test('auto mirror starts once for a phone already connected at launch', async () => {
    // mirror_status() musi się rozstrzygnąć przed pierwszym list_devices()/onDevices(), inaczej brama
    // (s.mirror.available) jest jeszcze zamknięta, kiedy telefon jest już gotowy.
    const bridge = createFakeBridge('adware', { delay: 0 });
    await bridge.api.save_settings({ mirror_auto: true });
    const ctl = new Controller(new AppState(), bridge);
    await ctl.init();
    await flush();
    expect(bridge.calls.filter((c) => c.method === 'mirror_start')).toHaveLength(1);
    expect(ctl.state.mirror.serial).toBe('R58T00TEST');
  });

  test('a stale mirror:state event for a different phone does not override the phone that is now starting', async () => {
    const { ctl, s, bridge } = await setupCtl('empty');
    const starting = ctl.mirrorStart('B', 'Phone B'); // optymistycznie: serial=B, state=starting — od razu, przed odpowiedzią
    // Zdarzenie o poprzednim telefonie (A) dociera z opóźnieniem, już po starcie B — ma być zignorowane.
    bridge.emit('mirror:state', { serial: 'A', state: 'stopped', reason: 'disconnected' });
    expect(s.mirror.serial).toBe('B');
    expect(s.mirror.state).toBe('starting');
    expect(s.error).toBeNull();
    await starting;
    await flush();
  });

  test('mirror stopped by a disconnect does not raise an error card', async () => {
    const { s, bridge } = await setupCtl('empty');
    bridge.emit('mirror:state', { serial: 'S', state: 'stopped', reason: 'disconnected' });
    expect(s.error).toBeNull();
    expect(s.mirror.state).toBe('stopped');
  });

  test('mirrorStart seeds the state from the call result when no event follows (a repeated start)', async () => {
    const { ctl, s } = await setupCtl('empty');
    await ctl.mirrorStart('R58T00TEST', 'Galaxy A14');
    await flush();
    expect(s.mirror.state).toBe('running');
    // Powtórzony start: most zwraca aktualny stan bez nowych zdarzeń — nie może zostać "starting" na zawsze.
    await ctl.mirrorStart('R58T00TEST', 'Galaxy A14');
    expect(s.mirror.state).toBe('running');
  });
});
