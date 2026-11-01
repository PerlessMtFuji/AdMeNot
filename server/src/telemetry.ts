// Statystyki użycia (spec kroku H §7): zapis znanych pól, limit bajtów na dobę, usuwanie na żądanie.
import { json, readLimited } from "./http";
import { takeQuota, untilMidnight } from "./quota";

export const TELEMETRY_MAX_BODY = 256 * 1024;
export const TELEMETRY_DAILY_BYTES = 200 * 1024; // ~80 MB / 13 mies. obok raportów w 500 MB D1 free
// Jedna instalacja (albo ktoś podszywający się pod nią) nie zajmie całego budżetu doby (SEC-03).
export const TELEMETRY_INSTALL_DAILY_BYTES = 100 * 1024;
// Na adres: losowe ID instalacji nie wyczerpią wspólnego budżetu doby.
export const TELEMETRY_IP_DAILY_BYTES = 40 * 1024;
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

// Pole opcjonalne: brak (starszy program) → null; obecne → ścisła walidacja.
function optional(v: unknown, check: (v: unknown) => Obj): Obj | null {
  return v === null || v === undefined ? null : check(v);
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
// Sprawdzenia stanu telefonu: dokładnie jeden znany identyfikator, bez domen i pakietów przeglądarek.
const CHECK_STATES = ["ok", "review", "unrecognized"] as const;
const SITE_MODES = ["per_site", "shared", "rdp"] as const;
const FIX_KINDS = ["channel", "site_permission"] as const;

// Kopia starego telefonu: tylko liczby i flagi wybranych rodzajów danych — bez nazw folderów,
// plików i pakietów, więc każde pole spoza listy odrzuca zdarzenie.
const COMMON = ["install", "type", "t", "app", "os", "lang"] as const;
const TRANSFER_FIELDS = ["device", "status", "seconds", "bytes_mb", "files", "files_failed", "apps",
  "apps_failed", "categories"] as const;
const TRANSFER_CATEGORIES = ["contacts", "sms", "mms", "calls", "media", "downloads", "whatsapp", "others",
  "apps"] as const;
const MAX_MB = 10_000_000; // 10 TB w MB (telemetry_events.MAX_MB)
// Wgrywanie kopii na nowy telefon: tak samo same liczby i flagi grup — bez nazw plików, folderów
// („Inne foldery” to tylko `others`) i pakietów z plików APK.
const RESTORE_FIELDS = ["device", "status", "seconds", "bytes_mb", "files", "exists", "renamed", "denied",
  "failed", "unselected", "missing", "apk_skipped", "apk_suspicious_skipped", "streams", "hashed", "media_scan",
  "groups", "tel", "safety", "cleanup_ok"] as const;
// Telefonia przy wgrywaniu (Etap 3): liczby per kategoria, droga zapisu i flagi — bez nazw kont
// (adresów e-mail), numerów, treści i nazw plików.
const TEL_CATEGORIES = ["contacts", "sms", "mms", "calls"] as const;
const TEL_COUNTS = ["written", "existed", "skipped", "failed", "manual"] as const;
const TEL_PATHS = ["app_process", "companion", "file", "none"] as const;
const RESTORE_COUNTS = ["files", "exists", "renamed", "denied", "failed", "unselected", "missing", "apk_skipped",
  "apk_suspicious_skipped"] as const;
const RESTORE_GROUPS = ["photos", "videos", "downloads", "whatsapp", "others"] as const;
const MAX_STREAMS = 8; // telemetry_events.MAX_STREAMS

// Obiekt z dokładnie tymi kluczami (wartości logiczne).
function flags(v: unknown, keys: readonly string[]): Obj {
  need(isObj(v) && Object.keys(v as Obj).every((k) => keys.includes(k)));
  const out: Obj = {};
  for (const k of keys) {
    need(typeof (v as Obj)[k] === "boolean");
    out[k] = (v as Obj)[k];
  }
  return out;
}

// Obiekt o kluczach z `keys` (podzbiór: tylko wybrane kategorie), każda wartość sprawdzona przez `item`.
function some(v: unknown, keys: readonly string[], item: (x: unknown) => unknown): Obj {
  need(isObj(v) && Object.keys(v as Obj).every((k) => keys.includes(k)));
  const out: Obj = {};
  for (const k of keys) if (k in (v as Obj)) out[k] = item((v as Obj)[k]);
  return out;
}

function telKind(v: unknown): Obj {
  need(isObj(v) && Object.keys(v as Obj).every((k) => (TEL_COUNTS as readonly string[]).includes(k)
    || k === "path" || k === "visible_warning"));
  const t = v as Obj;
  need(oneOf(t.path, TEL_PATHS) && typeof t.visible_warning === "boolean");
  const out: Obj = {};
  for (const k of TEL_COUNTS) {
    need(int(t[k]));
    out[k] = t[k];
  }
  return { ...out, path: t.path, visible_warning: t.visible_warning };
}

function bool(v: unknown): boolean {
  need(typeof v === "boolean");
  return v as boolean;
}

// Telefonia przy wgrywaniu: brak wszystkich trzech pól (same pliki, starszy program) → nic.
function restoreTel(e: Obj): Obj {
  if (e.tel === undefined && e.safety === undefined && e.cleanup_ok === undefined) return {};
  return { tel: some(e.tel, TEL_CATEGORIES, telKind), safety: some(e.safety, TEL_CATEGORIES, bool),
    cleanup_ok: bool(e.cleanup_ok) };
}

function checks(v: unknown): Obj {
  need(isObj(v) && Object.keys(v as Obj).length === 1 && oneOf((v as Obj).site_notifications, CHECK_STATES));
  return { site_notifications: (v as Obj).site_notifications };
}

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
      need(e.apk_mode === undefined || oneOf(e.apk_mode, ["pending", "full", "manual", "partial"]));
      let eta: Obj | null = null;
      if (e.eta !== null && e.eta !== undefined) {
        need(isObj(e.eta) && oneOf((e.eta as Obj).kind, ["measured", "rough"]) && int((e.eta as Obj).seconds, 86_400));
        eta = { kind: (e.eta as Obj).kind, seconds: (e.eta as Obj).seconds };
      }
      return {
        device: device(e.device), session: e.session, apps: e.apps, verdicts: counts(e.verdicts, VERDICTS),
        low_behavior_data: e.low_behavior_data, apk, seconds: e.seconds, apk_stage: e.apk_stage,
        apk_mode: e.apk_mode ?? null, eta,
        checks: optional(e.checks, checks), sites: optional(e.sites, (v) => counts(v, SITE_MODES)),
        packages: packages(e.packages, (p) => {
          need(oneOf(p.verdict, VERDICTS) && int(p.score, 1000) && oneOf(p.confidence, ["low", "medium", "high"])
            && typeof p.system === "boolean");
          return { verdict: p.verdict, score: p.score, confidence: p.confidence, system: p.system };
        }),
      };
    }
    case "repair": {
      need(SESSION.test(String(e.session)) && int(e.failed) && Array.isArray(e.errors)
        && (e.errors as unknown[]).length <= MAX_ERRORS && (e.errors as unknown[]).every((k) => str(k))
        && (e.interrupted === null || oneOf(e.interrupted, ["stopped", "disconnected"])));
      const SOURCES = isObj(e.sources) && "blind" in (e.sources as Obj)
        ? ["flagged", "manual", "blind"] : ["flagged", "manual"];
      return {
        device: device(e.device), session: e.session, levels: counts(e.levels, LEVELS),
        sources: counts(e.sources, SOURCES), failed: e.failed, errors: e.errors,
        interrupted: e.interrupted, fixes: optional(e.fixes, (v) => counts(v, FIX_KINDS)),
        packages: packages(e.packages, (p) => {
          need(oneOf(p.source, ["flagged", "manual", "blind"]) && oneOf(p.level, LEVELS)
            && (p.ok === null || typeof p.ok === "boolean"));
          return { source: p.source, level: p.level, ok: p.ok };
        }),
      };
    }
    case "undo":
      need(int(e.apps) && int(e.failed) && int(e.age_days));
      // Starsze wersje programu nie wysyłają liczb witryn.
      need((e.sites === undefined || int(e.sites)) && (e.sites_restored === undefined || int(e.sites_restored)));
      return {
        device: device(e.device), apps: e.apps, failed: e.failed, age_days: e.age_days,
        sites: e.sites === undefined ? 0 : e.sites,
        sites_restored: e.sites_restored === undefined ? 0 : e.sites_restored,
        packages: packages(e.packages, (p) => {
          need(typeof p.ok === "boolean");
          return { ok: p.ok };
        }),
      };
    case "transfer_backup":
      need(Object.keys(e).every((k) => (COMMON as readonly string[]).includes(k)
        || (TRANSFER_FIELDS as readonly string[]).includes(k)));
      need(oneOf(e.status, ["complete", "incomplete", "stopped"]) && int(e.seconds, 86_400)
        && int(e.bytes_mb, MAX_MB) && int(e.files) && int(e.files_failed) && int(e.apps) && int(e.apps_failed));
      return {
        device: device(e.device), status: e.status, seconds: e.seconds, bytes_mb: e.bytes_mb,
        files: e.files, files_failed: e.files_failed, apps: e.apps, apps_failed: e.apps_failed,
        categories: flags(e.categories, TRANSFER_CATEGORIES),
      };
    case "transfer_restore": {
      need(Object.keys(e).every((k) => (COMMON as readonly string[]).includes(k)
        || (RESTORE_FIELDS as readonly string[]).includes(k)));
      need(oneOf(e.status, ["complete", "incomplete", "stopped"]) && int(e.seconds, 86_400)
        && int(e.bytes_mb, MAX_MB) && RESTORE_COUNTS.every((k) => int(e[k]))
        && int(e.streams, MAX_STREAMS) && (e.streams as number) >= 1 && typeof e.hashed === "boolean"
        && oneOf(e.media_scan, ["done", "failed", "restart", "skipped"]));
      const out: Obj = { device: device(e.device), status: e.status, seconds: e.seconds, bytes_mb: e.bytes_mb };
      for (const k of RESTORE_COUNTS) out[k] = e[k];
      return { ...out, streams: e.streams, hashed: e.hashed, media_scan: e.media_scan,
        groups: flags(e.groups, RESTORE_GROUPS), ...restoreTel(e) };
    }
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

