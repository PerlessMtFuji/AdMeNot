import { env, exports } from "cloudflare:workers";
import { beforeEach, describe, expect, it } from "vitest";
import worker from "../src/index";
import { TELEMETRY_IP_DAILY_BYTES } from "../src/telemetry";

const BASE = "https://admenot.test";
const ID = "3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const DEVICE = { manufacturer: "OPPO", model: "CPH2483", android: "14" };

function common(type: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { install: ID, type, t: "2026-10-10T14:00:00Z", app: "0.9.3", os: "Windows 10.0.26100", lang: "pl", ...extra };
}
const scan = (extra: Record<string, unknown> = {}) => common("scan", {
  device: DEVICE, session: "ab12cd34", apps: 187, verdicts: { malicious: 1, suspicious: 0, review: 1 },
  low_behavior_data: false, apk: { requested: 2, analyzed: 2, failed: 0 }, seconds: 41, apk_stage: false,
  packages: [{ package: "com.clean.pro.boost", verdict: "malicious", score: 82, confidence: "high", system: false }],
  ...extra,
});
const repair = () => common("repair", {
  device: DEVICE, session: "ab12cd34", levels: { silence: 0, disable: 1, remove: 1 }, sources: { flagged: 1, manual: 1 },
  failed: 0, errors: [], interrupted: null,
  packages: [{ package: "com.clean.pro.boost", source: "flagged", level: "remove", ok: true }],
});
const blindRepair = () => common("repair", {
  device: DEVICE, session: "ab12cd34", levels: { silence: 0, disable: 0, remove: 1 },
  sources: { flagged: 0, manual: 0, blind: 1 }, failed: 0, errors: [], interrupted: null,
  packages: [{ package: "com.a", source: "blind", level: "remove", ok: true }],
});
const undo = () => common("undo", { device: DEVICE, apps: 1, failed: 0, age_days: 2, packages: null });
const start = () => common("start", { mode: "simple" });
const CATEGORIES = { contacts: true, sms: true, mms: false, calls: true, media: true, downloads: false,
  whatsapp: true, others: false, apps: true };
const transfer = (extra: Record<string, unknown> = {}) => common("transfer_backup", {
  device: DEVICE, status: "complete", seconds: 2710, bytes_mb: 38400, files: 5230, files_failed: 0,
  apps: 12, apps_failed: 0, categories: CATEGORIES, ...extra,
});
const GROUPS = { photos: true, videos: true, downloads: false, whatsapp: true, others: false };
const restore = (extra: Record<string, unknown> = {}) => common("transfer_restore", {
  device: DEVICE, status: "complete", seconds: 1800, bytes_mb: 31000, files: 5100, exists: 120, renamed: 3,
  denied: 0, failed: 0, unselected: 40, missing: 0, apk_skipped: 1, apk_suspicious_skipped: 1, streams: 4,
  hashed: false, media_scan: "done", groups: GROUPS, ...extra,
});

const explorer = (extra: Record<string, unknown> = {}) => common("explorer", {
  device: DEVICE, seconds: 612, copied_files: 148, copied_mb: 1920, uploaded_files: 6, uploaded_mb: 41,
  previews: { image: 23, video: 2, audio: 1, text: 1 }, created: { folder: 1, text: 0 },
  errors: { explorer_denied: 1 }, mb_s: 31, ...extra,
});

async function post(events: unknown[], raw?: string): Promise<Response> {
  return exports.default.fetch(new Request(BASE + "/api/v1/telemetry", {
    method: "POST", headers: { "Content-Type": "application/json", "CF-Connecting-IP": crypto.randomUUID() },
    body: raw ?? JSON.stringify({ format: 1, events }),
  }));
}
async function rows(): Promise<{ install: string; type: string; body: string }[]> {
  return (await env.DB.prepare("SELECT install, type, body FROM events ORDER BY rowid").all()).results as never;
}

beforeEach(async () => {
  await env.DB.prepare("DELETE FROM events").run();
});

