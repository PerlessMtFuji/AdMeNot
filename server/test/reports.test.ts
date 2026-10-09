import { env, exports } from "cloudflare:workers";
import { beforeEach, describe, expect, it } from "vitest";
import worker from "../src/index";

const BASE = "https://admenot.test";
const ID = /^R-[0-9A-HJKMNP-TV-Z]{6}$/;

function report(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    format: 1, kind: "error", app: "0.9.3", os: "Windows 10.0.26100", lang: "pl", count: 1,
    created: "2026-10-09T14:03:12",
    context: { call: "plan_order", job: "exec", screen: null, device: { manufacturer: "OPPO", model: "CPH2483", android: "14" } },
    error: { type: "KeyError", message: "'x'", where: "plan.py:118 in plan_order", trace: "Traceback…" },
    log_tail: null, adb_tail: null, comment: "skan",
    ...overrides,
  };
}

function post(body: unknown, headers: Record<string, string> = {}): Promise<Response> {
  return exports.default.fetch(new Request(BASE + "/api/v1/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json", "CF-Connecting-IP": crypto.randomUUID(), ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  }));
}

beforeEach(async () => {
  await env.DB.exec("DELETE FROM reports");
});

describe("POST /api/v1/reports", () => {
  it("zapisuje raport i zwraca numer", async () => {
    const res = await post(report());
    expect(res.status).toBe(201);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    const { id } = await res.json<{ id: string }>();
    expect(id).toMatch(ID);
    const row = await env.DB.prepare("SELECT * FROM reports WHERE id = ?").bind(id).first<Record<string, unknown>>();
    expect(row).toMatchObject({ kind: "error", app: "0.9.3", error_type: "KeyError", seen: 0 });
    expect(JSON.parse(row!.body as string)).toEqual(report());
    expect(row!.created as string).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
  });

  it("raport z ADB i bez opisu", async () => {
    const res = await post(report({ adb_tail: ["14:00:00\tok\t0.1s\tshell:pm list packages"], comment: null }));
    expect(res.status).toBe(201);
  });

  it.each([
    ["zły JSON", "{nie"],
    ["tablica", []],
    ["format 2", report({ format: 2 })],
    ["nieznany rodzaj", report({ kind: "spam" })],
    ["pusty typ błędu", report({ error: { type: "", message: "", where: null, trace: null } })],
    ["za długi opis", report({ comment: "x".repeat(1001) })],
    ["za długi traceback", report({ error: { type: "E", message: "", where: null, trace: "t".repeat(16385) } })],
    ["za dużo wierszy ADB", report({ adb_tail: Array(51).fill("x") })],
    ["wiersz ADB nie-tekst", report({ adb_tail: [1] })],
    ["count 0", report({ count: 0 })],
    ["context nie obiekt", report({ context: "x" })],
  ])("400 dla: %s", async (_name, body) => {
    const res = await post(body);
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "invalid" });
  });

  it("emoji liczone jak w Pythonie (punkty kodowe)", async () => {
    expect((await post(report({ comment: "😀".repeat(1000) }))).status).toBe(201);
  });

  it("413 powyżej 64 KB", async () => {
    const res = await post(report({ log_tail: "x".repeat(70_000) }));
    expect(res.status).toBe(413);
    expect(await res.json()).toEqual({ error: "too_large" });
  });

  it("400 bez Content-Type JSON", async () => {
    const res = await post(report(), { "Content-Type": "text/plain" });
    expect(res.status).toBe(400);
  });

  it("429 z limitera", async () => {
    const limited = { ...env, REPORTS_LIMITER: { limit: async () => ({ success: false }) } } as unknown as Env;
    const res = await worker.fetch(new Request(BASE + "/api/v1/reports", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(report()),
    }), limited);
    expect(res.status).toBe(429);
    expect(await res.json()).toEqual({ error: "rate_limited" });
  });

  it("503 po przekroczeniu sufitu dziennego", async () => {
    const stmt = env.DB.prepare(
      "INSERT INTO reports (id, created, kind, app, os, lang, error_type, body) VALUES (?, datetime('now'), 'error', 'a', 'o', 'pl', 'E', '{}')");
    await env.DB.batch(Array.from({ length: 500 }, (_, i) => stmt.bind(`T-${i}`)));
    const res = await post(report());
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "busy" });
  });

  it("GET to 404", async () => {
    const res = await exports.default.fetch(new Request(BASE + "/api/v1/reports"));
    expect(res.status).toBe(404);
  });
});

describe("czyszczenie", () => {
  it("usuwa raporty starsze niż 90 dni", async () => {
    const stmt = env.DB.prepare(
      "INSERT INTO reports (id, created, kind, app, os, lang, error_type, body) VALUES (?, datetime('now', ?), 'error', 'a', 'o', 'pl', 'E', '{}')");
    await env.DB.batch([stmt.bind("OLD", "-91 days"), stmt.bind("NEW", "-89 days")]);
    await worker.scheduled!({ cron: "17 3 * * *", scheduledTime: Date.now(), noRetry() {} } as ScheduledController,
      env, {} as ExecutionContext);
    const ids = await env.DB.prepare("SELECT id FROM reports ORDER BY id").all<{ id: string }>();
    expect(ids.results.map((r) => r.id)).toEqual(["NEW"]);
  });
});