// Limiter przed czytaniem treści i przed D1, także dla DELETE (audyt 2026-10-11, SEC-03).
// Klucz trzymany tylko w pamięci limitera — adresu IP nie zapisujemy (spec backendu §2.2).
export async function limited(request: Request, env: Env): Promise<boolean> {
  const { success } = await env.TELEMETRY_LIMITER.limit({ key: request.headers.get("CF-Connecting-IP") ?? "unknown" });
  return !success;
}

// Bajty UTF-8 — tak liczy je transport i limit treści (BUG-12), nie jednostki UTF-16.
const utf8 = new TextEncoder();
const bytes = (s: string): number => utf8.encode(s).byteLength;

// Rezerwacja budżetu i zapis w jednym poleceniu (BUG-12): podzapytania liczą zużycie doby
// w chwili wstawiania, więc dwa równoległe żądania nie przejdą razem przy tym samym stanie.
// SQLite: length(CAST(body AS BLOB)) = bajty UTF-8 treści.
const INSERT_WITHIN_BUDGET = `
INSERT INTO events (install, created, t, type, app, body)
SELECT json_extract(value, '$.install'), datetime('now'), json_extract(value, '$.t'),
       json_extract(value, '$.type'), json_extract(value, '$.app'), json_extract(value, '$.body')
FROM json_each(?1)
WHERE (SELECT COALESCE(SUM(length(CAST(body AS BLOB))), 0) FROM events
       WHERE created >= datetime('now', '-1 day')) + ?2 <= ?3
  AND (SELECT COALESCE(SUM(length(CAST(body AS BLOB))), 0) FROM events
       WHERE install = ?4 AND created >= datetime('now', '-1 day')) + ?2 <= ?5`;

