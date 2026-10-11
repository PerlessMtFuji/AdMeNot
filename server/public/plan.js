// Plan naprawy dla klienta (spec 2026-10-11-plan-qr §4.3). Bez zależności; dane tylko przez textContent.
// Klucz jest we fragmencie adresu (#), którego przeglądarka nie wysyła na serwer.
const AAD = new TextEncoder().encode("admenot-plan-v1");
const ICON = /^data:image\/(webp|png|jpeg);base64,[A-Za-z0-9+/]+=*$/;
const LEVELS = ["silence", "disable", "remove"];

export const TEXTS = {
  pl: {
    title: "Plan naprawy",
    code: "Kod kontrolny",
    silence_on: "Zostaje na telefonie, ale nie będzie wyświetlać powiadomień ani okien nad innymi aplikacjami.",
    silence_off: "Zostaje na telefonie i nie będzie wyświetlać okien nad innymi aplikacjami. "
      + "Jej powiadomienia trzeba wyłączyć ręcznie w ustawieniach telefonu.",
    disable: "Przestanie działać. Jej dane zostają na telefonie.",
    remove: "Zostanie usunięta razem ze swoimi danymi. Samą aplikację da się przywrócić.",
    blocked: "Nie zostanie zmieniona.",
    footer_server: "Ten plan zobaczy tylko osoba z tym kodem QR. Wygasa godzinę po utworzeniu.",
    footer_local: "Ten plan nie był wysyłany na serwer — cała lista jest zapisana w kodzie QR.",
    expired: "Ten plan wygasł albo nie istnieje. Poproś serwisanta o nowy kod.",
    unreadable: "Nie da się odczytać planu.",
    offline: "Brak połączenia.",
    busy: "Serwer jest chwilowo zajęty. Spróbuj za chwilę.",
  },
  en: {
    title: "Repair plan",
    code: "Check code",
    silence_on: "Stays on the phone, but will not show notifications or windows over other apps.",
    silence_off: "Stays on the phone and will not show windows over other apps. "
      + "Its notifications have to be turned off by hand in the phone's settings.",
    disable: "Will stop working. Its data stays on the phone.",
    remove: "Will be removed together with its data. The app itself can be restored.",
    blocked: "Will not be changed.",
    footer_server: "Only someone with this QR code can see this plan. It expires an hour after it was created.",
    footer_local: "This plan was not sent to a server — the whole list is stored in the QR code.",
    expired: "This plan has expired or does not exist. Ask the technician for a new code.",
    unreadable: "The plan cannot be read.",
    offline: "No connection.",
    busy: "The server is busy. Try again in a moment.",
  },
};

function fromB64url(text) {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=");
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function inflate(bytes) {
  const stream = new Response(bytes).body.pipeThrough(new DecompressionStream("deflate-raw"));
  return JSON.parse(await new Response(stream).text());
}

function validate(p) {
  if (!p || p.v !== 1 || !Array.isArray(p.apps)) throw new Error("format");
  for (const a of p.apps) if (typeof a.n !== "string" || !LEVELS.includes(a.l)) throw new Error("format");
  return p;
}

export function parseFragment(hash) {
  const h = String(hash).replace(/^#/, "");
  const s = /^s\.([A-Za-z0-9_-]{22})\.([A-Za-z0-9_-]{43})$/.exec(h);
  if (s) return { mode: "server", id: s[1], key: s[2] };
  const l = /^l\.([A-Za-z0-9_-]+)$/.exec(h);
  if (l) return { mode: "local", data: l[1] };
  return null;
}

export async function decodeLocal(data) {
  return validate(await inflate(fromB64url(data)));
}

export async function decryptShare(blob, keyText) {
  if (blob.length < 29 || blob[0] !== 1) throw new Error("format");
  const key = await crypto.subtle.importKey("raw", fromB64url(keyText), "AES-GCM", false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: blob.subarray(1, 13), additionalData: AAD }, key, blob.subarray(13));
  return validate(await inflate(new Uint8Array(plain)));
}

export function effect(app, notif, t) {
  if (app.b) return t.blocked;
  if (app.l === "silence") return notif ? t.silence_on : t.silence_off;
  return t[app.l];
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

export function render(root, p, mode) {
  const lang = TEXTS[p.lang] ? p.lang : "en";
  const t = TEXTS[lang];
  document.documentElement.lang = lang;
  document.title = t.title;
  const head = el("header");
  head.append(el("h1", null, t.title));
  if (typeof p.shop === "string") head.append(el("p", "shop", p.shop));
  const meta = [p.phone, typeof p.at === "string" ? p.at.replace("T", " ") : null].filter((x) => typeof x === "string");
  head.append(el("p", "meta", meta.join(" · ")));
  const code = el("p", "code");
  code.append(el("span", null, t.code), el("b", null, String(p.code ?? "")));
  head.append(code);
  const list = el("ul", "apps");
  for (const a of p.apps) {
    const li = el("li", a.b ? "app blocked" : `app ${a.l}`);
    if (typeof a.i === "string" && ICON.test(a.i)) {
      const img = el("img", "icon");
      img.alt = "";
      img.src = a.i;
      li.append(img);
    } else {
      li.append(el("span", "icon initial", ([...a.n.trim()][0] ?? "?").toUpperCase()));
    }
    const body = el("div");
    body.append(el("b", null, a.n), el("p", null, effect(a, p.notif === 1, t)));
    li.append(body);
    list.append(li);
  }
  root.replaceChildren(head, list, el("footer", null, mode === "server" ? t.footer_server : t.footer_local));
}

function fail(root, key) {
  const lang = (navigator.language || "en").toLowerCase().startsWith("pl") ? "pl" : "en";
  document.documentElement.lang = lang;
  root.replaceChildren(el("p", "state", TEXTS[lang][key]));
}

async function main(root) {
  const f = parseFragment(location.hash);
  if (!f) return fail(root, "unreadable");
  try {
    if (f.mode === "local") return render(root, await decodeLocal(f.data), "local");
    let res;
    try {
      res = await fetch(`/api/v1/shares/${f.id}`, { cache: "no-store" });
    } catch {
      return fail(root, "offline");
    }
    if (res.status === 404) return fail(root, "expired");
    if (!res.ok) return fail(root, "busy");
    render(root, await decryptShare(new Uint8Array(await res.arrayBuffer()), f.key), "server");
  } catch {
    fail(root, "unreadable");
  }
}

const root = typeof document !== "undefined" ? document.getElementById("plan") : null;
if (root) void main(root);
