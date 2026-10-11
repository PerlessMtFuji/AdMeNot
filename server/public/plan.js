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
    silence_on_many: "Zostają na telefonie, ale nie będą wyświetlać powiadomień ani okien nad innymi aplikacjami.",
    silence_off_many: "Zostają na telefonie i nie będą wyświetlać okien nad innymi aplikacjami. "
      + "Ich powiadomienia trzeba wyłączyć ręcznie w ustawieniach telefonu.",
    disable_many: "Przestaną działać. Ich dane zostają na telefonie.",
    remove_many: "Zostaną usunięte razem ze swoimi danymi. Same aplikacje da się przywrócić.",
    blocked_many: "Nie zostaną zmienione.",
    remove_title: "Do usunięcia",
    disable_title: "Do wyłączenia",
    silence_title: "Do wyciszenia",
    blocked_title: "Bez zmian",
    footer_server: "Ten plan zobaczy tylko osoba z tym kodem QR. Wygasa godzinę po utworzeniu.",
    footer_local: "Ten plan nie był wysyłany na serwer — cała lista jest zapisana w kodzie QR.",
    expired: "Ten plan wygasł albo nie istnieje. Poproś serwisanta o nowy kod.",
    unreadable: "Nie da się odczytać planu.",
    offline: "Brak połączenia.",
    busy: "Serwer jest chwilowo zajęty. Spróbuj za chwilę.",
    old_browser: "Ta przeglądarka jest za stara, żeby pokazać plan. Zaktualizuj ją albo otwórz kod w innej przeglądarce.",
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
    silence_on_many: "Stay on the phone, but will not show notifications or windows over other apps.",
    silence_off_many: "Stay on the phone and will not show windows over other apps. "
      + "Their notifications have to be turned off by hand in the phone's settings.",
    disable_many: "Will stop working. Their data stays on the phone.",
    remove_many: "Will be removed together with their data. The apps themselves can be restored.",
    blocked_many: "Will not be changed.",
    remove_title: "To be removed",
    disable_title: "To be turned off",
    silence_title: "To be silenced",
    blocked_title: "No change",
    footer_server: "Only someone with this QR code can see this plan. It expires an hour after it was created.",
    footer_local: "This plan was not sent to a server — the whole list is stored in the QR code.",
    expired: "This plan has expired or does not exist. Ask the technician for a new code.",
    unreadable: "The plan cannot be read.",
    offline: "No connection.",
    busy: "The server is busy. Try again in a moment.",
    old_browser: "This browser is too old to show the plan. Update it or open the code in another browser.",
  },
};

function fromB64url(text) {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=");
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** deflate-raw w DecompressionStream: Safari 16.4+, Chrome 103+. Starsze rzucają przy tworzeniu strumienia. */
export function canInflate(g) {
  try {
    return typeof g.DecompressionStream === "function" && Boolean(new g.DecompressionStream("deflate-raw"));
  } catch {
    return false;
  }
}

/** Pierwszy znak graficzny (flaga, emoji złożone), nie pierwszy punkt kodowy. */
export function initial(name) {
  const text = String(name).trim();
  if (!text) return "?";
  const first = typeof Intl !== "undefined" && Intl.Segmenter
    ? new Intl.Segmenter().segment(text)[Symbol.iterator]().next().value.segment
    : [...text][0];
  return first.toUpperCase();
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

/** Skutek dla klienta; many: opis całej grupy kilku aplikacji (liczba mnoga). */
export function effect(app, notif, t, many = false) {
  const key = app.b ? "blocked" : app.l === "silence" ? (notif ? "silence_on" : "silence_off") : app.l;
  return t[many ? `${key}_many` : key];
}

const GROUPS = ["remove", "disable", "silence", "blocked"]; // od najmocniejszej zmiany; bez zmian na końcu

/** Aplikacje pogrupowane wg skutku, w grupie alfabetycznie: jeden opis na grupę zamiast przy każdej. */
export function groups(apps, notif, t, lang) {
  const order = new Intl.Collator(lang);
  return GROUPS.map((key) => {
    const list = apps.filter((a) => (a.b ? "blocked" : a.l) === key).sort((a, b) => order.compare(a.n, b.n));
    return list.length ? { key, title: t[`${key}_title`], text: effect(list[0], notif, t, list.length > 1), apps: list } : null;
  }).filter((g) => g !== null);
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
  const sections = groups(p.apps, p.notif === 1, t, lang).map((g) => {
    const section = el("section", `group ${g.key}`);
    const list = el("ul", "apps");
    for (const a of g.apps) {
      const li = el("li", "app");
      if (typeof a.i === "string" && ICON.test(a.i)) {
        const img = el("img", "icon");
        img.alt = "";
        img.src = a.i;
        li.append(img);
      } else {
        li.append(el("span", "icon initial", initial(a.n)));
      }
      const name = el("b", null, a.n);
      name.dir = "auto"; // nazwy po arabsku czy hebrajsku nie mieszają kierunku z tekstem strony
      li.append(name);
      list.append(li);
    }
    section.append(el("h2", null, g.title), el("p", "desc", g.text), list);
    return section;
  });
  root.replaceChildren(head, ...sections, el("footer", null, mode === "server" ? t.footer_server : t.footer_local));
}

function fail(root, key) {
  const lang = (navigator.language || "en").toLowerCase().startsWith("pl") ? "pl" : "en";
  document.documentElement.lang = lang;
  root.replaceChildren(el("p", "state", TEXTS[lang][key]));
}

async function main(root) {
  const f = parseFragment(location.hash);
  if (!f) return fail(root, "unreadable");
  if (!canInflate(globalThis)) return fail(root, "old_browser");
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
