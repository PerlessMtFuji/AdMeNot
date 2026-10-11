import { env, exports } from "cloudflare:workers";
import { beforeEach, describe, expect, it } from "vitest";
import worker, { SHARE_MAX_BODY, SHARES_IP_DAILY, SHARES_LIVE_CAP } from "../src/index";

const BASE = "https://admenot.test";
const ID = /^[A-Za-z0-9_-]{22}$/;
const blob = (size = 64, first = 1) => { const b = new Uint8Array(size).fill(7); b[0] = first; return b; };
const open = (over: Record<string, unknown> = {}) => ({
  ...env,
  SHARES_LIMITER: { limit: async () => ({ success: true }) },
  SHARES_READ_LIMITER: { limit: async () => ({ success: true }) },
  ...over,
}) as unknown as Env;

function post(body: BodyInit, headers: Record<string, string> = {}, e?: Env): Promise<Response> {
  const req = new Request<unknown, IncomingRequestCfProperties>(BASE + "/api/v1/shares", {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream", "CF-Connecting-IP": crypto.randomUUID(), ...headers },
    body,
  });
  return e ? worker.fetch(req, e) : exports.default.fetch(req);
}

const get = (id: string, e?: Env) => {
  const req = new Request<unknown, IncomingRequestCfProperties>(`${BASE}/api/v1/shares/${id}`, { headers: { "CF-Connecting-IP": crypto.randomUUID() } });
  return e ? worker.fetch(req, e) : exports.default.fetch(req);
};

beforeEach(async () => {
  await env.DB.exec("DELETE FROM shares");
});

describe("POST /api/v1/shares", () => {
  it("zapisuje blob i oddaje go bajt w bajt", async () => {
    const sent = blob(1000);
    const res = await post(sent);
    expect(res.status).toBe(201);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    const { id, expires } = await res.json<{ id: string; expires: string }>();
    expect(id).toMatch(ID);
    const minutes = (Date.parse(expires) - Date.now()) / 60000;
    expect(minutes).toBeGreaterThan(58);
    expect(minutes).toBeLessThan(61);
    const back = await get(id);
    expect(back.status).toBe(200);
    expect(back.headers.get("Content-Type")).toBe("application/octet-stream");
    expect(back.headers.get("Cache-Control")).toBe("no-store");
    expect(new Uint8Array(await back.arrayBuffer())).toEqual(sent);
  });

  it.each([
    ["zły typ treści", () => post(blob(), { "Content-Type": "application/json" })],
    ["zła wersja", () => post(blob(64, 2))],
    ["za krótki", () => post(blob(20))],
  ])("400: %s", async (_name, send) => {
    const res = await send();
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "invalid" });
  });

  it("413 powyżej limitu", async () => {
    const res = await post(blob(SHARE_MAX_BODY + 1));
    expect(res.status).toBe(413);
  });

  it("429 z limitera", async () => {
    const res = await post(blob(), {}, open({ SHARES_LIMITER: { limit: async () => ({ success: false }) } }));
    expect(res.status).toBe(429);
    expect(await res.json()).toEqual({ error: "rate_limited" });
  });

  it("jeden adres zapisze najwyżej SHARES_IP_DAILY planów na dobę", async () => {
    const e = open();
    const ip = { "CF-Connecting-IP": "198.51.100.77" };
    for (let i = 0; i < SHARES_IP_DAILY; i++) expect((await post(blob(), ip, e)).status).toBe(201);
    const res = await post(blob(), ip, e);
    expect(res.status).toBe(429);
    expect(await res.json()).toEqual({ error: "budget" });
  }, 30_000); // 300 kolejnych zapisów nie mieści się w domyślnych 5 s

  it("503 po osiągnięciu sufitu aktywnych planów", async () => {
    const stmt = env.DB.prepare(
      "INSERT INTO shares (id, created, expires, body) VALUES (?, datetime('now'), datetime('now', '+30 minutes'), 'AQ==')");
    await env.DB.batch(Array.from({ length: SHARES_LIVE_CAP }, (_, i) => stmt.bind(`T-${i}`)));
    const res = await post(blob());
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "busy" });
  });

  it("zapis kasuje wygasłe plany (także gdy sufit był pełny wygasłymi)", async () => {
    const stmt = env.DB.prepare(
      "INSERT INTO shares (id, created, expires, body) VALUES (?, datetime('now', '-2 hours'), datetime('now', '-1 hours'), 'AQ==')");
    await env.DB.batch(Array.from({ length: SHARES_LIVE_CAP }, (_, i) => stmt.bind(`OLD-${i}`)));
    expect((await post(blob())).status).toBe(201);
    const { n } = (await env.DB.prepare("SELECT COUNT(*) AS n FROM shares").first<{ n: number }>())!;
    expect(n).toBe(1);
  });
});

describe("GET /api/v1/shares/:id", () => {
  it("404 dla nieznanego, złego i wygasłego planu, bez rozróżnienia", async () => {
    const { id } = await (await post(blob())).json<{ id: string }>();
    await env.DB.prepare("UPDATE shares SET expires = datetime('now', '-1 minutes') WHERE id = ?").bind(id).run();
    for (const which of [id, "A".repeat(22), "../../etc"]) {
      const res = await get(which);
      expect(res.status).toBe(404);
      expect(await res.json()).toEqual({ error: "not_found" });
    }
  });

  it("429 z limitera odczytu", async () => {
    const res = await get("A".repeat(22), open({ SHARES_READ_LIMITER: { limit: async () => ({ success: false }) } }));
    expect(res.status).toBe(429);
  });

  it("cron kasuje wygasłe plany", async () => {
    const stmt = env.DB.prepare(
      "INSERT INTO shares (id, created, expires, body) VALUES (?, datetime('now'), datetime('now', ?), 'AQ==')");
    await env.DB.batch([stmt.bind("OLD", "-1 minutes"), stmt.bind("NEW", "+30 minutes")]);
    await worker.scheduled!({ cron: "17 3 * * *", scheduledTime: Date.now(), noRetry() {} } as ScheduledController,
      env, {} as ExecutionContext);
    const ids = await env.DB.prepare("SELECT id FROM shares").all<{ id: string }>();
    expect(ids.results.map((r) => r.id)).toEqual(["NEW"]);
  });
});
