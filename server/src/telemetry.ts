// Statystyki użycia (spec kroku H §7): zapis znanych pól, limit bajtów na dobę, usuwanie na żądanie.
import { json, readLimited } from "./http";

export const TELEMETRY_MAX_BODY = 256 * 1024;
export const TELEMETRY_DAILY_BYTES = 200 * 1024; // ~80 MB / 13 mies. obok raportów w 500 MB D1 free
const MAX_EVENTS = 100;
const MAX_PACKAGES = 200;
const MAX_ERRORS = 20;
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
// Rok 2026–2099; bez porównania z zegarem serwera — komputery w serwisach mają różne zegary (spec §7.2).
const HOUR = /^20(2[6-9]|[3-9]\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):00:00Z$/;
const PKG = /^[A-Za-z0-9_.]{1,255}$/;
const SESSION = /^[0-9a-f]{8}$/;
const SHORT = 64;

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown, max = SHORT): v is string => typeof v === "string" && v.length > 0 && [...v].length <= max;
const int = (v: unknown, max = 100_000): v is number => Number.isInteger(v) && (v as number) >= 0 && (v as number) <= max;
const oneOf = <T extends string>(v: unknown, values: readonly T[]): v is T => typeof v === "string" && (values as readonly string[]).includes(v);

class Invalid extends Error {}
function need(ok: boolean): void {
  if (!ok) throw new Invalid();
}

// Obiekt z dokładnie tymi kluczami (liczby) — np. verdicts, levels, sources.
function counts(v: unknown, keys: readonly string[]): Obj {
  need(isObj(v) && Object.keys(v as Obj).every((k) => keys.includes(k)));
  const out: Obj = {};
  for (const k of keys) {
    need(int((v as Obj)[k]));
    out[k] = (v as Obj)[k];
  }
  return out;
}

function device(v: unknown): Obj {
  need(isObj(v) && Object.keys(v as Obj).every((k) => ["manufacturer", "model", "android"].includes(k)));
  const d = v as Obj;
  for (const k of ["manufacturer", "model", "android"]) need(str(d[k]));
  return { manufacturer: d.manufacturer, model: d.model, android: d.android };
}

function packages(v: unknown, item: (p: Obj) => Obj): Obj[] | null {
  if (v === null || v === undefined) return null;
  need(Array.isArray(v) && v.length <= MAX_PACKAGES);
  return (v as unknown[]).map((p) => {
    need(isObj(p) && PKG.test(String((p as Obj).package)));
    return { package: (p as Obj).package, ...item(p as Obj) };
  });
}

const VERDICTS = ["malicious", "suspicious", "review"] as const;
const LEVELS = ["silence", "disable", "remove"] as const;

function body(e: Obj): Obj {
  switch (e.type) {
    case "start":
      need(oneOf(e.mode, ["simple", "expert"]));
      return { mode: e.mode };
    case "scan": {
      need(SESSION.test(String(e.session)) && int(e.apps) && typeof e.low_behavior_data === "boolean"
        && int(e.seconds, 86_400) && typeof e.apk_stage === "boolean");
      let apk: Obj | null = null;
      if (e.apk !== null && e.apk !== undefined) apk = counts(e.apk, ["requested", "analyzed", "failed"]);
      return {
        device: device(e.device), session: e.session, apps: e.apps, verdicts: counts(e.verdicts, VERDICTS),
        low_behavior_data: e.low_behavior_data, apk, seconds: e.seconds, apk_stage: e.apk_stage,
        packages: packages(e.packages, (p) => {
          need(oneOf(p.verdict, VERDICTS) && int(p.score, 1000) && oneOf(p.confidence, ["low", "medium", "high"])
            && typeof p.system === "boolean");
          return { verdict: p.verdict, score: p.score, confidence: p.confidence, system: p.system };
        }),
      };
    }
    case "repair":
      need(SESSION.test(String(e.session)) && int(e.failed) && Array.isArray(e.errors)
        && (e.errors as unknown[]).length <= MAX_ERRORS && (e.errors as unknown[]).every((k) => str(k))
        && (e.interrupted === null || oneOf(e.interrupted, ["stopped", "disconnected"])));
      return {
        device: device(e.device), session: e.session, levels: counts(e.levels, LEVELS),
        sources: counts(e.sources, ["flagged", "manual"]), failed: e.failed, errors: e.errors,
        interrupted: e.interrupted,
        packages: packages(e.packages, (p) => {
          need(oneOf(p.source, ["flagged", "manual"]) && oneOf(p.level, LEVELS)
            && (p.ok === null || typeof p.ok === "boolean"));
          return { source: p.source, level: p.level, ok: p.ok };
        }),
      };
    case "undo":
      need(int(e.apps) && int(e.failed) && int(e.age_days));
      return {
        device: device(e.device), apps: e.apps, failed: e.failed, age_days: e.age_days,
        packages: packages(e.packages, (p) => {
          need(typeof p.ok === "boolean");
          return { ok: p.ok };
        }),
      };
    default:
      throw new Invalid();
  }
}