describe("POST /api/v1/telemetry", () => {
  it("przyjmuje tryb, szacunek i źródło blind", async () => {
    const withMode = scan({ apk_mode: "manual", eta: { kind: "rough", seconds: 600 } });
    expect((await post([withMode, blindRepair()])).status).toBe(200);
  });

  it("starsze zdarzenia bez nowych pól nadal przechodzą", async () => {
    expect((await post([scan(), repair()])).status).toBe(200);
  });

  it("zapisuje stan sprawdzeń i liczby witryn oraz napraw; brak pól → null", async () => {
    const withChecks = scan({ checks: { site_notifications: "review" }, sites: { per_site: 2, shared: 1, rdp: 0 } });
    const withFixes = { ...repair(), fixes: { channel: 1, site_permission: 2 } };
    expect((await post([withChecks, withFixes, scan(), repair()])).status).toBe(200);
    const [s, r, oldScan, oldRepair] = (await rows()).map((x) => JSON.parse(x.body));
    expect(s.checks).toEqual({ site_notifications: "review" });
    expect(s.sites).toEqual({ per_site: 2, shared: 1, rdp: 0 });
    expect(r.fixes).toEqual({ channel: 1, site_permission: 2 });
    expect([oldScan.checks, oldScan.sites, oldRepair.fixes]).toEqual([null, null, null]);
  });

  it.each([
    ["nieznany stan", scan({ checks: { site_notifications: "fix" } })],
    ["dodatkowy klucz w checks", scan({ checks: { site_notifications: "ok", other: "ok" } })],
    ["pusty checks", scan({ checks: {} })],
    ["domena w sites", scan({ sites: { per_site: 1, shared: 0, rdp: 0, "example.com": 1 } })],
    ["napis zamiast liczby w sites", scan({ sites: { per_site: "example.com", shared: 0, rdp: 0 } })],
    ["brak klucza w sites", scan({ sites: { per_site: 1, shared: 0 } })],
    ["dodatkowy klucz w fixes", { ...repair(), fixes: { channel: 1, site_permission: 0, "com.android.chrome": 1 } }],
    ["napis w fixes", { ...repair(), fixes: { channel: "x", site_permission: 0 } }],
    ["ujemna liczba w fixes", { ...repair(), fixes: { channel: -1, site_permission: 0 } }],
  ])("400: %s", async (_name, event) => {
    expect((await post([event])).status).toBe(400);
    expect(await rows()).toEqual([]);
  });

  it("odrzuca nieznany tryb i zły szacunek", async () => {
    expect((await post([scan({ apk_mode: "fast" })])).status).toBe(400);
    expect((await post([scan({ eta: { kind: "exact", seconds: 1 } })])).status).toBe(400);
  });

  it("one address cannot exceed its daily share, whatever install IDs it claims", async () => {
    const ip = "198.51.100.7";
    const big = () => ({ ...scan({ packages: Array.from({ length: 200 }, (_, i) => ({
      package: `com.example.app${i}`, verdict: "review", score: 25, confidence: "low", system: false })) }),
      install: crypto.randomUUID() });
    const send = (from: string) => exports.default.fetch(new Request(BASE + "/api/v1/telemetry", {
      method: "POST", headers: { "Content-Type": "application/json", "CF-Connecting-IP": from },
      body: JSON.stringify({ format: 1, events: [big()] }),
    }));
    let res = await send(ip);
    let sent = 1;
    while (res.status === 200 && sent < 10) {
      res = await send(ip);
      sent += 1;
    }
    expect(sent).toBeGreaterThan(1);
    expect(res.status).toBe(429);
    expect(await res.json()).toEqual({ error: "budget" });
    expect(Number(res.headers.get("Retry-After"))).toBeGreaterThan(0);
    const stored = (await rows()).reduce((n, r) => n + new TextEncoder().encode(r.body).byteLength, 0);
    expect(stored).toBeLessThanOrEqual(TELEMETRY_IP_DAILY_BYTES);
    expect((await send("198.51.100.8")).status).toBe(200);
  });

  it("zapisuje wszystkie typy zdarzeń", async () => {
    const res = await post([start(), scan(), repair(), undo()]);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true, stored: 4 });
    expect((await rows()).map((r) => r.type)).toEqual(["start", "scan", "repair", "undo"]);
  });

  it("transfer_backup: przyjęte i zapisane same liczby oraz flagi", async () => {
    const res = await post([transfer(), transfer({ status: "stopped", bytes_mb: 600_000 })]);
    expect(res.status).toBe(200);
    const [first, second] = (await rows()).map((r) => JSON.parse(r.body));
    expect(first).toMatchObject({ type: "transfer_backup", status: "complete", files: 5230, categories: CATEGORIES });
    expect(second).toMatchObject({ status: "stopped", bytes_mb: 600_000 });
  });

  it.each([
    ["dodatkowe pole path", transfer({ path: "DCIM/Camera" })],
    ["nieznany status", transfer({ status: "x" })],
    ["nazwa folderu w categories", transfer({ categories: { ...CATEGORIES, Music: true } })],
    ["liczba zamiast flagi", transfer({ categories: { ...CATEGORIES, sms: 1 } })],
    ["brak flagi", transfer({ categories: { contacts: true } })],
    ["ujemna liczba plików", transfer({ files: -1 })],
    ["seconds ponad dobę", transfer({ seconds: 86_401 })],
    ["bytes_mb ponad limit", transfer({ bytes_mb: 10_000_001 })],
    ["brak urządzenia", transfer({ device: undefined })],
  ])("transfer_backup 400: %s", async (_name, event) => {
    expect((await post([event])).status).toBe(400);
    expect(await rows()).toEqual([]);
  });

  it("transfer_restore: przyjęte i zapisane same liczby oraz flagi grup", async () => {
    const res = await post([restore(), restore({ status: "stopped", media_scan: "skipped", streams: 1, hashed: true })]);
    expect(res.status).toBe(200);
    const [first, second] = (await rows()).map((r) => JSON.parse(r.body));
    expect(first).toMatchObject({ type: "transfer_restore", status: "complete", files: 5100, exists: 120,
      missing: 0, streams: 4, media_scan: "done", groups: GROUPS });
    expect(second).toMatchObject({ status: "stopped", media_scan: "skipped", streams: 1, hashed: true });
  });

  it.each([
    ["dodatkowe pole path", restore({ path: "DCIM/Camera" })],
    ["nieznany media_scan", restore({ media_scan: "x" })],
    ["streams ponad 8", restore({ streams: 99 })],
    ["streams 0", restore({ streams: 0 })],
    ["nieznany status", restore({ status: "phone_full" })],
    ["nazwa folderu w groups", restore({ groups: { ...GROUPS, "other:Music": true } })],
    ["brak grupy", restore({ groups: { photos: true } })],
    ["liczba zamiast flagi", restore({ groups: { ...GROUPS, photos: 1 } })],
    ["hashed nie logiczne", restore({ hashed: "no" })],
    ["ujemna liczba", restore({ denied: -1 })],
    ["brak missing", restore({ missing: undefined })],
    ["seconds ponad dobę", restore({ seconds: 86_401 })],
    ["bytes_mb ponad limit", restore({ bytes_mb: 10_000_001 })],
    ["brak urządzenia", restore({ device: undefined })],
  ])("transfer_restore 400: %s", async (_name, event) => {
    expect((await post([event])).status).toBe(400);
    expect(await rows()).toEqual([]);
  });

  const TEL_KIND = { written: 410, existed: 2, skipped: 30, failed: 0, manual: 0, path: "app_process",
    visible_warning: false };
  const TEL = { contacts: TEL_KIND, sms: { ...TEL_KIND, path: "companion", visible_warning: true },
    mms: { ...TEL_KIND, path: "file", manual: 3 }, calls: { ...TEL_KIND, path: "none", written: 0 } };
  const withTel = (tel: Record<string, unknown> = TEL, extra: Record<string, unknown> = {}) => restore({
    tel, safety: { contacts: true, sms: true, mms: false, calls: true }, cleanup_ok: true, ...extra });

  it("transfer_restore z telefonią: przyjęte i zapisane same liczby", async () => {
    const res = await post([withTel(), withTel({ sms: TEL.sms }, { safety: { sms: false }, cleanup_ok: false })]);
    expect(res.status).toBe(200);
    const [first, second] = (await rows()).map((r) => JSON.parse(r.body));
    expect(first).toMatchObject({ type: "transfer_restore", tel: TEL, cleanup_ok: true,
      safety: { contacts: true, sms: true, mms: false, calls: true } });
    expect(second).toMatchObject({ tel: { sms: TEL.sms }, safety: { sms: false }, cleanup_ok: false });
    expect(Object.keys(second.tel)).toEqual(["sms"]);
  });

  it("transfer_restore bez telefonii (same pliki) nadal przechodzi", async () => {
    expect((await post([restore()])).status).toBe(200);
    const body = JSON.parse((await rows())[0].body);
    expect(body.tel).toBeUndefined();
    expect(body.cleanup_ok).toBeUndefined();
  });

  it.each([
    ["nieznana droga", withTel({ ...TEL, sms: { ...TEL.sms, path: "x" } })],
    ["dodatkowe pole account", withTel({ ...TEL, contacts: { ...TEL_KIND, account: "jan@gmail.com" } })],
    ["kategoria rcs", withTel({ ...TEL, rcs: TEL_KIND })],
    ["brak pola w kategorii", withTel({ ...TEL, calls: { ...TEL_KIND, manual: undefined } })],
    ["ujemna liczba", withTel({ ...TEL, sms: { ...TEL.sms, failed: -1 } })],
    ["liczba ponad limit", withTel({ ...TEL, sms: { ...TEL.sms, written: 100_001 } })],
    ["visible_warning nie logiczne", withTel({ ...TEL, sms: { ...TEL.sms, visible_warning: 1 } })],
    ["safety z kategorią rcs", withTel(TEL, { safety: { rcs: true } })],
    ["safety nie logiczne", withTel(TEL, { safety: { sms: "yes" } })],
    ["cleanup_ok nie logiczne", withTel(TEL, { cleanup_ok: "ok" })],
    ["tel nie obiekt", withTel([] as never)],
    ["dodatkowe pole accounts", withTel(TEL, { accounts: ["jan@gmail.com"] })],
  ])("transfer_restore z telefonią 400: %s", async (_name, event) => {
    expect((await post([event])).status).toBe(400);
    expect(await rows()).toEqual([]);
  });

  it("undo: liczby witryn opcjonalne, domyślnie 0", async () => {
    await post([undo()]);
    expect(JSON.parse((await rows())[0].body)).toMatchObject({ sites: 0, sites_restored: 0 });
  });

  it("undo: liczby witryn przepisane", async () => {
    await post([{ ...undo(), sites: 3, sites_restored: 2 }]);
    expect(JSON.parse((await rows())[0].body)).toMatchObject({ sites: 3, sites_restored: 2 });
  });

  it("undo: sites nie będące liczbą odrzucone", async () => {
    expect((await post([{ ...undo(), sites: "x" }])).status).toBe(400);
  });

  it("zapisuje tylko znane pola", async () => {
    await post([scan({ serial: "R58T00TEST", extra: 1 })]);
    const body = JSON.parse((await rows())[0].body);
    expect(body.serial).toBeUndefined();
    expect(body.extra).toBeUndefined();
    expect(body.device).toEqual(DEVICE);
  });

  it.each([
    ["zły UUID", scan({ install: "x" })],
    ["UUID wielkimi literami", scan({ install: ID.toUpperCase() })],
    ["nieznany typ", common("boot")],
    ["zły format t", scan({ t: "2026-10-10 14:00" })],
    ["t sprzed 2026", scan({ t: "2025-12-31T23:00:00Z" })],
    ["zła nazwa pakietu", scan({ packages: [{ package: "a b", verdict: "review", score: 1, confidence: "low", system: false }] })],
    ["zły werdykt", scan({ packages: [{ package: "a.b", verdict: "safe", score: 1, confidence: "low", system: false }] })],
    ["ujemna liczba", scan({ apps: -1 })],
    ["urządzenie z numerem seryjnym", scan({ device: { ...DEVICE, serial: "R58" } })],
  ])("400: %s", async (_name, event) => {
    expect((await post([event])).status).toBe(400);
    expect(await rows()).toEqual([]);
  });

  it("t z odległej przyszłości jest przyjęty (zły zegar u użytkownika)", async () => {
    expect((await post([scan({ t: "2031-01-01T00:00:00Z" })])).status).toBe(200);
  });

  it("400: pusta paczka, ponad 100 zdarzeń, zły format, nie-JSON", async () => {
    expect((await post([])).status).toBe(400);
    expect((await post(Array.from({ length: 101 }, start))).status).toBe(400);
    expect((await post([], JSON.stringify({ format: 2, events: [start()] }))).status).toBe(400);
    expect((await post([], "{")).status).toBe(400);
  });

  it("413 dla treści ponad 256 KB", async () => {
    expect((await post([], "x".repeat(256 * 1024 + 1))).status).toBe(413);
  });

  it("429 po przekroczeniu dziennego limitu bajtów", async () => {
    const big = "x".repeat(150 * 1024);
    await env.DB.prepare("INSERT INTO events (install, created, t, type, app, body) VALUES (?, datetime('now'), ?, 'scan', '0.9.3', ?)")
      .bind(ID, "2026-10-10T14:00:00Z", big).run();
    expect((await post([scan(), scan(), scan()].map((e) => ({ ...e, packages: Array.from({ length: 200 }, (_, i) => ({ package: `com.app.n${i}`, verdict: "review", score: 30, confidence: "low", system: false })) })))).status).toBe(429);
    expect(await rows()).toHaveLength(1);
  });
});

