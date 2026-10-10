import { env, exports } from "cloudflare:workers";
import { beforeEach, describe, expect, it } from "vitest";
import worker from "../src/index";

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
const undo = () => common("undo", { device: DEVICE, apps: 1, failed: 0, age_days: 2, packages: null });
const start = () => common("start", { mode: "simple" });

async function post(events: unknown[], raw?: string): Promise<Response> {
  return exports.default.fetch(new Request(BASE + "/api/v1/telemetry", {
    method: "POST", headers: { "Content-Type": "application/json" },
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
  it("zapisuje wszystkie typy zdarzeń", async () => {
    const res = await post([start(), scan(), repair(), undo()]);
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true, stored: 4 });
    expect((await rows()).map((r) => r.type)).toEqual(["start", "scan", "repair", "undo"]);
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
