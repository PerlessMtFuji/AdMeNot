import { describe, expect, test, vi } from 'vitest';
import { setupCtl } from '../test-utils';
import { Controller } from './controller';
import { CHECKS_SAMPLE, createFakeBridge } from './fakeBridge';
import { i18n } from './i18n/index.svelte';
import { actedAfter, actedLevels, needsWelcome, withoutUndone } from './logic';
import { AppState } from './state.svelte';
import type { Settings } from './types';

function setup(scenario: string) {
  const bridge = createFakeBridge(scenario, { delay: 0 });
  const ctl = new Controller(new AppState(), bridge);
  return { bridge, ctl, s: ctl.state };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('controller with the adware scenario', () => {
  test('deleting an order calls the bridge and refreshes the history', async () => {
    const { bridge, ctl } = setup('adware');
    await ctl.init();
    const before = bridge.calls.filter((c) => c.method === 'history').length;
    await ctl.deleteOrder('ZS/2026/0926/01');
    expect(bridge.calls.some((c) => c.method === 'delete_order' && c.args[0] === 'ZS/2026/0926/01')).toBe(true);
    expect(bridge.calls.filter((c) => c.method === 'history').length).toBe(before + 1);
  });

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
    expect(s.selection['com.clean.pro.boost']).toBe('disable');
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
    s.client = 'Anna Kowalska';
    s.unlocked = ['com.android.systemui'];
    ctl.newScan();
    expect(s.acted).toEqual({});
    expect(s.client).toBe(''); // PRIV-04: następny telefon to inny klient
    expect(s.unlocked).toEqual([]);
  });

  test('undo one app from the results after back to repair', async () => {
    const { ctl, s, bridge } = setup('adware');
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    await ctl.openPlan();
    await ctl.execute();
    await vi.waitFor(() => expect(s.phase).toBe('done'));
    const order = s.order!;
    ctl.backToRepair();
    await vi.waitFor(() => expect(s.job).toBeNull());
    await ctl.undoApp('com.clean.pro.boost');
    expect(s.undoTarget).toBe('com.clean.pro.boost');
    await vi.waitFor(() => expect(s.job).toBeNull());
    expect(bridge.calls.filter((c) => c.method === 'undo').at(-1)!.args).toEqual([order, null, 'com.clean.pro.boost']);
    expect(s.phase).toBe('results'); // zostajemy na liście, bez przejścia do Historii
    expect(s.acted['com.clean.pro.boost']).toBeUndefined();
    expect(s.acted['com.wlive.forecast']).toBeDefined(); // pozostałe aplikacje zlecenia bez zmian
    expect(s.undoTarget).toBeNull();
    ctl.setLevel('com.clean.pro.boost', 'remove');
    expect(s.selection['com.clean.pro.boost']).toBe('remove'); // przywróconą można znowu wybrać
  });

  test('a failed undo keeps the app marked as done and shows why', async () => {
    const { ctl, s, bridge } = setup('adware');
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    await ctl.openPlan();
    await ctl.execute();
    await vi.waitFor(() => expect(s.phase).toBe('done'));
    ctl.backToRepair();
    s.undoTarget = 'com.clean.pro.boost';
    s.undoing = { order: s.actedLog['com.clean.pro.boost'][0].order, pkg: 'com.clean.pro.boost' };
    bridge.emit('undo:done', { order: 'X', status: 'partially_undone', status_label: '', errors: ['Brak kopii'], admin_not_restored: false,
      sites_total: 0, sites_restored: 0, restored_sites: [], firefox_debugging: false, interrupted: [] });
    expect(s.acted['com.clean.pro.boost']).toBe('remove');
    expect(s.undoTarget).toBe('com.clean.pro.boost');
    expect(s.undoResult?.errors).toEqual(['Brak kopii']);
  });

  test('an undone interrupted order leaves the banner; one still pending stays; hiding is local', async () => {
    const { ctl, bridge } = setup('adware');
    await ctl.init();
    const s = ctl.state;
    s.interrupted = ['ZS/1', 'ZS/2', 'ZS/3'];
    const done = { status: 'partially_undone', status_label: '', errors: [], admin_not_restored: false,
      sites_total: 0, sites_restored: 0, restored_sites: [], firefox_debugging: false };
    bridge.emit('undo:done', { ...done, order: 'ZS/1', interrupted: ['ZS/2', 'ZS/3'] });
    expect(s.interrupted).toEqual(['ZS/2', 'ZS/3']);
    bridge.emit('undo:done', { ...done, order: 'ZS/2', interrupted: ['ZS/2', 'ZS/3'] }); // cofnięto tylko część
    expect(s.interrupted).toEqual(['ZS/2', 'ZS/3']);
    ctl.hideInterrupted('ZS/3');
    expect(s.interrupted).toEqual(['ZS/2']);
    expect(bridge.calls.some((c) => c.method === 'delete_order')).toBe(false);
  });

  test('two orders: undo goes to the newest one and falls back to the earlier level', () => {
    const plan = (level: 'disable' | 'remove') => ({ runnable: 1, code: 'K7F3', apps: [{ package: 'p', name: 'P', level, level_label: '',
      blocked: false, reason: null, reason_text: null, steps: [], warnings: [] }] });
    const result = (order: string) => ({ order, status: 'done', status_label: '', stopped: false,
      apps: [{ package: 'p', name: 'P', outcome: 'ok' as const, errors: [], kinds: [] }] });
    let log = actedAfter({}, plan('disable'), result('A'));
    log = actedAfter(log, plan('remove'), result('B'));
    expect(actedLevels(log)).toEqual({ p: 'remove' });
    expect(log.p.at(-1)!.order).toBe('B');
    expect(actedLevels(withoutUndone(log, 'B', 'q'))).toEqual({ p: 'remove' }); // inna aplikacja
    log = withoutUndone(log, 'B', 'p');
    expect(actedLevels(log)).toEqual({ p: 'disable' });
    expect(actedLevels(withoutUndone(log, 'A', null))).toEqual({}); // całe zlecenie z Historii
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
    expect(s.selection['com.clean.pro.boost']).toBe('disable');
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
    expect(s.selection['com.clean.pro.boost']).toBe('disable'); // propozycja silnika ma pierwszeństwo
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

  test('APK events of an abandoned job do not touch the current scan (BUG-10)', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    s.job = { id: 'job-2', kind: 'scan' };
    s.apk = { done: 0, total: 0, running: true, changed: [], eta: null };
    bridge.emit('apk:progress', { done: 5, total: 9, package: 'old', eta_s: null, job_id: 'job-1' });
    bridge.emit('apk:stopped', { job_id: 'job-1' });
    expect(s.apk).toEqual({ done: 0, total: 0, running: true, changed: [], eta: null });
    bridge.emit('apk:progress', { done: 1, total: 3, package: 'new', eta_s: null, job_id: 'job-2' });
    expect(s.apk.done).toBe(1);
  });

  test('events: question, admin wait, job errors, console cap, close request', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    bridge.emit('exec:user_wait', { package: 'p', name: 'P', kind: 'admin', timeout: 180, action_id: 1 });
    expect(s.userWait?.name).toBe('P');
    bridge.emit('exec:question', { job_id: 'job-3', kind: 'user_timeout', package: 'p', name: 'P' });
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
    s.apk = { done: 3, total: 9, running: true, changed: [], eta: null };
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

  test('undo:done clears the site queue', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    const sites = [{ action_id: 4, package: 'com.android.chrome', browser: 'Chrome', site: 'a.example' }];
    bridge.emit('undo:sites', { order: 'ZS/1', sites });
    expect(s.undoSites).toEqual(sites);
    bridge.emit('undo:done', { order: 'ZS/1', status: 'undone', status_label: '', errors: [], admin_not_restored: false,
      sites_total: 1, sites_restored: 1, restored_sites: [], firefox_debugging: false, interrupted: [] });
    expect(s.undoSites).toBeNull();
    bridge.emit('undo:sites', { order: 'ZS/1', sites });
    await ctl.undo('ZS/1'); // nowe cofanie zaczyna bez starej kolejki
    expect(s.undoSites).toBeNull();
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

describe('repair screen view state', () => {
  test('groups, diagnostics and details: set, reset by scan, mode and new scan; plan closes diagnostics', async () => {
    const { ctl, s } = await setupCtl('adware');
    await ctl.startScan();
    await vi.waitFor(() => expect(s.job).toBeNull());
    ctl.setGroupOpen('review', true);
    expect(s.openGroups).toEqual({ review: true });
    await ctl.setMode('expert');
    expect(s.openGroups).toEqual({});
    ctl.setGroupOpen('safe', true);
    ctl.openDiagnostics();
    expect(s.diagnostics).toBe(true);
    await ctl.openPlan();
    expect(s.diagnostics).toBe(false);
    expect(s.plan).not.toBeNull();
    ctl.closePlan();
    ctl.openDiagnostics();
    ctl.closeDiagnostics();
    expect(s.diagnostics).toBe(false);
    ctl.setDetailsOpen(true);
    expect(s.detailsOpen).toBe(true);
    ctl.openDiagnostics();
    ctl.newScan();
    expect(s.openGroups).toEqual({});
    expect(s.diagnostics).toBe(false);
    expect(s.detailsOpen).toBe(true); // szczegóły techniczne: do zamknięcia programu
  });
});

describe('error reports', () => {
  test('init loads startup reports', async () => {
    const { ctl, s, bridge } = setup('empty');
    bridge.setCrashes([{ id: '20261009-140312-abcd', kind: 'exit', created: '2026-10-09T14:03:12', type: 'fatal', sent_id: null }],
      ['20261009-140312-abcd']);
    await ctl.init();
    expect(s.crashStartup).toEqual(['20261009-140312-abcd']);
  });

  test('open previews, toggling ADB and sending shows the number', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    ctl.openCrash('20261009-140312-abcd');
    await vi.waitFor(() => expect(s.crashPreview).not.toBeNull());
    expect(s.crashHasAdb).toBe(true);
    s.crashAdb = true;
    s.crashComment = 'skan';
    await ctl.previewCrash();
    expect(bridge.calls.at(-1)).toEqual({ method: 'crash_preview', args: ['20261009-140312-abcd', true, 'skan'] });
    const first = ctl.sendCrash();
    const second = ctl.sendCrash(); // podwójny klik
    await Promise.all([first, second]);
    expect(bridge.calls.filter((c) => c.method === 'send_crash')).toHaveLength(1);
    expect(s.crashSent).toBe('R-7K3Q9M');
    expect(s.error).toBeNull();
  });

  test('offline error stays in the dialog', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    bridge.failNextCrashSend('crash_offline');
    ctl.openCrash('20261009-140312-abcd');
    await ctl.sendCrash();
    expect(s.crashError?.key).toBe('crash_offline');
    expect(s.crashSent).toBeNull();
    expect(s.error).toBeNull();
  });

  test('close and discard forget the startup banner', async () => {
    const { ctl, s, bridge } = setup('empty');
    bridge.setCrashes([], ['a', 'b']);
    await ctl.init();
    ctl.openCrash('a');
    ctl.closeCrash();
    expect(s.crashDialog).toBeNull();
    expect(s.crashStartup).toEqual(['b']);
    await ctl.discardCrash('b');
    expect(bridge.calls.at(-1)).toEqual({ method: 'discard_crash', args: ['b'] });
    expect(s.crashStartup).toEqual([]);
  });

  test('UI error is captured once', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    await ctl.captureUiError('TypeError: x', 'at f');
    await ctl.captureUiError('TypeError: y', 'at g');
    expect(bridge.calls.filter((c) => c.method === 'capture_ui_error')).toHaveLength(1);
    expect(s.fatalCrash).toBe('20261009-140312-ui00');
  });
});

describe('first run and telemetry consent', () => {
  test('akceptacja ostrzeżenia zapisuje zgody i zamyka ekran powitalny', async () => {
    const bridge = createFakeBridge('adware', { delay: 0, welcome: true });
    const ctl = new Controller(new AppState(), bridge);
    await ctl.init();
    expect(ctl.state.settingsLoaded).toBe(true);
    expect(needsWelcome(ctl.state.settings)).toBe(true);
    await ctl.acceptWelcome(true, false);
    expect(needsWelcome(ctl.state.settings)).toBe(false);
    expect(ctl.state.settings.telemetry).toBe(true);
    expect(bridge.calls.at(-1)).toEqual({ method: 'accept_welcome', args: [true, false] });
  });

  test('wyłączenie statystyk wyłącza też pakiety', async () => {
    const { ctl } = setup('adware');
    await ctl.init();
    await ctl.setTelemetry(true, true);
    await ctl.setTelemetry(false, true);
    expect(ctl.state.settings.telemetry_packages).toBe(false);
    expect(ctl.state.settings.telemetry_delete_pending).toBe(true);
  });

  test('zakończone usunięcie danych z serwera chowa baner', async () => {
    const { bridge, ctl } = setup('adware');
    await ctl.init();
    await ctl.setTelemetry(true, false);
    await ctl.setTelemetry(false, false);
    expect(ctl.state.settings.telemetry_delete_pending).toBe(true);
    bridge.emit('telemetry:deleted', {});
    expect(ctl.state.settings.telemetry_delete_pending).toBe(false);
  });
});

describe('plan dla klienta', () => {
  async function confirming() {
    const env = await setupCtl('adware');
    env.s.plan = { apps: [], runnable: 1, code: 'K7F3' };
    return env;
  }

  test('sharePlan sets state before the call and accepts an event that arrives early', async () => {
    const { ctl, s, bridge } = await confirming();
    const pending = ctl.sharePlan();
    const id = s.share!.id;
    expect(s.share).toMatchObject({ status: 'sending', url: null });
    bridge.emit('share:ready', { share_id: id, code: 'K7F3', url: 'https://x/plan#l.a', mode: 'local', expires: null });
    await pending;
    expect(s.share).toMatchObject({ status: 'ready', mode: 'local', code: 'K7F3' });
    const call = bridge.calls.find((c) => c.method === 'share_plan')!;
    expect(call.args[2]).toBe(id);
  });

  test('ignores events of an older share and marks the local → server upgrade', async () => {
    const { ctl, s, bridge } = await confirming();
    await ctl.sharePlan();
    const id = s.share!.id;
    bridge.emit('share:ready', { share_id: 'other', code: 'XXXX', url: 'u', mode: 'server', expires: null });
    bridge.emit('share:ready', { share_id: id, code: 'K7F3', url: 'l', mode: 'local', expires: null });
    bridge.emit('share:ready', { share_id: id, code: 'K7F3', url: 's', mode: 'server', expires: '2026-10-11T13:32:00Z' });
    expect(s.share).toMatchObject({ url: 's', mode: 'server', upgraded: true });
  });

  test('closing or reopening the plan clears the share and the consent', async () => {
    const { ctl, s, bridge } = await confirming();
    await ctl.sharePlan();
    s.consent = true;
    ctl.closePlan();
    expect(s.share).toBeNull();
    expect(s.consent).toBe(false);
    expect(bridge.calls.some((c) => c.method === 'cancel_share')).toBe(true);
  });

  test('cancel_share names the share it cancels', async () => {
    const { ctl, s, bridge } = await confirming();
    await ctl.sharePlan();
    const id = s.share!.id;
    ctl.closePlan();
    expect(bridge.calls.find((c) => c.method === 'cancel_share')!.args).toEqual([id]);
  });

  test('a late share:failed keeps a code that is already on screen', async () => {
    const { ctl, s, bridge } = await confirming();
    await ctl.sharePlan();
    const id = s.share!.id;
    bridge.emit('share:ready', { share_id: id, code: 'K7F3', url: 'l', mode: 'local', expires: null, offline: false });
    bridge.emit('share:failed', { share_id: id, code: 'K7F3', reason: 'error' });
    expect(s.share).toMatchObject({ status: 'ready', url: 'l', reason: null, offline: false });
  });

  test('a shared code other than the plan on screen recomputes the plan and asks for a new code', async () => {
    const { ctl, s, bridge } = await confirming();
    await ctl.sharePlan();
    s.consent = true;
    bridge.emit('share:ready', { share_id: s.share!.id, code: 'ABCD', url: 'u', mode: 'server', expires: null });
    expect(s.share).toBeNull();
    expect(s.consent).toBe(false);
    expect(s.planChanged).toBe(true);
    expect(bridge.calls.some((c) => c.method === 'preview_plan')).toBe(true);
  });

  test('execute passes the code only when consent is ticked', async () => {
    const { ctl, s, bridge } = await confirming();
    await ctl.execute();
    expect(bridge.calls.at(-1)!.args[2]).toBeNull();
    await ctl.sharePlan();
    bridge.emit('share:ready', { share_id: s.share!.id, code: 'K7F3', url: 'u', mode: 'server', expires: null });
    s.consent = true;
    await ctl.execute();
    expect(bridge.calls.filter((c) => c.method === 'execute').at(-1)!.args[2]).toEqual({ code: 'K7F3' });
  });

  test('plan_changed shows a notice, recomputes the plan and is not an error card', async () => {
    const { ctl, s, bridge } = await confirming();
    bridge.emit('job:error', { job_id: 'job-9', kind: 'exec', key: 'plan_changed', message: '' });
    expect(s.planChanged).toBe(true);
    expect(s.error).toBeNull();
    expect(bridge.calls.some((c) => c.method === 'preview_plan')).toBe(true);
    await ctl.sharePlan();
    expect(s.planChanged).toBe(false);
  });
});

describe('bulk selection of a verdict group', () => {
  async function scanned() {
    const { ctl, s } = setup('adware');
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(s.phase).toBe('results'));
    const app = (pkg: string) => s.scan!.apps.find((a) => a.package === pkg)!;
    return { ctl, s, group: [app('com.clean.pro.boost'), app('com.wlive.forecast'), app('com.sec.android.app.launcher')] };
  }

  test('select all keeps own choices, uses the engine proposal, then the settings action', async () => {
    const { ctl, s, group } = await scanned();
    s.selection = { 'com.wlive.forecast': 'remove' };
    expect(ctl.groupSelectLevels(group)).toEqual({
      'com.clean.pro.boost': 'disable', 'com.wlive.forecast': 'remove', 'com.sec.android.app.launcher': 'silence' });
  });

  test('one action for the selected apps; a system app gets disable instead of remove', async () => {
    const { ctl, s, group } = await scanned();
    s.selection = { 'com.clean.pro.boost': 'disable', 'com.sec.android.app.launcher': 'silence' };
    expect(ctl.groupActionLevels(group, 'remove')).toEqual({
      'com.clean.pro.boost': 'remove', 'com.sec.android.app.launcher': 'disable' });
  });

  test('apps removed in this order are left out; setLevels applies and clears at once', async () => {
    const { ctl, s, group } = await scanned();
    s.selection = {};
    s.actedLog = { 'com.clean.pro.boost': [{ order: 'A', level: 'remove' }] };
    expect(Object.keys(ctl.groupSelectLevels(group))).toEqual(['com.wlive.forecast', 'com.sec.android.app.launcher']);
    ctl.setLevels(ctl.groupSelectLevels(group));
    expect(s.selection).toEqual({ 'com.wlive.forecast': 'silence', 'com.sec.android.app.launcher': 'silence' });
    expect(s.touched).toEqual(expect.arrayContaining(['com.wlive.forecast', 'com.sec.android.app.launcher']));
    ctl.setLevels({ 'com.wlive.forecast': null, 'com.sec.android.app.launcher': null });
    expect(s.selection).toEqual({});
  });
});

