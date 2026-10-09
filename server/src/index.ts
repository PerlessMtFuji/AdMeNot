// Worker AdMeNot: statyczna strona z public/ (bez kodu) + API pod /api/v1/ (spec backendu §2).
// Nie logujemy zapytań ani nagłówków — adresów IP nie zapisujemy nigdzie (§2.2).

const JSON_HEADERS = { "Content-Type": "application/json", "Cache-Control": "no-store" };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

async function health(env: Env): Promise<Response> {
  try {
    await env.DB.prepare("SELECT 1").first();
    return json({ ok: true, db: true });
  } catch {
    return json({ ok: false, db: false }, 503);
  }
}

// Raporty błędów (spec raportów błędów §6): tylko zapis; odczyt wyłącznie przez wranglera autora.
const MAX_BODY = 64 * 1024;
const DAILY_CAP = 100; // najgorszy przypadek ~100 × 45 KB × 90 dni ≈ 400 MB (D1 free: 500 MB)
const KINDS = new Set(["error", "ui", "thread", "exit"]);
const ID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const LIMITS = { short: 64, type: 200, where: 300, message: 1000, trace: 16384, log: 8192, adbLine: 300, adbLines: 50, comment: 1000, context: 2048 };

// Długość w punktach kodowych — tak liczy Python po stronie programu.
const len = (s: string): number => [...s].length;
const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown, max: number, required = false): boolean =>
  (v === null || v === undefined) ? !required : typeof v === "string" && (!required || v.length > 0) && len(v) <= max;

function validReport(b: unknown): b is Record<string, unknown> & { error: Record<string, unknown> } {
  if (!isObject(b) || b.format !== 1 || typeof b.kind !== "string" || !KINDS.has(b.kind)) return false;
  for (const key of ["app", "os", "lang", "created"]) if (!text(b[key], LIMITS.short, true)) return false;
  if (!Number.isInteger(b.count) || (b.count as number) < 1 || (b.count as number) > 100_000) return false;
  if (!isObject(b.context) || len(JSON.stringify(b.context)) > LIMITS.context) return false;
  const e = b.error;
  if (!isObject(e) || !text(e.type, LIMITS.type, true) || !text(e.message, LIMITS.message)
    || !text(e.where, LIMITS.where) || !text(e.trace, LIMITS.trace)) return false;
  if (!text(b.log_tail, LIMITS.log) || !text(b.comment, LIMITS.comment)) return false;
  if (b.adb_tail !== null && b.adb_tail !== undefined) {
    if (!Array.isArray(b.adb_tail) || b.adb_tail.length > LIMITS.adbLines) return false;
    if (!b.adb_tail.every((line) => typeof line === "string" && len(line) <= LIMITS.adbLine)) return false;
  }
  return true;
}

const DEVICE_KEYS = ["manufacturer", "model", "android"];
const CONTEXT_KEYS = ["call", "job", "screen"];

// Zapisujemy tylko znane pola: nieznane klucze nie obchodzą limitów (device: dokładnie 3 pola).
function normalize(b: Record<string, unknown> & { error: Record<string, unknown> }): Record<string, unknown> | null {
  const ctx = b.context as Record<string, unknown>;
  const context: Record<string, unknown> = {};
  for (const key of CONTEXT_KEYS) {
    if (!text(ctx[key], LIMITS.short)) return null;
    context[key] = ctx[key] ?? null;
  }
  let device: Record<string, unknown> | null = null;
  if (ctx.device !== null && ctx.device !== undefined) {
    const d = ctx.device;
    if (!isObject(d) || Object.keys(d).some((k) => !DEVICE_KEYS.includes(k))) return null;
    device = {};
    for (const key of DEVICE_KEYS) {
      if (!text(d[key], LIMITS.short)) return null;
      device[key] = d[key] ?? null;
    }
  }
  context.device = device;
  const e = b.error;
  return {
    format: b.format, kind: b.kind, app: b.app, os: b.os, lang: b.lang, count: b.count, created: b.created,
    context,
    error: { type: e.type, message: e.message ?? null, where: e.where ?? null, trace: e.trace ?? null },
    log_tail: b.log_tail ?? null, adb_tail: b.adb_tail ?? null, comment: b.comment ?? null,
  };
}

// Czyta treść strumieniowo i przerywa po przekroczeniu limitu; null = za duża.
async function readLimited(request: Request): Promise<string | null> {
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_BODY) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const all = new Uint8Array(total);
  let offset = 0;
  for (const c of chunks) {
    all.set(c, offset);
    offset += c.byteLength;
  }
  return new TextDecoder().decode(all);
}

function reportId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return "R-" + Array.from(bytes, (b) => ID_ALPHABET[b % 32]).join(""); // 256 % 32 == 0: bez skrzywienia
}

async function createReport(request: Request, env: Env): Promise<Response> {
  if (!(request.headers.get("Content-Type") ?? "").toLowerCase().startsWith("application/json")) return json({ error: "invalid" }, 400);
  // Limiter przed czytaniem treści, żeby także odpowiedzi 413 były limitowane.
  const { success } = await env.REPORTS_LIMITER.limit({ key: request.headers.get("CF-Connecting-IP") ?? "unknown" });
  if (!success) return json({ error: "rate_limited" }, 429);
  const declared = Number(request.headers.get("Content-Length") ?? "0");
  if (declared > MAX_BODY) return json({ error: "too_large" }, 413);
  const raw = await readLimited(request);
  if (raw === null) return json({ error: "too_large" }, 413);
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return json({ error: "invalid" }, 400);
  }
  if (!validReport(parsed)) return json({ error: "invalid" }, 400);
  const clean = normalize(parsed);
  if (!clean) return json({ error: "invalid" }, 400);
  const stored = JSON.stringify(clean);
  try {
    const recent = await env.DB.prepare("SELECT COUNT(*) AS n FROM reports WHERE created >= datetime('now', '-1 day')")
      .first<{ n: number }>();
    if ((recent?.n ?? 0) >= DAILY_CAP) return json({ error: "busy" }, 503);
    const insert = (id: string) => env.DB.prepare(
      "INSERT INTO reports (id, created, kind, app, os, lang, error_type, error_where, body) "
      + "VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?)",
    ).bind(id, parsed.kind, parsed.app, parsed.os, parsed.lang, parsed.error.type, parsed.error.where ?? null, stored).run();
    let id = reportId();
    try {
      await insert(id);
    } catch (err) {
      // Ponawiamy tylko przy kolizji klucza (1 na ~10^9); inny błąd D1 idzie do 503.
      if (!String((err as Error)?.message ?? err).includes("UNIQUE constraint failed")) throw err;
      id = reportId();
      await insert(id);
    }
    return json({ id }, 201);
  } catch {
    return json({ error: "busy" }, 503);
  }
}

export default {
  async fetch(request, env): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (request.method === "GET" && pathname === "/api/v1/health") {
      return health(env);
    }
    if (request.method === "POST" && pathname === "/api/v1/reports") {
      return createReport(request, env);
    }
    return json({ error: "not_found" }, 404);
  },
  async scheduled(_controller, env, _ctx): Promise<void> {
    await env.DB.prepare("DELETE FROM reports WHERE created < datetime('now', '-90 days')").run();
  },
} satisfies ExportedHandler<Env>;
