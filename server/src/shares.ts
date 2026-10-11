// Plany naprawy dla klienta (spec 2026-10-11-plan-qr §4.2): zaszyfrowane bloby na godzinę.
// Serwer nie zna klucza (jest tylko we fragmencie adresu); nie zapisujemy adresów IP.
import { json, readLimitedBytes } from "./http";
import { takeQuota, untilMidnight } from "./quota";

export const SHARES_IP_DAILY = 300;
export const SHARES_LIVE_CAP = 500; // 500 × 128 KB × 4/3 (base64) ≈ 85 MB w D1 (free: 500 MB)
export const SHARE_MAX_BODY = 128 * 1024;
const MIN_BODY = 1 + 12 + 16; // wersja + nonce + tag GCM
const TTL = "+60 minutes";
const ID = /^[A-Za-z0-9_-]{22}$/;

function toBase64(bytes: Uint8Array): string {
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

function fromBase64(text: string): Uint8Array {
  const raw = atob(text);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function shareId(): string {
  return toBase64(crypto.getRandomValues(new Uint8Array(16)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const ip = (request: Request) => request.headers.get("CF-Connecting-IP") ?? "unknown";

export async function createShare(request: Request, env: Env): Promise<Response> {
  // Limiter przed czytaniem treści, żeby także odpowiedzi 400/413 były limitowane.
  if (!(await env.SHARES_LIMITER.limit({ key: ip(request) })).success) return json({ error: "rate_limited" }, 429);
  if (!(request.headers.get("Content-Type") ?? "").toLowerCase().startsWith("application/octet-stream")) {
    return json({ error: "invalid" }, 400);
  }
  if (Number(request.headers.get("Content-Length") ?? "0") > SHARE_MAX_BODY) return json({ error: "too_large" }, 413);
  const body = await readLimitedBytes(request, SHARE_MAX_BODY);
  if (body === null) return json({ error: "too_large" }, 413);
  if (body.length < MIN_BODY || body[0] !== 1) return json({ error: "invalid" }, 400);
  if (!(await takeQuota(request, env, "shares", 1, SHARES_IP_DAILY))) {
    return json({ error: "budget" }, 429, { "Retry-After": String(untilMidnight()) });
  }
  const stored = toBase64(body);
  try {
    await env.DB.prepare("DELETE FROM shares WHERE expires <= datetime('now')").run();
    // Sufit sprawdzany w tym samym poleceniu co zapis: równoległe zapisy go nie przekroczą.
    const insert = (id: string) => env.DB.prepare(
      "INSERT INTO shares (id, created, expires, body) SELECT ?, datetime('now'), datetime('now', ?), ? "
      + "WHERE (SELECT COUNT(*) FROM shares) < ?",
    ).bind(id, TTL, stored, SHARES_LIVE_CAP).run();
    let id = shareId();
    let res;
    try {
      res = await insert(id);
    } catch (err) {
      if (!String((err as Error)?.message ?? err).includes("UNIQUE constraint failed")) throw err;
      id = shareId();
      res = await insert(id);
    }
    if ((res.meta.changes ?? 0) === 0) return json({ error: "busy" }, 503);
    const row = await env.DB.prepare("SELECT expires FROM shares WHERE id = ?").bind(id).first<{ expires: string }>();
    return json({ id, expires: row!.expires.replace(" ", "T") + "Z" }, 201);
  } catch {
    return json({ error: "busy" }, 503);
  }
}

export async function getShare(request: Request, id: string, env: Env): Promise<Response> {
  if (!(await env.SHARES_READ_LIMITER.limit({ key: ip(request) })).success) return json({ error: "rate_limited" }, 429);
  if (!ID.test(id)) return json({ error: "not_found" }, 404);
  const row = await env.DB.prepare("SELECT body FROM shares WHERE id = ? AND expires > datetime('now')")
    .bind(id).first<{ body: string }>();
  if (!row) return json({ error: "not_found" }, 404);
  return new Response(fromBase64(row.body), {
    headers: { "Content-Type": "application/octet-stream", "Cache-Control": "no-store" },
  });
}

export async function pruneShares(env: Env): Promise<void> {
  await env.DB.prepare("DELETE FROM shares WHERE expires <= datetime('now')").run();
}