describe('tryb ręczny', () => {
  async function scanned(settings: Partial<Settings> = {}) {
    const env = await setupCtl('adware');
    if (Object.keys(settings).length) await env.ctl.saveSettings(settings);
    await env.ctl.startScan();
    await vi.waitFor(() => expect(env.s.phase).toBe('results'));
    await vi.waitFor(() => expect(env.s.job).toBeNull());
    return env;
  }

  const snap = (v: unknown) => JSON.parse(JSON.stringify(v));

  test('apk:manual czyści domyślne zaznaczenia i pytanie', async () => {
    const { ctl, s, bridge } = await scanned();
    s.job = { id: 'j1', kind: 'apk' } as never;
    expect(Object.keys(s.selection).length).toBeGreaterThan(0);
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 3, eta_s: 60, eta_kind: 'rough', eta_min_s: 36, eta_max_s: 90 });
    expect(s.apkQuestion?.kind).toBe('mode');
    bridge.emit('apk:manual', { scan: { ...snap(s.scan), apk_mode: 'manual' }, job_id: 'j1' });
    expect(s.selection).toEqual({});
    expect(s.apkQuestion).toBeNull();
    expect(s.apk.running).toBe(false);
    expect(ctl.state.scan?.apk_mode).toBe('manual');
  });

  test('apk:done w trybie częściowym nie dokleja domyślnych zaznaczeń', async () => {
    const { ctl, s, bridge } = await scanned();
    bridge.emit('apk:manual', { scan: { ...snap(s.scan), apk_mode: 'manual' } });
    const pkg = s.scan!.apps[0].package;
    ctl.setLevel(pkg, 'remove');
    bridge.emit('apk:done', { scan: { ...snap(s.scan), apk_mode: 'partial', on_demand: [pkg] } });
    expect(Object.keys(s.selection)).toEqual([pkg]);
  });

  test('ustawienie „zawsze ręcznie” — scan:done bez domyślnych zaznaczeń', async () => {
    // Nagranie scenariusza odtwarza potem apk:done starego trybu — sprawdzamy stan zaraz po scan:done.
    const env = await setupCtl('adware');
    await env.ctl.saveSettings({ apk_mode_default: 'manual' });
    let atScanDone: Record<string, string> | null = null;
    env.bridge.on('scan:done', () => { atScanDone = { ...env.s.selection }; });
    await env.ctl.startScan();
    await vi.waitFor(() => expect(env.s.phase).toBe('results'));
    expect(atScanDone).toEqual({});
  });

  test('chooseApkMode odpowiada i zapamiętuje wybór', async () => {
    const { ctl, s, bridge } = await scanned();
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 3, eta_s: null, eta_kind: null, eta_min_s: null, eta_max_s: null });
    await ctl.chooseApkMode('manual', true);
    expect(s.apkQuestion).toBeNull();
    expect(bridge.calls.some((c) => c.method === 'answer' && c.args[1] === 'manual')).toBe(true);
    expect(bridge.calls.some((c) => c.method === 'save_settings'
      && (c.args[0] as Partial<Settings>).apk_mode_default === 'manual')).toBe(true);
  });

  test('analyzeSelected wysyła zaznaczone i startuje zadanie apk', async () => {
    const { ctl, s, bridge } = await scanned();
    bridge.emit('apk:manual', { scan: { ...snap(s.scan), apk_mode: 'manual' } });
    ctl.setLevel('com.clean.pro.boost', 'remove');
    await ctl.analyzeSelected();
    expect(bridge.calls.find((c) => c.method === 'analyze_selected')?.args[0]).toEqual(['com.clean.pro.boost']);
    expect(s.apk.running).toBe(true);
    expect(s.apkScope).toBe('selected');
    await ctl.analyzeAll();
    expect(s.apkScope).toBe('all');
  });

  test('przejście z pełnej analizy zostawia tylko zaznaczenia serwisanta', async () => {
    const { ctl, s, bridge } = await scanned();
    const [first] = Object.keys(s.selection);
    const other = s.scan!.apps.find((a) => !(a.package in s.selection))!.package;
    ctl.setLevel(other, 'disable');
    bridge.emit('apk:manual', { scan: { ...snap(s.scan), apk_mode: 'manual' } });
    expect(s.selection).toEqual({ [other]: 'disable' });
    expect(first in s.selection).toBe(false);
  });

  test('zaznaczenie w trybie ręcznym nie bierze poziomu z ukrytego werdyktu', async () => {
    const { ctl, s, bridge } = await scanned({ select_level: 'remove' });
    const boost = s.scan!.apps.find((a) => a.package === 'com.clean.pro.boost')!;
    expect(boost.default_level).toBe('disable');
    bridge.emit('apk:manual', { scan: { ...snap(s.scan), apk_mode: 'manual', on_demand: [] } });
    ctl.toggle(boost);
    expect(s.selection[boost.package]).toBe('remove');
    ctl.toggle(boost);
    // Po analizie na żądanie werdykt jest widoczny — wtedy obowiązuje propozycja silnika.
    bridge.emit('apk:done', { scan: { ...snap(s.scan), apk_mode: 'partial', on_demand: [boost.package] } });
    ctl.toggle(boost);
    expect(s.selection[boost.package]).toBe('disable');
  });

  // Raport po szybkim skanie, zanim wybrano tryb analizy APK.
  async function pending(setting: Settings['apk_mode_default']) {
    const env = await scanned({ apk_mode_default: setting });
    const scan = { ...snap(env.s.scan), apk_mode: 'pending', on_demand: [] };
    env.bridge.emit('scan:done', { scan, interrupted: [], client: null });
    return env;
  }

  test('„pytaj”: scan:done bez domyślnych zaznaczeń; wybór pełnej, apk:done uzupełnia propozycje', async () => {
    const { ctl, s, bridge } = await pending('ask');
    expect(s.selection).toEqual({});
    expect(s.apk.running).toBe(true);
    expect(s.apkFullChosen).toBe(false);
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 3, eta_s: 60, eta_kind: 'measured', eta_min_s: 60, eta_max_s: 60 });
    await ctl.chooseApkMode('full', false);
    expect(s.apkFullChosen).toBe(true);
    bridge.emit('apk:done', { scan: { ...snap(s.scan), apk_mode: 'full' } });
    expect(s.selection['com.clean.pro.boost']).toBe('disable');
  });

  test('„pytaj”: pełna analiza przerwana bez apk:done — propozycje jak dawniej, z poszanowaniem zmian serwisanta', async () => {
    const { ctl, s, bridge } = await pending('ask');
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 3, eta_s: 60, eta_kind: 'measured', eta_min_s: 60, eta_max_s: 60 });
    await ctl.chooseApkMode('full', false);
    ctl.setLevel('com.wlive.forecast', 'remove');
    ctl.setLevel('com.wlive.forecast', null);
    bridge.emit('apk:stopped', {});
    expect(s.selection['com.clean.pro.boost']).toBe('disable');
    expect('com.wlive.forecast' in s.selection).toBe(false);
  });

  test('„pytaj”: błąd zadania po wyborze pełnej też uzupełnia propozycje; bez wyboru — nie', async () => {
    const a = await pending('ask');
    a.bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 3, eta_s: 60, eta_kind: 'measured', eta_min_s: 60, eta_max_s: 60 });
    await a.ctl.chooseApkMode('full', false);
    a.bridge.emit('job:error', { job_id: 'j1', kind: 'apk', key: 'internal', message: '' });
    expect(a.s.selection['com.clean.pro.boost']).toBe('disable');
    const b = await pending('ask');
    b.bridge.emit('apk:stopped', {});
    expect(b.s.selection).toEqual({});
  });

  test('„zawsze pełna”: scan:done z domyślnymi zaznaczeniami jak dawniej', async () => {
    const { s } = await pending('full');
    expect(s.selection['com.clean.pro.boost']).toBe('disable');
  });

  // Atrapa z ręcznie rozstrzyganymi odpowiedziami selection_eta.
  async function withEta() {
    const bridge = createFakeBridge('adware', { delay: 0 });
    const pending: { pkgs: string[]; resolve: (v: unknown) => void; reject: (e: unknown) => void }[] = [];
    const api = new Proxy(bridge.api, {
      get: (target, method: string) => (method === 'selection_eta'
        ? (pkgs: string[]) => new Promise((resolve, reject) => pending.push({ pkgs, resolve, reject }))
        : target[method as keyof typeof target]),
    });
    const ctl = new Controller(new AppState(), { ...bridge, api });
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(ctl.state.job).toBeNull());
    bridge.emit('apk:manual', { scan: { ...snap(ctl.state.scan), apk_mode: 'manual', on_demand: [] } });
    return { ctl, s: ctl.state, bridge, pending };
  }
  const eta = (n: number) => ({ eta_s: n, eta_kind: 'measured', eta_min_s: n, eta_max_s: n });

  test('szacunek dla zaznaczenia: starsza odpowiedź nie nadpisuje nowszej', async () => {
    const { ctl, s, pending } = await withEta();
    pending.length = 0;
    ctl.setLevel('com.clean.pro.boost', 'remove');
    ctl.setLevel('com.wlive.forecast', 'remove');
    expect(pending).toHaveLength(2);
    pending[1].resolve(eta(120));
    await vi.waitFor(() => expect(s.selectionEta?.eta_s).toBe(120));
    pending[0].resolve(eta(60));
    await new Promise((r) => setTimeout(r, 0));
    expect(s.selectionEta?.eta_s).toBe(120);
  });

  test('szacunek dla zaznaczenia: błąd bez banera, zmiana trybu w trakcie ignoruje odpowiedź', async () => {
    const { ctl, s, bridge, pending } = await withEta();
    ctl.setLevel('com.clean.pro.boost', 'remove');
    pending.at(-1)!.reject(new Error('boom'));
    await new Promise((r) => setTimeout(r, 0));
    expect(s.error).toBeNull();
    expect(s.selectionEta).toBeNull();
    ctl.setLevel('com.wlive.forecast', 'remove');
    bridge.emit('apk:done', { scan: { ...snap(s.scan), apk_mode: 'full' } });
    for (const p of pending) p.resolve(eta(60));
    await new Promise((r) => setTimeout(r, 0));
    expect(s.selectionEta).toBeNull();
  });

  test('szacunek dla zaznaczenia po apk:done w trybie częściowym i po powrocie do naprawy', async () => {
    const { s, ctl, bridge, pending } = await withEta();
    s.selection = { 'com.clean.pro.boost': 'remove' };
    pending.length = 0;
    bridge.emit('apk:done', { scan: { ...snap(s.scan), apk_mode: 'partial', on_demand: ['com.wlive.forecast'] } });
    expect(pending.map((p) => p.pkgs)).toEqual([['com.clean.pro.boost']]);
    pending[0].resolve(eta(90));
    await vi.waitFor(() => expect(s.selectionEta?.eta_s).toBe(90));
    s.result = { stopped: false } as never;
    ctl.backToRepair();
    await new Promise((r) => setTimeout(r, 0));
    expect(s.selectionEta).toBeNull();
  });

  // Atrapa bez nagrania skanu: zdarzenia zadania wysyła test, jak most po kolei.
  async function liveScan(setting: Settings['apk_mode_default']) {
    const { s: s0 } = await scanned();
    const scan = { ...snap(s0.scan), apk_mode: 'pending', on_demand: [] };
    const bridge = createFakeBridge('adware', { delay: 0 });
    const api = new Proxy(bridge.api, {
      get: (target, method: string) => (method === 'start_scan'
        ? async () => ({ job_id: 'job-1' })
        : target[method as keyof typeof target]),
    });
    const ctl = new Controller(new AppState(), { ...bridge, api });
    await ctl.init();
    await ctl.saveSettings({ apk_mode_default: setting });
    await ctl.startScan();
    bridge.emit('scan:done', { scan, interrupted: [], client: null });
    return { ctl, s: ctl.state, bridge };
  }

  test('„Przerwij i szukaj ręcznie”: pełna analiza po skanie (to samo zadanie) pozwala przejść do ręcznego', async () => {
    const { ctl, s, bridge } = await liveScan('ask');
    expect(s.canStopToManual).toBe(false);  // szybki skan jeszcze nie przeszedł w analizę APK
    bridge.emit('apk:question', { job_id: 'job-1', kind: 'mode', apps: 3, eta_s: 60, eta_kind: 'rough', eta_min_s: 36, eta_max_s: 90 });
    await ctl.chooseApkMode('full', false);
    bridge.emit('apk:progress', { done: 1, total: 3, package: 'com.a', eta_s: 40, job_id: 'job-1' });
    expect(s.job).toEqual({ id: 'job-1', kind: 'apk' });
    expect(s.canStopToManual).toBe(true);
    await ctl.stopToManual();
    expect(bridge.calls.some((c) => c.method === 'stop_apk_to_manual')).toBe(true);
  });

  test('„Przerwij i szukaj ręcznie”: także przy ustawieniu „zawsze pełna” (bez pytania)', async () => {
    const { s, bridge } = await liveScan('full');
    bridge.emit('apk:progress', { done: 1, total: 3, package: 'com.a', eta_s: 40, job_id: 'job-1' });
    expect(s.canStopToManual).toBe(true);
  });

  test('„Przerwij i szukaj ręcznie” niedostępne w analizie zaznaczonych', async () => {
    const { ctl, s, bridge } = await scanned();
    bridge.emit('apk:manual', { scan: { ...snap(s.scan), apk_mode: 'manual', on_demand: [] } });
    ctl.setLevel('com.clean.pro.boost', 'remove');
    await ctl.analyzeSelected();
    expect(s.canStopToManual).toBe(false);
    await ctl.analyzeAll();
    expect(s.canStopToManual).toBe(true);
  });

  test('„Przeanalizuj wszystko”: czas z szacunku całego telefonu, nie z analizy zaznaczonych', async () => {
    const { s, bridge } = await liveScan('ask');
    const GB = 1024 ** 3;
    const est = { to_fetch_bytes: GB, total_bytes: GB, unknown: 0, cached: 0, largest_bytes: 0, limit_bytes: 10 * GB,
      effective_bytes: 10 * GB, free_bytes: 50 * GB, eta_kind: 'measured' as const, job_id: 'job-1' };
    bridge.emit('apk:estimate', { ...est, apps: 90, eta_s: 600, eta_min_s: 600, eta_max_s: 600, scope: 'all' });
    bridge.emit('apk:manual', { scan: { ...snap(s.scan), apk_mode: 'manual', on_demand: [] }, job_id: 'job-1' });
    bridge.emit('job:end', { job_id: 'job-1', kind: 'apk' });
    bridge.emit('apk:estimate', { ...est, apps: 1, eta_s: 20, eta_min_s: 20, eta_max_s: 20, scope: 'part', job_id: 'job-2' });
    expect(s.apkEstimate?.apps).toBe(1);  // karta postępu: rozmiar bieżącej analizy
    expect(s.apkFullEta?.eta_s).toBe(600);
  });

  test('„pytaj” → pełna: domyślne zaznaczenia od razu po wyborze, z poszanowaniem zmian serwisanta', async () => {
    const { ctl, s, bridge } = await pending('ask');
    ctl.setLevel('com.wlive.forecast', 'remove');
    ctl.setLevel('com.wlive.forecast', null);
    bridge.emit('apk:question', { job_id: 'j1', kind: 'mode', apps: 3, eta_s: 60, eta_kind: 'measured', eta_min_s: 60, eta_max_s: 60 });
    await ctl.chooseApkMode('full', false);
    expect(s.selection['com.clean.pro.boost']).toBe('disable');
    expect('com.wlive.forecast' in s.selection).toBe(false);
  });
});

