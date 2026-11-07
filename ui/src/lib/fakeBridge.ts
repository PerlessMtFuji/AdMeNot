// Atrapa mostu: odtwarza scenariusze nagrane z prawdziwego Api (scripts/record_bridge_fixtures.py).
import type { Bridge } from './bridge';
import { live } from './fakeBridgeLive';
import type { Api, ApiError, EntryView, ExplorerListView, CopyView, CrashSummary, DeviceCheck, EventMap, EventName, Lang, PlanView, ScanView, ServiceInfo, Settings, ShotView, TaskView, TelemetrySample, UpdateView } from './types';
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
  failNext(method: string, key: string, message?: string): void;  // następne wywołanie `method` zwraca błąd `key`
  answerNext(method: string, result: unknown): void;  // następne wywołanie `method` zwraca `result` (np. problemy planu)
  setChecks(checks: DeviceCheck[]): void;  // co zwróci następny `recheck_site_notifications` (i kolejne skany)
  setCopies(copies: CopyView[]): void;  // kopie danych na komputerze (`transfers` bez nagrania w scenariuszu)
  calls: { method: string; args: unknown[] }[];
  emit<K extends EventName>(name: K, detail: EventMap[K]): void;
  /** Koniec atrapy: spóźnione zdarzenia (łańcuch `replay`, timery) już nic nie wysyłają. */
  dispose(): void;
};


const isError = (result: unknown): boolean => typeof result === 'object' && result !== null && 'error' in result
  && (result as { error: unknown }).error !== null;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const CHROME = 'com.android.chrome';
const SAMSUNG = 'com.sec.android.app.sbrowser';
const FIREFOX = 'org.mozilla.firefox';

/** Kontrole „Stanu telefonu” z wypełnionymi przeglądarkami: nagrane scenariusze mają telefon, którego nie rozpoznano. */
export const CHECKS_SAMPLE: DeviceCheck = {
  id: 'site_notifications', state: 'review', state_label: 'Do sprawdzenia',
  browsers: [
    { package: CHROME, name: 'Chrome', mode: 'per_site', read: 'ok', rdp_hint: false, block_action: false,
      all_fix: null, all_fix_label: null,
      sites: [
        { host: 'tanie-bilety.example', origin: 'https://tanie-bilety.example', blocked: false, active: true,
          fix: `site:${CHROME}:web:https://tanie-bilety.example;0`, fix_label: 'Wyłączenie powiadomień: tanie-bilety.example (Chrome)' },
        { host: 'wiadomosci.example', origin: 'https://wiadomosci.example', blocked: false, active: false,
          fix: `site:${CHROME}:web:https://wiadomosci.example;0`, fix_label: 'Wyłączenie powiadomień: wiadomosci.example (Chrome)' },
        { host: 'sklep.example', origin: 'https://sklep.example', blocked: true, active: false, fix: null, fix_label: null },
      ] },
    { package: SAMSUNG, name: 'Samsung Internet', mode: 'shared', read: 'partial', rdp_hint: false, block_action: true,
      all_fix: `site_all:${SAMSUNG}`, all_fix_label: 'Wyłączenie powiadomień wszystkich witryn (Samsung Internet)',
      sites: [{ host: 'reklamy.example', origin: 'https://reklamy.example', blocked: false, active: true, fix: null, fix_label: null }] },
    { package: FIREFOX, name: 'Firefox', mode: 'shared', read: 'partial', rdp_hint: true, block_action: false,
      all_fix: null, all_fix_label: null, sites: [] },
  ],
};

/** Przeglądarka, która jest też aplikacją z planu naprawy (adware): poprawka i poziom aplikacji w jednym zleceniu. */
export const CHECKS_APP_BROWSER: DeviceCheck = {
  id: 'site_notifications', state: 'review', state_label: 'Do sprawdzenia',
  browsers: [{ package: 'com.wlive.forecast', name: 'Forecast', mode: 'per_site', read: 'ok', rdp_hint: false,
    block_action: false, all_fix: null, all_fix_label: null,
    sites: [{ host: 'tanie-bilety.example', origin: 'https://tanie-bilety.example', blocked: false, active: true,
      fix: 'site:com.wlive.forecast:web:https://tanie-bilety.example;0',
      fix_label: 'Wyłączenie powiadomień: tanie-bilety.example (Forecast)' }] }],
};

/** Wysyłka planu dla klienta (spec plan-qr §6.4): serwer od razu, kod lokalny i potem serwer, plan za długi. */
export type ShareScenario = 'server' | 'local' | 'too_long';

