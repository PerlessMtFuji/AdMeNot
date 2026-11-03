// Miniatury galerii: kolejka pobierania z priorytetem (widoczne kafle pierwsze), limitem równoległości
// i pamięcią podręczną adresów `blob:` (zwalnianych przy wypadaniu z pamięci).
import { SvelteMap, SvelteSet } from 'svelte/reactivity';

/** Ile miniatur trzymamy w pamięci (ok. 400 × 20 KB). */
export const THUMB_CACHE = 400;
/** Najdłużej czekamy na klatkę filmu — zawieszony strumień nie może blokować miejsca w kolejce. */
const VIDEO_TIMEOUT_MS = 15_000;
/** Szerokość klatki filmu na kaflu (miniatury zdjęć z serwera mają 256 px). */
const VIDEO_FRAME_PX = 256;

export interface Fetched {
  blob: Blob;
  /** Kolor dominujący `#rrggbb` (nagłówek `X-Color`); pusty, gdy nieznany. */
  color: string;
  /** Długość filmu w sekundach. */
  duration?: number;
}

export interface Thumb {
  src: string;
  color: string;
  duration?: number;
}

export type ThumbFetcher = (url: string, signal: AbortSignal) => Promise<Fetched>;

export class ThumbQueue {
  private readonly cache = new SvelteMap<string, Thumb>();
  private readonly bad = new SvelteSet<string>();
  private readonly pending = new Map<string, number>();
  private readonly running = new Map<string, AbortController>();
  private keep = new Set<string>();

  constructor(private readonly fetcher: ThumbFetcher, private readonly concurrency = 6) {}

  /** Miniatura z pamięci (reaktywnie w szablonie) albo `null`, gdy jeszcze jej nie ma. */
  get(url: string): Thumb | null {
    return this.cache.get(url) ?? null;
  }

  /** Pobieranie się nie udało (np. HEVC bez kodeka) — kafel pokazuje ikonę typu. */
  failed(url: string): boolean {
    return this.bad.has(url);
  }

  /** Dopisuje do kolejki; mniejszy `priority` = wcześniej. Ponowne `want` tylko podnosi priorytet. */
  want(url: string, priority: number): void {
    if (this.cache.has(url) || this.bad.has(url) || this.running.has(url)) return;
    const was = this.pending.get(url);
    if (was === undefined || priority < was) this.pending.set(url, priority);
    this.pump();
  }

  /** Zostawia w kolejce tylko `urls` (np. kafle widoczne po zmianie folderu lub przewinięciu);
   *  ich miniatury też są wyrzucane z pamięci jako ostatnie. */
  cancelAllExcept(urls: Set<string>): void {
    this.keep = urls;
    for (const url of [...this.pending.keys()]) if (!urls.has(url)) this.pending.delete(url);
    for (const [url, ctl] of [...this.running]) {
      if (urls.has(url)) continue;
      ctl.abort();
      this.running.delete(url);
    }
    this.pump();
  }

  /** Koniec eksploratora: wszystko anulowane, adresy `blob:` zwolnione. */
  clear(): void {
    this.cancelAllExcept(new Set());
    for (const thumb of this.cache.values()) URL.revokeObjectURL(thumb.src);
    this.cache.clear();
    this.bad.clear();
  }

  private pump(): void {
    while (this.running.size < this.concurrency && this.pending.size) {
      let next = '';
      let best = Infinity;
      for (const [url, priority] of this.pending) {
        if (priority < best) {
          best = priority;
          next = url;
        }
      }
      this.pending.delete(next);
      this.start(next);
    }
  }

  private start(url: string): void {
    const ctl = new AbortController();
    this.running.set(url, ctl);
    const mine = () => this.running.get(url) === ctl;
    this.fetcher(url, ctl.signal).then((r) => {
      if (!mine()) return;
      this.running.delete(url);
      this.store(url, { src: URL.createObjectURL(r.blob), color: r.color, duration: r.duration });
    }, () => {
      if (!mine()) return;
      this.running.delete(url);
      this.bad.add(url);
    }).finally(() => this.pump());
  }