describe('phone checks and site fixes', () => {
  const scanned = async () => {
    const bridge = createFakeBridge('adware', { delay: 0, checks: [CHECKS_SAMPLE] });
    const ctl = new Controller(new AppState(), bridge);
    await ctl.init();
    await ctl.startScan();
    await vi.waitFor(() => expect(ctl.state.job).toBeNull());
    return { bridge, ctl, s: ctl.state };
  };
  const CHROME_FIX = CHECKS_SAMPLE.browsers[0].sites[0].fix!;

  test('the scan brings the checks, with no fix selected', async () => {
    const { s } = await scanned();
    expect(s.scan!.device_checks[0].browsers.map((b) => b.name)).toEqual(['Chrome', 'Samsung Internet', 'Firefox']);
    expect(s.fixes.size).toBe(0);
  });

  test('selected fixes go to preview_plan, share_plan and execute', async () => {
    const { ctl, s, bridge } = await scanned();
    ctl.toggleFix(CHROME_FIX);
    await ctl.openPlan();
    expect(bridge.calls.filter((c) => c.method === 'preview_plan').at(-1)!.args[2]).toEqual([CHROME_FIX]);
    expect(s.plan!.apps.some((a) => a.level === 'fix')).toBe(true);
    await ctl.sharePlan();
    expect(bridge.calls.find((c) => c.method === 'share_plan')!.args[3]).toEqual([CHROME_FIX]);
    await ctl.execute();
    expect(bridge.calls.find((c) => c.method === 'execute')!.args[3]).toEqual([CHROME_FIX]);
  });

  test('toggling twice leaves nothing selected; a new scan clears the selection', async () => {
    const { ctl, s } = await scanned();
    ctl.toggleFix(CHROME_FIX);
    ctl.toggleFix(CHROME_FIX);
    expect(s.fixes.size).toBe(0);
    ctl.toggleFix(CHROME_FIX);
    await ctl.startScan();
    expect(s.fixes.size).toBe(0);
  });

  test('a re-read replaces the check and drops a fix the phone no longer offers', async () => {
    const { ctl, s, bridge } = await scanned();
    ctl.toggleFix(CHROME_FIX);
    const [chrome, ...rest] = CHECKS_SAMPLE.browsers;
    bridge.setChecks([{ ...CHECKS_SAMPLE, browsers: [{ ...chrome, sites: chrome.sites.slice(1) }, ...rest] }]);
    await ctl.recheckSiteNotifications();
    expect(s.scan!.device_checks[0].browsers[0].sites.map((x) => x.host)).toEqual(['wiadomosci.example', 'sklep.example']);
    expect(s.fixes.size).toBe(0);
  });

  test('back to repair re-reads the sites: a silenced site leaves the list', async () => {
    const { ctl, s, bridge } = await scanned();
    ctl.toggleFix(CHROME_FIX);
    s.result = { order: 'Z', status: 'done', status_label: '', stopped: false, apps: [] };
    s.phase = 'done';
    const [chrome, ...rest] = CHECKS_SAMPLE.browsers;
    bridge.setChecks([{ ...CHECKS_SAMPLE, browsers: [{ ...chrome, sites: chrome.sites.slice(1) }, ...rest] }]);
    ctl.backToRepair();
    expect(s.fixes.size).toBe(0);
    await vi.waitFor(() => expect(s.scan!.device_checks[0].browsers[0].sites.map((x) => x.host))
      .toEqual(['wiadomosci.example', 'sklep.example']));
  });

  test('a failed re-read leaves the scan and the error card alone', async () => {
    const { ctl, s, bridge } = await scanned();
    const before = s.scan!.device_checks;
    bridge.failNext('recheck_site_notifications', 'busy');
    await ctl.recheckSiteNotifications();
    expect(s.error).toBeNull();
    expect(s.scan!.device_checks).toEqual(before);
  });

  test('background recheck without a change keeps the checks', async () => {
    const { ctl, s, bridge } = await scanned();
    const before = s.scan!.device_checks;
    await ctl.recheckSiteNotifications(true); // atrapa: bez zmiany na telefonie `check` = null
    expect(bridge.calls.at(-1)).toEqual({ method: 'recheck_site_notifications', args: [true] });
    expect(s.scan!.device_checks).toBe(before);
  });

  test('user wait events: a channel step names the site and the browser, user_done clears it', async () => {
    const { s, bridge } = await scanned();
    bridge.emit('exec:user_wait', { package: 'com.android.chrome', name: 'Chrome', kind: 'channel',
      site: 'tanie-bilety.example', browser: 'Chrome', timeout: 180, action_id: 1 });
    expect(s.userWait).toMatchObject({ kind: 'channel', site: 'tanie-bilety.example', browser: 'Chrome' });
    bridge.emit('exec:user_done', { package: 'com.android.chrome', status: 'done' });
    expect(s.userWait).toBeNull();
  });

  test('exec:done carries the Firefox debugging reminder into the result', async () => {
    const { s, bridge } = await scanned();
    bridge.emit('exec:done', { order: 'ZS/1', status: 'done', status_label: '', stopped: false, apps: [], firefox_debugging: true });
    expect(s.result?.firefox_debugging).toBe(true);
  });
});

