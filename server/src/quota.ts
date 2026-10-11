// Dobowy limit na adres (przegląd 2026-10-11): identyfikator instalacji podaje klient, więc limit na
// instalację nie chroni wspólnego budżetu. Skrót adresu żyje tylko w pamięci tego obiektu i znika o
// północy UTC albo przy jego wyładowaniu — nic nie trafia do D1 ani do magazynu obiektu (spec §2.2).
import { DurableObject } from "cloudflare:workers";

const today = (): string => new Date().toISOString().slice(0, 10);

export class Quota extends DurableObject {
  private day = today();
  private used = new Map<string, number>();

  take(key: string, amount: number, limit: number): boolean {
    const now = today();
    if (now !== this.day) {
      this.day = now;
      this.used.clear();
    }
    const total = (this.used.get(key) ?? 0) + amount;
    if (total > limit) return false;
    this.used.set(key, total);
    return true;
  }
}

async function hashed(ip: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(ip));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

// Sekundy do północy UTC — wtedy limit wraca (nagłówek Retry-After).
export function untilMidnight(now = new Date()): number {
  const next = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
  return Math.max(1, Math.ceil((next - now.getTime()) / 1000));
}

export async function takeQuota(request: Request, env: Env, scope: string, amount: number, limit: number): Promise<boolean> {
  const ip = request.headers.get("CF-Connecting-IP") ?? "unknown";
  const stub = env.QUOTA.get(env.QUOTA.idFromName("global"));
  return stub.take(`${scope}:${await hashed(ip)}`, amount, limit);
}