  private store(url: string, thumb: Thumb): void {
    this.cache.set(url, thumb);
    while (this.cache.size > THUMB_CACHE) {
      // najstarsza spoza widocznych; gdy widoczne wypełniają całą pamięć — po prostu najstarsza
      let victim: string | undefined;
      for (const key of this.cache.keys()) {
        if (!this.keep.has(key)) {
          victim = key;
          break;
        }
      }
      victim ??= this.cache.keys().next().value!;
      URL.revokeObjectURL(this.cache.get(victim)!.src);
      this.cache.delete(victim);
    }
  }
}

/** Miniatura zdjęcia z serwera mediów; kolor dominujący w nagłówku `X-Color` (udostępniony przez CORS). */
export async function fetchThumb(url: string, signal: AbortSignal): Promise<Fetched> {
  const r = await fetch(url, { signal });
  if (!r.ok) throw new Error(`thumb ${r.status}`);
  return { blob: await r.blob(), color: r.headers.get('X-Color') ?? '' };
}

/** Klatka filmu: `<video crossorigin preload="metadata">` → canvas (serwer odsyła ACAO = nasz origin, więc
 *  canvas nie jest „skażony”). Brak kodeka (np. HEVC na części komputerów) — błąd, kafel pokazuje ikonę. */
export function videoFrame(url: string, signal: AbortSignal): Promise<Fetched> {
  return new Promise<Fetched>((resolve, reject) => {
    const video = document.createElement('video');
    let settled = false;
    const done = () => {
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener('abort', fail);
      video.removeAttribute('src');
      video.load();  // zwalnia połączenie ze strumieniem
    };
    const fail = () => {
      if (settled) return;
      done();
      reject(new Error('video frame'));
    };
    const timer = setTimeout(fail, VIDEO_TIMEOUT_MS);
    signal.addEventListener('abort', fail);
    video.crossOrigin = 'anonymous';
    video.preload = 'metadata';
    video.muted = true;
    video.addEventListener('error', fail);
    video.addEventListener('loadedmetadata', () => {
      // pierwsza klatka bywa czarna — bierzemy chwilę dalej, ale nie poza krótki film
      video.currentTime = Math.min(1, (video.duration || 0) / 4);
    });
    video.addEventListener('seeked', () => {
      const w = VIDEO_FRAME_PX;
      const h = Math.max(1, Math.round((w * video.videoHeight) / Math.max(1, video.videoWidth)));
      const canvas = document.createElement('canvas');
      Object.assign(canvas, { width: w, height: h });
      const ctx = canvas.getContext('2d');
      if (!ctx) return fail();
      ctx.drawImage(video, 0, 0, w, h);
      // kolor dominujący ≈ średnia: obraz zmniejszony do 1 piksela
      const dot = document.createElement('canvas');
      Object.assign(dot, { width: 1, height: 1 });
      dot.getContext('2d')?.drawImage(canvas, 0, 0, 1, 1);
      const [r, g, b] = dot.getContext('2d')?.getImageData(0, 0, 1, 1).data ?? [0, 0, 0];
      const color = `#${[r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')}`;
      const duration = video.duration;
      canvas.toBlob((blob) => {
        if (settled) return;
        done();
        if (blob) resolve({ blob, color, duration });
        else reject(new Error('video frame'));
      }, 'image/jpeg', 0.82);
    }, { once: true });
    video.src = url;
  });
}

/** Źródło kafla: miniatura z serwera (`…/thumb`) albo klatka z pliku filmu (`…/file`). */
export const mediaFetcher: ThumbFetcher = (url, signal) =>
  (new URL(url).pathname.endsWith('/thumb') ? fetchThumb : videoFrame)(url, signal);