describe('data transfer', () => {
  async function chosen() {
    const env = setup('transfer');
    await env.ctl.init();
    env.s.client = 'Anna K.';
    await env.ctl.startTransfer();
    await vi.waitFor(() => expect(env.s.transfer.inventory).not.toBeNull());
    return env;
  }

  test('startTransfer reads the inventory for the picked phone and opens the copy screen', async () => {
    const { s, bridge } = await chosen();
    expect(bridge.calls.find((c) => c.method === 'transfer_inventory')?.args).toEqual(['R58T00TEST', 'Anna K.']);
    expect(s.phase).toBe('transfer_choose');
    expect(s.device?.serial).toBe('R58T00TEST');
    expect(s.transfer.selection).toEqual({ contacts: true, sms: true, mms: false, calls: true,
      categories: ['media', 'downloads', 'whatsapp'], others: [], apps: ['com.wlive.forecast', 'com.whatsapp'] });
    await vi.waitFor(() => expect(s.job).toBeNull());
  });

  test('toggles change the selection', async () => {
    const { ctl, s } = await chosen();
    ctl.toggleTransfer('downloads');
    expect(s.transfer.selection.categories).toEqual(['media', 'whatsapp']);
    ctl.toggleTransfer('sms');
    expect([s.transfer.selection.sms, s.transfer.selection.mms]).toEqual([false, false]);
    ctl.toggleTransfer('sms');
    expect([s.transfer.selection.sms, s.transfer.selection.mms]).toEqual([true, false]); // MMS: telefon ich nie podał
    ctl.toggleTransferOther('Music');
    ctl.toggleTransferOther('');
    expect(s.transfer.selection.others).toEqual(['Music', '']);
    ctl.toggleTransfer('others');
    expect(s.transfer.selection.others).toEqual([]);
    ctl.toggleTransfer('others');
    expect(s.transfer.selection.others).toEqual(['', 'Music']);
    ctl.toggleTransferApp('com.wlive.forecast');
    expect(s.transfer.selection.apps).toEqual(['com.whatsapp']);
    ctl.toggleTransfer('apps');
    expect(s.transfer.selection.apps).toEqual([]);
    ctl.toggleTransfer('apps');
    expect(s.transfer.selection.apps).toEqual(['com.wlive.forecast', 'com.whatsapp']);
  });

  test('startBackup sends the engine selection and the done event shows the result', async () => {
    const { ctl, s, bridge } = await chosen();
    ctl.toggleTransferApp('com.wlive.forecast');
    ctl.toggleTransferOther('Music');
    await ctl.startBackup();
    expect(s.phase).toBe('transfer_backup');
    const sent = bridge.calls.find((c) => c.method === 'start_backup')?.args[0] as Record<string, unknown>;
    expect(Object.keys(sent).sort()).toEqual(['apps', 'calls', 'categories', 'contacts', 'mms', 'others', 'sms']);
    expect(sent).toEqual({ contacts: true, sms: true, mms: false, calls: true,
      categories: ['media', 'downloads', 'whatsapp'], others: ['Music'], apps: ['com.whatsapp'] });
    await vi.waitFor(() => expect(s.phase).toBe('transfer_done'));
    expect(s.transfer.result?.status).toBe('complete');
    expect(s.transfer.copy?.days_left).toBe(7);
    expect(s.transfer.progress?.stage).toBe('apps');
  });

  test('waiting for the phone, then progress clears the notice', async () => {
    const { s, bridge } = await chosen();
    s.phase = 'transfer_backup';
    bridge.emit('transfer:waiting', {});
    expect(s.transfer.waiting).toBe(true);
    bridge.emit('transfer:progress', { stage: 'files', done_files: 1, total_files: 2, done_bytes: 1, total_bytes: 2, current: 'DCIM/a.jpg' });
    expect(s.transfer.waiting).toBe(false);
    expect(s.transfer.progress?.current).toBe('DCIM/a.jpg');
  });

  test('stopping asks the bridge to stop the backup job and ends as a stopped copy', async () => {
    const { ctl, s, bridge } = await chosen();
    s.phase = 'transfer_backup';
    ctl.setJob('job-9', 'backup');
    s.transfer.waiting = true;
    await ctl.stopBackup();
    expect(s.stopping).toBe(true);
    expect(bridge.calls.at(-1)).toEqual({ method: 'stop', args: ['job-9'] });
    bridge.emit('transfer:done', { result: { status: 'stopped', copy_id: 'x', telephony: {}, files_done: 0, files_failed: 0,
      apps_done: 0, apps_failed: 0, bytes: 0, seconds: 1 }, copy: { id: 'x', serial: 'S', model: 'M', manufacturer: 'm', client: null,
      created: '2026-10-25T10:00:00', expires: '2026-11-01T10:00:00', days_left: 7, status: 'in_progress', bytes: 0, counts: {} } });
    expect(s.phase).toBe('transfer_done');
    expect(s.stopping).toBe(false);
    expect(s.transfer.waiting).toBe(false);
    expect(s.transfer.result?.status).toBe('stopped');
  });

  test('a backup job error lands on the error card and returns to the choice', async () => {
    const { s, bridge } = await chosen();
    s.phase = 'transfer_backup';
    s.transfer.waiting = true;
    bridge.emit('job:error', { job_id: 'job-2', kind: 'backup', key: 'transfer_disk_full', message: '' });
    expect(s.error?.key).toBe('transfer_disk_full');
    expect(s.phase).toBe('transfer_choose');
    expect(s.transfer.waiting).toBe(false);
  });

  test('an inventory error returns to connect', async () => {
    const { ctl, s, bridge } = setup('transfer');
    await ctl.init();
    s.phase = 'transfer_choose';
    bridge.emit('job:error', { job_id: 'job-1', kind: 'transfer_scan', key: 'timeout', message: '' });
    expect(s.phase).toBe('connect');
    expect(s.error?.key).toBe('timeout');
  });

  test('start_backup refused without an inventory stays on the choice with the error', async () => {
    const { ctl, s, bridge } = await chosen();
    bridge.failNext('start_backup', 'transfer_no_inventory');
    await ctl.startBackup();
    expect(s.phase).toBe('transfer_choose');
    expect(s.error?.key).toBe('transfer_no_inventory');
  });

  test('re-checking the WhatsApp backup updates the inventory', async () => {
    const { ctl, s } = await chosen();
    expect(s.transfer.inventory?.whatsapp_backup).toBeNull();
    await ctl.recheckWhatsapp();
    expect(s.transfer.inventory?.whatsapp_backup).toBe('2026-09-26T14:29:00');
  });

  test('copies: load, extend, delete', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    bridge.setCopies([{ id: 'S/1', serial: 'S', model: 'M', manufacturer: 'm', client: 'Anna', created: '2026-10-25T10:00:00',
      expires: '2026-11-01T10:00:00', days_left: 7, status: 'complete', bytes: 10, counts: {} }]);
    await ctl.loadTransfers();
    expect(s.transfer.copies).toHaveLength(1);
    await ctl.extendTransfer('S/1');
    expect(s.transfer.copies[0].days_left).toBe(14);
    expect(s.transfer.copies[0].expires).toBe('2026-11-08T10:00:00');
    await ctl.deleteTransfer('S/1');
    expect(s.transfer.copies).toEqual([]);
  });

  test('a refused delete (copy in use) keeps the copy and shows the error', async () => {
    const { ctl, s, bridge } = setup('transfer');
    await ctl.init();
    s.transfer.copies = [{ id: 'S/1' } as never];
    bridge.failNext('delete_transfer', 'busy');
    await ctl.deleteTransfer('S/1');
    expect(s.transfer.copies).toHaveLength(1);
    expect(s.error?.key).toBe('busy');
  });

  test('opening the history loads the copies', async () => {
    const { ctl, bridge } = setup('transfer');
    await ctl.init();
    await ctl.openHistory();
    expect(bridge.calls.some((c) => c.method === 'transfers')).toBe(true);
  });

  test('leaving the transfer goes back to connect', async () => {
    const { ctl, s } = await chosen();
    ctl.leaveTransfer();
    expect(s.phase).toBe('connect');
    expect(s.transfer.inventory).toBeNull();
  });
});

