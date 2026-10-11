// Dobowy limit na adres (przegląd 2026-10-11): identyfikator instalacji podaje klient, więc limit na
// instalację nie chroni wspólnego budżetu. Licznik trzymamy w magazynie obiektu (pamięć znika po
// minucie bezczynności i przy wdrożeniu), ale pod kluczem HMAC(QUOTA_KEY, dzień UTC, adres): bez
// sekretu nie da się go odwrócić słownikiem adresów, a dzień w kluczu nie pozwala łączyć dni.
// Alarm o północy UTC kasuje wszystkie liczniki (spec §2.2, polityka prywatności).
import { DurableObject } from "cloudflare:workers";

const today = (now = new Date()): string => now.toISOString().slice(0, 10);

// Sekundy do północy UTC — wtedy limit wraca (nagłówek Retry-After).
export function untilMidnight(now = new Date()): number {
  const next = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
  return Math.max(1, Math.ceil((next - now.getTime()) / 1000));
}

export class Quota extends DurableObject {
  async take(key: string, amount: number, limit: number): Promise<boolean> {
    const storage = this.ctx.storage;
    if ((await storage.getAlarm()) === null) await storage.setAlarm(Date.now() + untilMidnight() * 1000);
    const total = ((await storage.get<number>(key)) ?? 0) + amount;
    if (total > limit) return false;
    await storage.put(key, total);
    return true;
  }

  async alarm(): Promise<void> {
    await this.ctx.storage.deleteAll(); // liczniki minionej doby; następny alarm ustawi `take`
  }
}

async function hmac(secret: string, text: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" },
    false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(text));
  return Array.from(new Uint8Array(mac), (b) => b.toString(16).padStart(2, "0")).join("");
}

// false = limit na dziś wyczerpany. Awaria obiektu albo brak sekretu przepuszcza zapytanie:
// wspólny dobowy sufit w D1 nadal chroni bazę, a program nie dostaje błędu 500.
export async function takeQuota(request: Request, env: Env, scope: string, amount: number, limit: number): Promise<boolean> {
  try {
    if (!env.QUOTA_KEY) throw new Error("QUOTA_KEY missing");
    const ip = request.headers.get("CF-Connecting-IP") ?? "unknown";
    const stub = env.QUOTA.get(env.QUOTA.idFromName("global"));
    return await stub.take(`${scope}:${await hmac(env.QUOTA_KEY, `${today()}|${ip}`)}`, amount, limit);
  } catch {
    return true;
  }
}