export function createFakeBridge(name: string,
  options: { delay?: number; welcome?: boolean; share?: ShareScenario; lang?: Lang; checks?: DeviceCheck[] } = {}): FakeBridge {
  const data = scenarios[name];
  if (!data) throw new Error(`unknown scenario: ${name}`);
  const delay = options.delay ?? 15;
  const queues = new Map<string, RecordedCall[]>();
  for (const call of data.calls) {
    queues.set(call.method, [...(queues.get(call.method) ?? []), call]);
  }
  const target = new EventTarget();
  const calls: FakeBridge['calls'] = [];
  let settings: Settings = { lang: options.lang ?? 'pl', mode: 'simple', adb_path: null, backups_dir: null, report_pdf_dir: null, theme: 'system', mirror_auto: false,
    apk_cache_limit_gb: 10, apk_cache_clear_after_repair: false, select_level: 'silence', retention_days: 60,
    check_updates: true, dismissed_update: null, last_run_version: null,
    welcome_version: options.welcome ? null : 1, welcome_current: 1, telemetry: false, telemetry_packages: false,
    telemetry_id: null, telemetry_delete_pending: false, donate_reminders: true, apk_mode_default: 'full',
    transfers_dir: null, transfer_keep_days: 7, transfer_apps_default: true, verify_copies: false,
    explorer_hidden: false, explorer_dest_mode: 'last', explorer_dest_fixed: null, report_open: true,
    explorer_recent_phones: 0 };
  let service: ServiceInfo = { name: null, address: null, phone: null, logo: null, email: null, nip: null,
    website: null, technician: null, footer: null };
  let lastScan: ScanView | null = null;
  let mirror: { serial: string | null; state: string } = { serial: null, state: 'stopped' };
  let update: UpdateView = { available: null, dismissed: false, retired: null, updated_to: null, updated_notes: null, installable: true };
  const shots: ShotView[] = [];
  let crashes: CrashSummary[] = [];
  let crashStartup: string[] = [];
  let failSend: string | null = null;
  const failures = new Map<string, { key: string; message: string }>();
  let checks: DeviceCheck[] | null = options.checks ? structuredClone(options.checks) : null;
  let checksChanged = false; // odpytywanie w tle (`whenDebugging`) dostaje odczyt tylko po zmianie
  let copies: CopyView[] = [];
  let planCode = 'K7F3'; // kod ostatniego podglądu planu: udostępnienie liczy ten sam plan
  let taskSeq = 0;
  const tasks: TaskView[] = [];
  const fakeTask = (kind: TaskView['kind'], dest: string): TaskView => ({
    id: `s1t${++taskSeq}`, kind, status: 'queued', done_files: 0, total_files: 2, done_bytes: 0, total_bytes: 2048,
    speed: 0, eta_s: null, skipped: 0, renamed: 0, failed: [], verified: null, dest, omitted: 0, targets: [] });
  const answers = new Map<string, unknown>();
  const SHOT_IMAGE = 'data:image/svg+xml,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="90" height="200"><rect width="90" height="200" rx="8" fill="#1f2937"/>'
    + '<rect x="8" y="40" width="74" height="90" rx="6" fill="#f59e0b"/></svg>');

  let disposed = false;
  const dispose = () => {
    disposed = true;
    live.delete(dispose);
  };
  live.add(dispose);  // `disposeFakeBridges()` po każdym teście

  const dispatch = (event: string, detail: unknown) => {
    // po końcu atrapy (albo środowiska jsdom po teście) zdarzenie nie ma już odbiorcy
    if (disposed || typeof CustomEvent === 'undefined') return;
    if (checks && (event === 'scan:done' || event === 'apk:done' || event === 'apk:manual')) {
      // Kopia: nagrania są wspólne dla wszystkich atrap w procesie, więc ich zdarzeń nie wolno zmieniać.
      const scan = (detail as { scan: ScanView }).scan;
      detail = { ...(detail as object), scan: { ...scan, device_checks: structuredClone(checks) } };
    }
    if (event === 'update:state') update = structuredClone(detail as UpdateView);
    if (event === 'scan:done' || event === 'apk:done' || event === 'apk:manual') lastScan = (detail as { scan: ScanView }).scan;
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
      case 'transfers':
        return { copies: structuredClone(copies) };
      case 'extend_transfer': {
        const copy = copies.find((c) => c.id === args[0]);
        if (!copy) return { error: { key: 'bad_request', message: 'copy_id' } };
        // jak most: +`transfer_keep_days` dni od obecnej daty wygaśnięcia, czas lokalny bez strefy
        const days = settings.transfer_keep_days;
        const d = new Date(copy.expires);
        d.setDate(d.getDate() + days);
        const p = (n: number) => String(n).padStart(2, '0');
        const expires = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
        Object.assign(copy, { expires, days_left: copy.days_left + days });
        return { copy: structuredClone(copy) };
      }
      case 'set_transfer_note': {
        const copy = copies.find((c) => c.id === args[0]);
        if (!copy) return { error: { key: 'bad_request', message: 'copy_id' } };
        copy.note = typeof args[1] === 'string' && args[1].trim() ? args[1].trim() : null;
        return { copy: structuredClone(copy) };
      }
      case 'delete_transfer':
        copies = copies.filter((c) => c.id !== args[0]);
        return { deleted: String(args[0]) };
      case 'skip_tap':
        return {};
      case 'transfer_whatsapp':
        return { whatsapp_backup: '2026-09-26T14:29:00' };
      case 'transfer_rescan': {
        // Scenariusz bez nagranego ponownego skanu: ten sam odczyt co `transfer_inventory`.
        const events = data.calls.find((c) => c.method === 'transfer_inventory')?.events ?? [];
        const end = events.find(([event]) => event === 'job:end')?.[1] as { job_id: string } | undefined;
        if (!end) return { error: { key: 'transfer_no_inventory', message: '' } };
        replay(events);
        return { job_id: end.job_id };
      }
      case 'delete_order':
        return { deleted: String(args[0]) };
      case 'get_settings':
        return { ...settings };
      case 'save_settings': {
        const changes = args[0] as Partial<Settings>;
        if ((changes.apk_cache_limit_gb ?? 0) > 120) return { error: { key: 'bad_request', message: 'apk_cache_limit_gb' } };
        // jak most: folder PDF tylko jako ścieżka bezwzględna (litera dysku albo udział sieciowy)
        if (changes.report_pdf_dir && !/^([A-Za-z]:[\\/]|\\\\)/.test(changes.report_pdf_dir)) {
          return { error: { key: 'bad_request', message: 'report_pdf_dir' } };
        }
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
      case 'open_donate':
        return { ok: true };
      case 'set_donate_reminders':
        settings = { ...settings, donate_reminders: args[0] as boolean };
        return { ...settings };
      case 'apk_cache': {
        const GB = 1024 ** 3;
        const limit = settings.apk_cache_limit_gb * GB;
        return { size_bytes: 3.4 * GB, free_bytes: 4 * GB, disk_bytes: 120 * GB, limit_bytes: limit,
                 effective_bytes: Math.min(limit, 5.4 * GB), path: 'C:\\Users\\serwis\\AppData\\Local\\AdMeNot\\apk-cache' };
      }
      case 'analyze_selected':
      case 'analyze_all':
        return { job_id: 'job-apk' };
      case 'stop_apk_to_manual':
        return { ok: true };
      case 'selection_eta':
        return { eta_s: 20, eta_kind: 'measured', eta_min_s: 20, eta_max_s: 20 };
      case 'start_incident':
      case 'mark_incident':
        return { ok: true };
      case 'share_plan': {
        const shareId = String(args[2]);
        const code = planCode;
        const server: [string, unknown] = ['share:ready', { share_id: shareId, code, mode: 'server',
          expires: '2026-10-11T13:32:00Z', url: `https://admenot.perlessmtfuji.workers.dev/plan#s.${'A'.repeat(22)}.${'B'.repeat(43)}` }];
        if (options.share === 'too_long') {
          replay([['share:failed', { share_id: shareId, code, reason: 'too_long', offline: true }]]);
        } else if (options.share === 'local') {
          replay([['share:ready', { share_id: shareId, code, mode: 'local', expires: null, offline: true,
            url: `https://admenot.perlessmtfuji.workers.dev/plan#l.${'x'.repeat(1498)}` }]]);
          setTimeout(() => dispatch(...server), 3000); // pełny plan dochodzi po powrocie sieci
        } else {
          replay([server]);
        }
        return { share_id: shareId, code };
      }
      case 'cancel_share':
        return { ok: true };
      case 'recheck_site_notifications':
        if (args[0] === true && !checksChanged) return { check: null };
        checksChanged = false;
        return { check: structuredClone(checks?.[0] ?? lastScan?.device_checks[0]) };
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
      case 'explorer_storage':
        return { total: 128 * 1024 ** 3, used: 71 * 1024 ** 3, free: 57 * 1024 ** 3,
          groups: { photos: 28 * 1024 ** 3, videos: 17 * 1024 ** 3, whatsapp: 6 * 1024 ** 3, other: 20 * 1024 ** 3 } };
      case 'explorer_close':
      case 'explorer_pause':
      case 'explorer_resume':
      case 'explorer_cancel':
      case 'explorer_open_folder':
        return {};
      // Kopia i wgrywanie nie mają nagrania (kolejka w tle): zadanie w kolejce, postęp wstrzykują testy (`emit`).
      case 'explorer_copy':
      case 'explorer_upload': {
        const task = fakeTask(method === 'explorer_copy' ? 'to_pc' : 'to_phone',
          String(args[1] ?? settings.explorer_dest ?? ''));
        tasks.push(task);
        return { task: task.id };
      }
      case 'explorer_pick_dest':
        settings = { ...settings, explorer_dest: 'D:\\Serwis\\Kowalska' };
        return { path: 'D:\\Serwis\\Kowalska' };
      case 'explorer_pick_upload':
        return { paths: args[0] === 'folder' ? ['C:\\Users\\serwis\\Desktop\\Faktury_2026']
          : ['C:\\Users\\serwis\\Desktop\\zdjecie.jpg', 'C:\\Users\\serwis\\Desktop\\umowa.pdf'] };
      case 'explorer_clipboard':
        return { paths: ['C:\\Users\\serwis\\Documents\\faktura.pdf'] };
      case 'explorer_retry': {
        const task = fakeTask('to_pc', settings.explorer_dest ?? '');
        tasks.push(task);
        return { task: task.id };
      }
      case 'explorer_tasks':
        return { tasks: [...tasks] };
      case 'watch_devices':
      case 'stop':
      case 'reopen_screen':
      case 'skip_site':
      case 'open_site':
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

  // Nagrany podgląd planu nie zna poprawek: dopisuje plany `fix` (jeden na przeglądarkę), jak prawdziwy planista.
  const withFixRows = (plan: PlanView, fixes: unknown): PlanView => {
    const wanted = Array.isArray(fixes) ? (fixes as string[]) : [];
    if (!wanted.length) return plan;
    const labels = new Map<string, string>();
    const names = new Map<string, string>();
    for (const b of (checks ?? lastScan?.device_checks ?? []).flatMap((c) => c.browsers)) {
      names.set(b.package, b.name);
      if (b.all_fix && b.all_fix_label) labels.set(b.all_fix, b.all_fix_label);
      for (const s of b.sites) if (s.fix && s.fix_label) labels.set(s.fix, s.fix_label);
    }
    const byPackage = new Map<string, string[]>();
    for (const fix of [...wanted].sort()) {
      const pkg = fix.split(':')[1];
      byPackage.set(pkg, [...(byPackage.get(pkg) ?? []), labels.get(fix) ?? fix]);
    }
    const rows = [...byPackage].map(([pkg, steps]) => ({ package: pkg, name: names.get(pkg) ?? pkg, level: 'fix' as const,
      level_label: 'Ustawienia witryn', blocked: false, reason: null, reason_text: null, steps, warnings: [] }));
    return { ...plan, apps: [...plan.apps, ...rows], runnable: plan.runnable + rows.length, code: `${plan.code}F` };
  };

  // Eksplorator: odczyty zależą od ścieżki — nagranie tej samej ścieżki, a folder bez nagrania składany
  // z nagranych list (podfoldery z dłuższych ścieżek), żeby dało się chodzić po drzewie.
  const BY_PATH = new Set(['explorer_list', 'explorer_meta', 'explorer_text', 'explorer_sheet', 'explorer_sheet_head']);
  const recordedLists = () => data.calls.filter((c) => c.method === 'explorer_list' && !isError(c.result))
    .map((c) => c.result as ExplorerListView);
  const fakeListing = (path: string): ExplorerListView | ApiError => {
    const lists = recordedLists();
    if (!lists.length) return { error: { key: 'explorer_missing', message: '' } };
    const root = lists[0].crumbs[0];
    const known = new Map(lists.flatMap((l) => l.entries).map((e) => [e.path, e]));
    const prefix = path === root.path ? `${root.path}/` : `${path}/`;
    const children = new Map<string, EntryView>();
    for (const p of [...known.keys(), ...lists.map((l) => l.path)]) {
      if (!p.startsWith(prefix)) continue;
      const name = p.slice(prefix.length).split('/')[0];
      const child = prefix + name;
      if (!children.has(child)) {
        children.set(child, known.get(child) ?? { name, path: child, kind: 'dir', size: 4096, mtime: 1790413200,
          label: null, locked: false, type: 'other', ext: '', thumb: null, url: null });
      }
    }
    const parts = path.slice(root.path.length).split('/').filter(Boolean);
    const crumbs = [root, ...parts.map((part, i) => ({ label: part, path: `${root.path}/${parts.slice(0, i + 1).join('/')}` }))];
    return { path, crumbs, entries: [...children.values()], skipped: 0, locked: false };
  };

  // Podgląd: nagrany jest jeden plik z GPS (`IMG_20260926_0000.jpg`) i jeden tekst w cp1250; reszta składana tak,
  // żeby podgląd działał na każdym pliku. Tekst oddaje się dwoma kawałkami („Pokaż więcej”).
  const fakeMeta = (path: string) => {
    const known = recordedLists().flatMap((l) => l.entries).find((e) => e.path === path);
    return { meta: { gps: null, width: 64, height: 48, size: known?.size ?? 0, mtime: known?.mtime ?? 0, path } };
  };
  const fakeText = (path: string, more: boolean) => {
    const hit = data.calls.find((c) => c.method === 'explorer_text' && c.args[0] === path)?.result as
      { text: string; encoding: string } | undefined;
    const encoding = hit?.encoding ?? 'utf-8';
    if (more) return { text: '\nDalszy ciąg pliku — drugi kawałek.', encoding, truncated: false };
    return { text: hit?.text ?? 'Przykładowy tekst pliku.', encoding, truncated: true };
  };

  // Arkusz bez nagrania: dwa arkusze z polskimi znakami i sto wierszy (przewijanie, szukanie między arkuszami).
  const fakeSheet = () => ({
    sheets: [
      { name: 'Faktury', truncated: false, hidden: false, rows: [['Nr', 'Klient', 'Kwota', 'Data'],
        ...Array.from({ length: 100 }, (_, i) => [`F/${i + 1}`, i % 3 ? 'Gdańsk' : 'Łódź', String((i + 1) * 12.5), '2026-09-01'])] },
      { name: 'Notatki', truncated: false, hidden: false, rows: [['Klient z Łodzi płaci przelewem']] },
    ],
    delimiter: null, encoding: null,
  });

  const invoke = (method: string, args: unknown[]): unknown => {
    calls.push({ method, args });
    const failure = failures.get(method);
    if (failure) {
      failures.delete(method);
      return { error: { ...failure } };
    }
    if (answers.has(method)) {
      const result = answers.get(method);
      answers.delete(method);
      return structuredClone(result);
    }
    if (method === 'explorer_text') return fakeText(String(args[0]), args[1] === true);
    if (method === 'explorer_text_head') {
      const { text } = fakeText(String(args[0]), false);
      return { text, truncated: false };
    }
    if (BY_PATH.has(method)) {
      const hit = data.calls.find((c) => c.method === method && c.args[0] === args[0]);
      if (hit) {
        replay(hit.events);
        return structuredClone(hit.result);
      }
      if (method === 'explorer_list' && queues.has(method)) return fakeListing(String(args[0]));
      if (method === 'explorer_meta') return fakeMeta(String(args[0]));
      if (method === 'explorer_sheet') return fakeSheet();
      if (method === 'explorer_sheet_head') {
        const { sheets } = fakeSheet();
        return { names: sheets.map((s) => s.name), rows: sheets[0].rows.slice(0, 30), truncated: true };
      }
    }
    const queue = queues.get(method);
    if (!queue || queue.length === 0) return fallback(method, args);
    const call = queue.length > 1 ? queue.shift()! : queue[0];
    // Zlecenie wykonuje ten sam plan co podgląd: z poprawkami (bez ich kroków — tych nagranie nie ma).
    replay(method !== 'execute' ? call.events : call.events.map(([event, detail]) => (event === 'exec:order'
      ? [event, { ...(detail as object), plan: withFixRows(structuredClone((detail as { plan: PlanView }).plan), args[3]) }]
      : [event, detail]) as [string, unknown]));
    if (method === 'preview_plan') {
      const plan = withFixRows(structuredClone(call.result) as PlanView, args[2]);
      planCode = plan.code ?? planCode;
      return plan;
    }
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
    failNext: (method, key, message = '') => { failures.set(method, { key, message }); },
    answerNext: (method, result) => { answers.set(method, result); },
    setChecks: (next) => { checks = structuredClone(next); checksChanged = true; },
    setCopies: (next) => { copies = structuredClone(next); },
    dispose,
  };
}