describe("ochrona budżetu (audyt 2026-10-11, SEC-03, BUG-12)", () => {
  const OTHER = "11111111-2222-4333-8444-555555555555";
  const fill = (install: string, body: string) => env.DB.prepare(
    "INSERT INTO events (install, created, t, type, app, body) VALUES (?, datetime('now'), 't', 'scan', 'a', ?)",
  ).bind(install, body).run();

  it("429 z limitera przed czytaniem treści i przed D1 — także DELETE", async () => {
    const limitedEnv = { ...env, TELEMETRY_LIMITER: { limit: async () => ({ success: false }) } } as unknown as Env;
    const res = await worker.fetch(new Request(BASE + "/api/v1/telemetry", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ format: 1, events: [start()] }),
    }), limitedEnv);
    expect(res.status).toBe(429);
    expect(await res.json()).toEqual({ error: "rate_limited" });
    const del = await worker.fetch(new Request(`${BASE}/api/v1/telemetry/${ID}`, { method: "DELETE" }), limitedEnv);
    expect(del.status).toBe(429);
    expect(await rows()).toHaveLength(0);
  });

  it("jedna instalacja nie zajmie całego budżetu doby", async () => {
    await fill(ID, "x".repeat(100 * 1024 - 100));
    expect((await post([scan()])).status).toBe(429);
    expect((await post([{ ...scan(), install: OTHER }])).status).toBe(200);
  });

  it("limit liczy bajty UTF-8, nie znaki", async () => {
    await fill(OTHER, "€".repeat(68 * 1024)); // 68 Ki znaków = 204 KB
    expect((await post([start()])).status).toBe(429);
  });

  it("paczka z różnymi instalacjami jest odrzucona", async () => {
    expect((await post([start(), { ...start(), install: OTHER }])).status).toBe(400);
  });

  it("równoległe żądania na ostatnim wolnym miejscu nie przekraczają budżetu", async () => {
    const event = scan({ packages: Array.from({ length: 150 }, (_, i) => ({ package: `com.app.n${i}`, verdict: "review", score: 30, confidence: "low", system: false })) });
    const size = new TextEncoder().encode(JSON.stringify({ ...event })).byteLength;
    await fill(OTHER, "x".repeat(200 * 1024 - Math.floor(size * 1.5)));
    const results = await Promise.all([post([event]), post([{ ...event, install: "22222222-3333-4444-8555-666666666666" }])]);
    expect(results.map((r) => r.status).sort()).toEqual([200, 429]);
    const total = await env.DB.prepare("SELECT SUM(length(CAST(body AS BLOB))) AS n FROM events").first<{ n: number }>();
    expect(total!.n).toBeLessThanOrEqual(200 * 1024);
  });
});

