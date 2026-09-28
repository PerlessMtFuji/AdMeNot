// Atrapa mostu: odtwarza scenariusze nagrane z prawdziwego Api (scripts/record_bridge_fixtures.py).
import type { Bridge } from './bridge';
import type { Api, EventMap, EventName, ScanView, ServiceInfo, Settings } from './types';

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
  calls: { method: string; args: unknown[] }[];
  emit<K extends EventName>(name: K, detail: EventMap[K]): void;
};

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function createFakeBridge(name: string, options: { delay?: number } = {}): FakeBridge {
  const data = scenarios[name];
  if (!data) throw new Error(`unknown scenario: ${name}`);
  const delay = options.delay ?? 15;
  const queues = new Map<string, RecordedCall[]>();
  for (const call of data.calls) {
    queues.set(call.method, [...(queues.get(call.method) ?? []), call]);
  }
  const target = new EventTarget();
  const calls: FakeBridge['calls'] = [];
  let settings: Settings = { lang: 'pl', mode: 'simple', adb_path: null, backups_dir: null, theme: 'system' };
  let service: ServiceInfo = { name: null, address: null, phone: null, logo: null };
  let lastScan: ScanView | null = null;

  const dispatch = (event: string, detail: unknown) => {
    if (event === 'scan:done' || event === 'apk:done') lastScan = (detail as { scan: ScanView }).scan;
    target.dispatchEvent(new CustomEvent(event, { detail: structuredClone(detail) }));
  };

  // Zdarzenia zawsze po zwróceniu wyniku (jak w pywebview), jedno wywołanie po drugim.
  let chain: Promise<void> = Promise.resolve();
  const replay = (events: [string, unknown][]) => {
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
      case 'save_settings':
        settings = { ...settings, ...(args[0] as Partial<Settings>) };
        return { ...settings };
      case 'rerender':
        return { scan: lastScan };
      case 'list_devices':
        return { devices: [], error: null };
      case 'history':
        return { serial: null, serials: [], orders: [], devices: [] };
      case 'check_adb':
        return { ok: true, version: 'Android Debug Bridge version 1.0.41', message: '' };
      case 'pick_folder':
        return { path: 'D:\\DeMalware\\kopie' };
      case 'service':
        return { ...service };
      case 'save_service':
        service = { ...service, ...(args[0] as Partial<ServiceInfo>) };
        return { ...service };
      case 'pick_logo':
        return { path: 'D:\\DeMalware\\logo.png' };
      case 'report': {
        const stem = String(args[0]).replaceAll('/', '-');
        const dir = 'C:\\Users\\serwis\\AppData\\Local\\DeMalware\\reports';
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
      default:
        return { error: { key: 'internal', message: `fake bridge: ${method}` } };
    }
  };

  const invoke = (method: string, args: unknown[]): unknown => {
    calls.push({ method, args });
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
  };
}