export async function createEvents(request: Request, env: Env): Promise<Response> {
  if (!(request.headers.get("Content-Type") ?? "").toLowerCase().startsWith("application/json")) return json({ error: "invalid" }, 400);
  if (await limited(request, env)) return json({ error: "rate_limited" }, 429);
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
    need(events.every((e) => e.install === events[0].install)); // paczka = jedna instalacja
  } catch {
    return json({ error: "invalid" }, 400); // także SyntaxError z JSON.parse
  }
  const rows = events.map((e) => ({ install: e.install, t: e.t, type: e.type, app: e.app, body: JSON.stringify(e) }));
  const size = rows.reduce((n, r) => n + bytes(r.body), 0);
  const later = { "Retry-After": String(untilMidnight()) };
  if (!(await takeQuota(request, env, "telemetry", size, TELEMETRY_IP_DAILY_BYTES))) return json({ error: "budget" }, 429, later);
  try {
    const res = await env.DB.prepare(INSERT_WITHIN_BUDGET)
      .bind(JSON.stringify(rows), size, TELEMETRY_DAILY_BYTES, events[0].install, TELEMETRY_INSTALL_DAILY_BYTES)
      .run();
    if ((res.meta.changes ?? 0) === 0) return json({ error: "busy" }, 429, later);
    return json({ ok: true, stored: events.length });
  } catch {
    return json({ error: "busy" }, 503);
  }
}

export async function deleteEvents(request: Request, install: string, env: Env): Promise<Response> {
  if (await limited(request, env)) return json({ error: "rate_limited" }, 429);
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