describe("DELETE /api/v1/telemetry/{install}", () => {
  it("usuwa wiersze instalacji", async () => {
    await post([start(), scan()]);
    await post([{ ...start(), install: "11111111-2222-4333-8444-555555555555" }]);
    const res = await exports.default.fetch(new Request(`${BASE}/api/v1/telemetry/${ID}`, { method: "DELETE" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ deleted: 2 });
    expect((await rows()).map((r) => r.install)).toEqual(["11111111-2222-4333-8444-555555555555"]);
  });

  it("400 dla złego ID, 200 z zerem dla nieznanego", async () => {
    expect((await exports.default.fetch(new Request(`${BASE}/api/v1/telemetry/abc`, { method: "DELETE" }))).status).toBe(400);
    const res = await exports.default.fetch(new Request(`${BASE}/api/v1/telemetry/${ID}`, { method: "DELETE" }));
    expect(await res.json()).toEqual({ deleted: 0 });
  });
});

describe("retencja", () => {
  it("cron usuwa zdarzenia starsze niż 13 miesięcy", async () => {
    await env.DB.prepare("INSERT INTO events (install, created, t, type, app, body) VALUES (?, datetime('now', '-14 months'), 't', 'start', 'a', '{}'), (?, datetime('now', '-12 months'), 't', 'start', 'a', '{}')")
      .bind(ID, ID).run();
    await worker.scheduled!({ cron: "17 3 * * *", scheduledTime: Date.now(), noRetry() {} } as ScheduledController,
      env, {} as ExecutionContext);
    expect(await rows()).toHaveLength(1);
  });
});

describe("POST /api/v1/telemetry: explorer", () => {
  it("przyjmuje zdarzenie i zapisuje same liczby", async () => {
    expect((await post([explorer(), explorer({ errors: {}, mb_s: null })])).status).toBe(200);
    const [first, second] = (await rows()).map((r) => JSON.parse(r.body));
    expect(first).toMatchObject({ type: "explorer", copied_files: 148, copied_mb: 1920, mb_s: 31,
      previews: { image: 23, video: 2, audio: 1, text: 1 }, created: { folder: 1, text: 0 },
      errors: { explorer_denied: 1 } });
    expect(second).toMatchObject({ errors: {}, mb_s: null });
  });

  it.each([
    ["tekst ze znakiem / w errors", explorer({ errors: { "DCIM/Camera": 1 } })],
    ["tekst ze znakiem / w wartości", explorer({ errors: { explorer_denied: "a/b" } })],
    ["klucz błędu z kropką (nazwa pliku)", explorer({ errors: { "IMG_1.jpg": 1 } })],
    ["wielkie litery w kluczu błędu", explorer({ errors: { Explorer: 1 } })],
    ["zbyt długi klucz błędu", explorer({ errors: { ["a".repeat(65)]: 1 } })],
    ["ułamek w errors", explorer({ errors: { explorer_denied: 1.5 } })],
    ["ponad 20 kluczy błędów", explorer({ errors: Object.fromEntries(Array.from({ length: 21 }, (_, i) => [`e_${i}`, 1])) })],
    ["nieznane pole", explorer({ path: "DCIM" })],
    ["pole tekstowe z /", explorer({ mb_s: "a/b" })],
    ["nieznany klucz previews", explorer({ previews: { image: 1, video: 0, audio: 0, text: 0, pdf: 1 } })],
    ["brak klucza created", explorer({ created: { folder: 1 } })],
    ["ujemna liczba", explorer({ copied_files: -1 })],
    ["seconds ponad dobę", explorer({ seconds: 86_401 })],
    ["copied_mb ponad limit", explorer({ copied_mb: 10_000_001 })],
    ["brak urządzenia", explorer({ device: undefined })],
    ["mb_s ujemne", explorer({ mb_s: -1 })],
  ])("400: %s", async (_name, event) => {
    expect((await post([event])).status).toBe(400);
    expect(await rows()).toEqual([]);
  });
});