describe('data transfer — resuming', () => {
  const RESUMABLE = { id: 'R58T00TEST-x/20260925-100000', serial: 'R58T00TEST', model: 'SM-A145R', manufacturer: 'samsung', client: 'Anna K.',
    created: '2026-09-25T10:00:00', expires: '2026-10-02T10:00:00', days_left: 6, status: 'in_progress' as const, bytes: 0,
    counts: {} };

  test('the inventory of a phone with an interrupted copy starts from that copy\'s selection', async () => {
    const { ctl, s, bridge } = setup('transfer');
    await ctl.init();
    s.phase = 'transfer_choose';
    const event = (await import('../../../tests/fixtures/bridge/transfer.json')).default.calls
      .find((c) => c.method === 'transfer_inventory')!.events.find(([name]) => name === 'transfer:inventory')![1] as never;
    bridge.emit('transfer:inventory', { ...(event as object), resumable: { ...RESUMABLE, selection: {
      contacts: true, sms: false, mms: false, calls: false, categories: ['media'], others: ['Music', 'Gone'],
      apps: ['com.whatsapp'], verify_hash: false } as never } } as never);
    expect(s.transfer.selection).toEqual({ contacts: true, sms: false, mms: false, calls: false, categories: ['media'],
      others: ['Music'], apps: ['com.whatsapp'] });
    await ctl.startBackup();
    expect(bridge.calls.find((c) => c.method === 'start_backup')?.args[0]).toEqual({ contacts: true, sms: false, mms: false,
      calls: false, categories: ['media'], others: ['Music'], apps: ['com.whatsapp'] });
  });

  test('"Resume" on the connect screen continues the copy straight after reading the phone', async () => {
    const { ctl, s, bridge } = setup('transfer');
    await ctl.init();
    // słuchacz po kontrolerze: telefon ma przerwaną kopię (nagranie jej nie ma)
    bridge.on('transfer:inventory', () => {
      s.transfer.resumable = RESUMABLE;
      s.transfer.selection = { ...s.transfer.selection, sms: false, apps: [] };
    });
    await ctl.startTransfer(true);
    await vi.waitFor(() => expect(bridge.calls.some((c) => c.method === 'start_backup')).toBe(true));
    expect(bridge.calls.find((c) => c.method === 'start_backup')?.args[0]).toMatchObject({ sms: false, apps: [] });
  });

  test('"Resume" stays on the choose screen when the copy cannot go on (gone, no space)', async () => {
    const { ctl, s, bridge } = setup('transfer');
    await ctl.init();
    await ctl.startTransfer(true);  // nagranie: kopii do wznowienia już nie ma
    await vi.waitFor(() => expect(s.job).toBeNull());
    expect(s.phase).toBe('transfer_choose');
    bridge.on('transfer:inventory', (d) => {
      s.transfer.resumable = RESUMABLE;
      s.transfer.inventory = { ...d.inventory, free_pc: 0 };
    });
    await ctl.startTransfer(true);
    await vi.waitFor(() => expect(s.job).toBeNull());
    expect(s.phase).toBe('transfer_choose');
    expect(bridge.calls.some((c) => c.method === 'start_backup')).toBe(false);
    // zwykłe „Przenieś dane” nigdy nie rusza samo
    await ctl.startTransfer();
    await vi.waitFor(() => expect(s.job).toBeNull());
    expect(bridge.calls.some((c) => c.method === 'start_backup')).toBe(false);
  });

  test('re-ticking apps selects every app when none is on by default', async () => {
    const { ctl, s } = setup('transfer');
    await ctl.init();
    s.transfer.inventory = { apps: [{ package: 'a', label: 'A', verdict: 'suspicious', default_on: false, bytes: null }],
      others: [] } as never;
    ctl.toggleTransfer('apps');
    expect(s.transfer.selection.apps).toEqual(['a']);
    ctl.toggleTransfer('apps');
    expect(s.transfer.selection.apps).toEqual([]);
  });

  test('after a backup error the interrupted copy is offered for resuming', async () => {
    const { ctl, s, bridge } = setup('empty');
    await ctl.init();
    s.phase = 'transfer_backup';
    s.device = { serial: 'R58T00TEST', manufacturer: 'samsung', model: 'SM-A145R' } as never;
    // ten sam model, inny egzemplarz: wznowić można tylko kopię tego telefonu
    bridge.setCopies([{ ...RESUMABLE, id: 'OTHER/20260925-100000', serial: 'OTHER' }, RESUMABLE]);
    bridge.emit('job:error', { job_id: 'job-2', kind: 'backup', key: 'transfer_disk_full', message: '' });
    await vi.waitFor(() => expect(s.transfer.resumable?.id).toBe(RESUMABLE.id));
    expect(s.phase).toBe('transfer_choose');
  });
});
