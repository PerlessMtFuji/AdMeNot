import { runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { env, exports } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import worker from "../src/index";
import { REPORTS_IP_DAILY } from "../src/quota";
import type { Quota } from "../src/quota";

const BASE = "https://admenot.test";

function report(from: string): Promise<Response> {
  return exports.default.fetch(new Request(BASE + "/api/v1/reports", {
    method: "POST", headers: { "Content-Type": "application/json", "CF-Connecting-IP": from },
    body: JSON.stringify(body()),
  }));
}

function body(): Record<string, unknown> {
  return {
    format: 1, kind: "error", app: "0.9.3", os: "Windows 10.0.26100", lang: "pl", count: 1,
    created: "2026-10-09T14:03:12", context: { call: "x", job: null, screen: null, device: null },
    error: { type: "KeyError", message: "", where: null, trace: null }, log_tail: null, adb_tail: null, comment: null,
  };
}

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

const quota = () => env.QUOTA.get(env.QUOTA.idFromName("global")) as DurableObjectStub<Quota>;

describe("dobowy limit na adres (przegląd 2026-10-11)", () => {
  it("counters survive the object being dropped from memory and never hold the address", async () => {
    const ip = "203.0.113.42";
    expect((await report(ip)).status).toBe(201);
    const stored = await runInDurableObject(quota(), async (_obj, state) => [...(await state.storage.list()).entries()]);
    expect(stored.length).toBeGreaterThan(0);
    const plain = await sha256(ip);
    for (const [key] of stored) {
      expect(key).not.toContain(ip);
      expect(key).not.toContain(plain); // skrót bez sekretu dałoby się odwrócić słownikiem adresów
    }
  });

  it("one address is limited with no secret to configure", async () => {
    // Bez sekretu do ustawienia przy wdrożeniu: klucz HMAC losuje i trzyma sam obiekt.
    const bare = { ...env, REPORTS_LIMITER: { limit: async () => ({ success: true }) } } as unknown as Env;
    const send = () => worker.fetch(new Request(BASE + "/api/v1/reports", {
      method: "POST", headers: { "Content-Type": "application/json", "CF-Connecting-IP": "203.0.113.44" },
      body: JSON.stringify(body()),
    }), bare);
    for (let i = 0; i < REPORTS_IP_DAILY; i++) expect((await send()).status).toBe(201);
    expect((await send()).status).toBe(429);
  });

  it("the midnight alarm wipes every counter", async () => {
    await report("203.0.113.43");
    expect(await runDurableObjectAlarm(quota())).toBe(true);
    const left = await runInDurableObject(quota(), async (_obj, state) => (await state.storage.list()).size);
    expect(left).toBe(0);
  });
});
