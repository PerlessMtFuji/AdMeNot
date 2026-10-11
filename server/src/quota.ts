// Dobowy limit na adres (przegląd 2026-10-11): identyfikator instalacji podaje klient, więc limit na
// instalację nie chroni wspólnego budżetu. Licznik trzymamy w magazynie obiektu (pamięć znika po
// minucie bezczynności i przy wdrożeniu), pod kluczem HMAC(klucz doby, adres). Klucz doby losuje sam
// obiekt i kasuje go o północy UTC razem z licznikami: nie ma sekretu do ustawienia przy wdrożeniu,
// a skrótów z różnych dni nie da się ze sobą połączyć (spec §2.2, polityka prywatności).
import { DurableObject } from "cloudflare:workers";

const today = (now = new Date()): string => now.toISOString().slice(0, 10);
const KEY = "key"; // { day, secret } — klucz HMAC bieżącej doby

// Sekundy do północy UTC — wtedy limit wraca (nagłówek Retry-After).
export function untilMidnight(now = new Date()): number {
  const next = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
  return Math.max(1, Math.ceil((next - now.getTime()) / 1000));
}

function hex(bytes: ArrayBuffer | Uint8Array): string {
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
}

export class Quota extends DurableObject {
  // Adres przychodzi tylko w wywołaniu RPC; do magazynu trafia wyłącznie jego HMAC.
  async take(scope: string, ip: string, amount: number, limit: number): Promise<boolean> {
    const storage = this.ctx.storage;
    let stored = await storage.get<{ day: string; secret: string }>(KEY);
    if (!stored || stored.day !== today()) {
      await storage.deleteAll(); // alarm się spóźnił albo nie przyszedł: nowa doba, nowy klucz
      stored = { day: today(), secret: hex(crypto.getRandomValues(new Uint8Array(32))) };
      await storage.put(KEY, stored);
      await storage.setAlarm(Date.now() + untilMidnight() * 1000);
    }
    const counter = `${scope}:${await hmac(stored.secret, ip)}`;
    const total = ((await storage.get<number>(counter)) ?? 0) + amount;
    if (total > limit) return false;
    await storage.put(counter, total);
    return true;
  }

  async alarm(): Promise<void> {
    await this.ctx.storage.deleteAll(); // liczniki i klucz minionej doby; nowy klucz ustawi `take`
  }
}

async function hmac(secret: string, text: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" },
    false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(text)));
}

// false = limit na dziś wyczerpany. Awaria obiektu przepuszcza zapytanie: wspólny dobowy sufit
// w D1 nadal chroni bazę, a program nie dostaje błędu 500.
export async function takeQuota(request: Request, env: Env, scope: string, amount: number, limit: number): Promise<boolean> {
  try {
    const ip = request.headers.get("CF-Connecting-IP") ?? "unknown";
    return await env.QUOTA.get(env.QUOTA.idFromName("global")).take(scope, ip, amount, limit);
  } catch {
    return true;
  }
}