function normalize(e: unknown): Obj {
  need(isObj(e));
  const o = e as Obj;
  need(typeof o.install === "string" && UUID.test(o.install) && typeof o.t === "string" && HOUR.test(o.t)
    && str(o.app) && str(o.os) && oneOf(o.lang, ["pl", "en"]));
  return { install: o.install, type: o.type, t: o.t, app: o.app, os: o.os, lang: o.lang, ...body(o) };
}

export async function createEvents(request: Request, env: Env): Promise<Response> {
  if (!(request.headers.get("Content-Type") ?? "").toLowerCase().startsWith("application/json")) return json({ error: "invalid" }, 400);
  if (Number(request.headers.get("Content-Length") ?? "0") > TELEMETRY_MAX_BODY) return json({ error: "too_large" }, 413);
  const raw = await readLimited(request, TELEMETRY_MAX_BODY);
  if (raw === null) return json({ error: "too_large" }, 413);
  let events: Obj[];
  try {
    const parsed = JSON.parse(raw) as unknown;
    need(isObj(parsed) && (parsed as Obj).format === 1 && Array.isArray((parsed as Obj).events));
    const list = (parsed as Obj).events as unknown[];
    need(list.length >= 1 && list.length <= MAX_EVENTS);
    events = list.map(normalize);
  } catch {
    return json({ error: "invalid" }, 400); // także SyntaxError z JSON.parse
  }
  const bodies = events.map((e) => JSON.stringify(e));
  const size = bodies.reduce((n, b) => n + b.length, 0);
  try {
    const used = await env.DB.prepare("SELECT COALESCE(SUM(length(body)), 0) AS n FROM events WHERE created >= datetime('now', '-1 day')")
      .first<{ n: number }>();
    if ((used?.n ?? 0) + size > TELEMETRY_DAILY_BYTES) return json({ error: "busy" }, 429);
    await env.DB.batch(events.map((e, i) => env.DB.prepare(
      "INSERT INTO events (install, created, t, type, app, body) VALUES (?, datetime('now'), ?, ?, ?, ?)",
    ).bind(e.install, e.t, e.type, e.app, bodies[i])));
    return json({ ok: true, stored: events.length });
  } catch {
    return json({ error: "busy" }, 503);
  }
}

export async function deleteEvents(install: string, env: Env): Promise<Response> {
  if (!UUID.test(install)) return json({ error: "invalid" }, 400);
  try {
    const res = await env.DB.prepare("DELETE FROM events WHERE install = ?").bind(install).run();
    return json({ deleted: res.meta.changes ?? 0 });
  } catch {
    return json({ error: "busy" }, 503);
  }
}

export async function pruneEvents(env: Env): Promise<void> {
  await env.DB.prepare("DELETE FROM events WHERE created < datetime('now', '-13 months')").run();
}
