// Atrapa mostu: odtwarza scenariusze nagrane z prawdziwego Api (scripts/record_bridge_fixtures.py).
import type { Bridge } from './bridge';
import type { Api, CrashSummary, EventMap, EventName, ScanView, ServiceInfo, Settings, ShotView, TelemetrySample, UpdateView } from './types';
// Wynik `telemetry_events.sample()` z Pythona (Task 7 planu kroku H) — ten sam kształt co prawdziwe zdarzenia.
import SAMPLE from './telemetrySample.json';

interface RecordedCall {
  method: string;
  args: unknown[];
  result: unknown;
  events: [string, unknown][];
}

interface Recorded {
  name: string;
  calls: RecordedCall[];
}

const files = import.meta.glob('../../../tests/fixtures/bridge/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, Recorded>;

const scenarios: Record<string, Recorded> = Object.fromEntries(
  Object.values(files).map((data) => [data.name, data]),
);

export function scenarioNames(): string[] {
  return Object.keys(scenarios);
}

export type FakeBridge = Bridge & {
  setCrashes(reports: CrashSummary[], startup: string[]): void;
  failNextCrashSend(key: string): void;
  failNext(method: string, key: string): void;  // następne wywołanie `method` zwraca błąd `key`
  calls: { method: string; args: unknown[] }[];
  emit<K extends EventName>(name: K, detail: EventMap[K]): void;
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function createFakeBridge(name: string, options: { delay?: number; welcome?: boolean } = {}): FakeBridge {
  const data = scenarios[name];
  if (!data) throw new Error(`unknown scenario: ${name}`);
  const delay = options.delay ?? 15;
  const queues = new Map<string, RecordedCall[]>();
  for (const call of data.calls) {
    queues.set(call.method, [...(queues.get(call.method) ?? []), call]);
  }
  const target = new EventTarget();
  const calls: FakeBridge['calls'] = [];
  let settings: Settings = { lang: 'pl', mode: 'simple', adb_path: null, backups_dir: null, theme: 'system', mirror_auto: false,
    apk_cache_limit_gb: 10, apk_cache_clear_after_repair: false, select_level: 'silence',
    check_updates: true, dismissed_update: null, last_run_version: null,
    welcome_version: options.welcome ? null : 1, welcome_current: 1, telemetry: false, telemetry_packages: false,
    telemetry_id: null, telemetry_delete_pending: false };
  let service: ServiceInfo = { name: null, address: null, phone: null, logo: null };
  let lastScan: ScanView | null = null;
  let mirror: { serial: string | null; state: string } = { serial: null, state: 'stopped' };
  let update: UpdateView = { available: null, dismissed: false, retired: null, updated_to: null, updated_notes: null, installable: true };
  const shots: ShotView[] = [];
  let crashes: CrashSummary[] = [];
  let crashStartup: string[] = [];
  let failSend: string | null = null;
  const failures = new Map<string, string>();
  const SHOT_IMAGE = 'data:image/svg+xml,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="90" height="200"><rect width="90" height="200" rx="8" fill="#1f2937"/>'
    + '<rect x="8" y="40" width="74" height="90" rx="6" fill="#f59e0b"/></svg>');

  const dispatch = (event: string, detail: unknown) => {
    if (event === 'update:state') update = structuredClone(detail as UpdateView);
    if (event === 'scan:done' || event === 'apk:done') lastScan = (detail as { scan: ScanView }).scan;
    target.dispatchEvent(new CustomEvent(event, { detail: structuredClone(detail) }));
  };

  // Zdarzenia zawsze po zwróceniu wyniku (jak w pywebview), jedno wywołanie po drugim.
  let chain: Promise<void> = Promise.resolve();
  const replay = (events: [string, unknown][]) => {
    if (events.length === 0) return; // nic do wysłania: nie zajmuje miejsca w łańcuchu (bez sztucznego opóźnienia)
    chain = chain.then(async () => {
      await sleep(delay);
      for (const [event, detail] of events) {
        if (delay > 0 && event !== 'adb:command') await sleep(delay);
        dispatch(event, detail);
      }
    });
  };

  const fallback = (method: string, args: unknown[]): unknown => {
    switch (method) {
      case 'get_settings':
        return { ...settings };
      case 'save_settings': {
        const changes = args[0] as Partial<Settings>;
        if ((changes.apk_cache_limit_gb ?? 0) > 120) return { error: { key: 'bad_request', message: 'apk_cache_limit_gb' } };
        settings = { ...settings, ...changes };
        return { ...settings };
      }
      case 'accept_welcome':
        settings = { ...settings, welcome_version: settings.welcome_current };
        return fallback('set_telemetry', args);
      case 'set_telemetry': {
        const [on, packages] = args as [boolean, boolean];
        settings = { ...settings, telemetry: on, telemetry_packages: on && packages,
          telemetry_id: on ? settings.telemetry_id ?? '3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b' : null,
          telemetry_delete_pending: !on && settings.telemetry_id !== null ? true : settings.telemetry_delete_pending };
        return { ...settings };
      }
      case 'telemetry_sample':
        return SAMPLE as TelemetrySample;
      case 'open_privacy':
        return { ok: true };
      case 'apk_cache': {
        const GB = 1024 ** 3;
        const limit = settings.apk_cache_limit_gb * GB;
        return { size_bytes: 3.4 * GB, free_bytes: 4 * GB, disk_bytes: 120 * GB, limit_bytes: limit,
                 effective_bytes: Math.min(limit, 5.4 * GB), path: 'C:\\Users\\serwis\\AppData\\Local\\AdMeNot\\apk-cache' };
      }
      case 'start_incident':
      case 'mark_incident':
        return { ok: true };
      case 'deep_analyze':
        return { job_id: 'job-deep' };
      case 'clear_apk_cache':
        return { freed_bytes: 3.4 * 1024 ** 3 };
      case 'rerender':
        return { scan: lastScan };
      case 'list_devices':
        return { devices: [], error: null };
      case 'history':
        return { serial: null, serials: [], orders: [], devices: [] };
      case 'check_adb':
        return { ok: true, version: 'Android Debug Bridge version 1.0.41', message: '', source: 'bundled',
                 path: 'C:\\AdMeNot\\tools\\scrcpy\\adb.exe' };
      case 'mirror_status':
        return { available: true, serial: mirror.serial, state: mirror.state, reason: null };
      case 'mirror_start': {
        const serial = String(args[0]);
        if (mirror.serial === serial && mirror.state !== 'stopped') return { serial, state: mirror.state, reason: null };
        mirror = { serial, state: 'running' };
        replay([['mirror:state', { serial, state: 'starting', reason: null }],
                ['mirror:state', { serial, state: 'running', reason: null }]]);
        return { serial, state: 'starting', reason: null };
      }
      case 'mirror_stop': {
        const serial = mirror.serial;
        mirror = { serial: null, state: 'stopped' };
        if (serial) replay([['mirror:state', { serial, state: 'stopped', reason: 'closed' }]]);
        return { ok: true };
      }
      case 'close_order':
        return { ok: true };
      case 'screenshot': {
        const chosen = shots.filter((x) => x.in_report).length;
        const shot: ShotView = { id: shots.length + 1, taken_at: '2026-09-26T14:31:00',
          caption: 'Na pierwszym planie: com.clean.pro.boost', black: false, in_report: chosen < 8, image: SHOT_IMAGE };
        shots.push(shot);
        return { shot: { ...shot }, count: shots.filter((x) => x.in_report).length };
      }
      case 'screenshots':
        return { order: args[0], limit: 8, items: shots.map((x) => ({ ...x })) };
      case 'set_screenshot_in_report': {
        const shot = shots.find((x) => x.id === args[0]);
        if (!shot) return { error: { key: 'unknown_screenshot', message: String(args[0]) } };
        if (args[1] && !shot.in_report && shots.filter((x) => x.in_report).length >= 8) {
          return { error: { key: 'shot_limit', message: '8' } };
        }
        shot.in_report = Boolean(args[1]);
        return { ...shot };
      }
      case 'pick_folder':
        return { path: 'D:\\AdMeNot\\kopie' };
      case 'service':
        return { ...service };
      case 'save_service':
        service = { ...service, ...(args[0] as Partial<ServiceInfo>) };
        return { ...service };
      case 'pick_logo':
        return { path: 'D:\\AdMeNot\\logo.png' };
      case 'report': {
        const stem = String(args[0]).replaceAll('/', '-');
        const dir = 'C:\\Users\\serwis\\AppData\\Local\\AdMeNot\\reports';
        return { order: args[0], html: `${dir}\\${stem}.html`, pdf: `${dir}\\${stem}.pdf`,
                 error: null, opened: `${dir}\\${stem}.pdf` };
      }
      case 'who_is_showing':
        return { resumed: null, overlays: [], errors: [] };
      case 'adb_shell':
        return { ok: true, output: `(atrapa) ${String(args[0])}\n` };
      case 'watch_devices':
      case 'stop':
      case 'answer':
      case 'quit':
        return { ok: true };
      case 'update_state':
        return { ...update };
      case 'dismiss_update':
        update = { ...update, dismissed: true };
        return { ...update };
      case 'install_update':
        return update.installable ? { job_id: 'job-update' } : { opened: true };
      case 'capture_ui_error':
        return { crash: '20261009-140312-ui00' };
      case 'crash_reports':
        return { reports: [...crashes], startup: [...crashStartup] };
      case 'crash_preview':
        return { body: { format: 1, kind: 'error', error: { type: 'KeyError', message: "'x'" },
          adb_tail: args[1] ? ['14:00:00\tok\t0.1s\tshell:pm list packages'] : null,
          comment: String(args[2] ?? '') || null }, has_adb: true };
      case 'send_crash':
        if (failSend) { const key = failSend; failSend = null; return { error: { key, message: '' } }; }
        return { sent_id: 'R-7K3Q9M' };
      case 'discard_crash':
        crashes = crashes.filter((c) => c.id !== args[0]);
        return {};
      case 'execute':
      case 'resume':
        if (update.retired) return { error: { key: 'retired', message: update.retired.reason ?? '', min_supported: update.retired.min_supported } };
        return { error: { key: 'internal', message: `fake bridge: ${method}` } };
      default:
        return { error: { key: 'internal', message: `fake bridge: ${method}` } };
    }
  };

  const invoke = (method: string, args: unknown[]): unknown => {
    calls.push({ method, args });
    const failure = failures.get(method);
    if (failure) {
      failures.delete(method);
      return { error: { key: failure, message: '' } };
    }
    const queue = queues.get(method);
    if (!queue || queue.length === 0) return fallback(method, args);
    const call = queue.length > 1 ? queue.shift()! : queue[0];
    replay(call.events);
    return structuredClone(call.result);
  };

  const api = new Proxy({} as Api, {
    get: (_target, method: string) => async (...args: unknown[]) => invoke(method, args),
  });

  return {
    api,
    calls,
    on: (event, handler) => {
      const listener = (e: Event) => handler((e as CustomEvent).detail);
      target.addEventListener(event, listener);
      return () => target.removeEventListener(event, listener);
    },
    emit: (event, detail) => dispatch(event, detail),
    setCrashes: (reports, startup) => { crashes = [...reports]; crashStartup = [...startup]; },
    failNextCrashSend: (key) => { failSend = key; },
    failNext: (method, key) => { failures.set(method, key); },
  };
}
