import { env, exports } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import worker from "../src/index";

const BASE = "https://admenot.test";

async function call(path: string, init?: RequestInit): Promise<Response> {
  return exports.default.fetch(new Request(BASE + path, init));
}

function expectJsonHeaders(res: Response): void {
  expect(res.headers.get("Content-Type")).toBe("application/json");
  expect(res.headers.get("Cache-Control")).toBe("no-store");
}

describe("/api/v1/health", () => {
  it("odpowiada ok, gdy D1 działa", async () => {
    const res = await call("/api/v1/health");
    expect(res.status).toBe(200);
    expectJsonHeaders(res);
    expect(await res.json()).toEqual({ ok: true, db: true });
  });

  it("odpowiada 503, gdy D1 nie działa", async () => {
    const broken = {
      prepare() {
        throw new Error("D1 niedostępna");
      },
    };
    const res = await worker.fetch(
      new Request(BASE + "/api/v1/health"),
      { ...env, DB: broken } as unknown as Env,
    );
    expect(res.status).toBe(503);
    expectJsonHeaders(res);
    expect(await res.json()).toEqual({ ok: false, db: false });
  });

  it("inne metody to 404", async () => {
    for (const method of ["POST", "PUT", "DELETE"]) {
      const res = await call("/api/v1/health", { method });
      expect(res.status, method).toBe(404);
    }
  });
});

describe("nieznane ścieżki API", () => {
  it.each(["/api/nic", "/api/v1/", "/api/v1/health/", "/api/v2/health"])("%s → 404 JSON", async (path) => {
    const res = await call(path);
    expect(res.status).toBe(404);
    expectJsonHeaders(res);
    expect(await res.json()).toEqual({ error: "not_found" });
  });
});

describe("schemat D1", () => {
  const IP_TOKENS = new Set(["ip", "ipv4", "ipv6", "addr", "address", "remote", "forwarded"]);

  it("żadna kolumna nie wygląda na adres IP (spec §2.2)", async () => {
    const tables = await env.DB.prepare(
      "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'",
    ).all<{ name: string }>();
    expect(tables.results.length).toBeGreaterThan(0);
    for (const { name } of tables.results) {
      const columns = await env.DB.prepare(`PRAGMA table_info("${name}")`).all<{ name: string }>();
      for (const column of columns.results) {
        const tokens = column.name.toLowerCase().split("_");
        expect(tokens.some((t) => IP_TOKENS.has(t)), `${name}.${column.name}`).toBe(false);
      }
    }
  });

  it("schema_info ma wersję 3", async () => {
    const row = await env.DB.prepare("SELECT version FROM schema_info").first<{ version: number }>();
    expect(row?.version).toBe(3);
  });
});

describe("strona", () => {
  it("strona główna jest w assets", async () => {
    const res = await env.ASSETS.fetch("https://assets.local/");
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("AdMeNot");
  });

  it.each(["/", "/pl/", "/privacy", "/pl/privacy"])("%s zwraca HTML", async (path) => {
    const res = await env.ASSETS.fetch("https://assets.local" + path);
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type") ?? "").toMatch(/^text\/html/);
    await res.arrayBuffer();
  });

  it.each([["/privacy", "Usage statistics (optional)", "13 months", "installation ID"],
    ["/pl/privacy", "Statystyki użycia (opcjonalne)", "13 miesięcy", "identyfikator instalacji"]])(
    "%s opisuje statystyki", async (path, heading, keep, id) => {
      const html = await (await env.ASSETS.fetch("https://assets.local" + path)).text();
      expect(html).toContain(`<h2>${heading}</h2>`);
      expect(html).toContain(keep);
      expect(html).toContain(id);
    });

  it.each([["/privacy", "Error reports", "90 days", "“Send”"],
    ["/pl/privacy", "Raporty błędów", "90 dni", "„Wyślij”"]])(
    "%s opisuje raporty błędów", async (path, heading, keep, button) => {
      const html = await (await env.ASSETS.fetch("https://assets.local" + path)).text();
      expect(html).toContain(`<h2>${heading}</h2>`);
      expect(html).toContain(keep);
      expect(html).toContain("R-7K3Q9M");
      expect(html).toContain(button);
    });
});
