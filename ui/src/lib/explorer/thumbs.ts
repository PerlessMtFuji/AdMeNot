// Miniatury galerii: kolejka pobierania z priorytetem (widoczne kafle pierwsze), limitem równoległości
// i pamięcią podręczną adresów `blob:` (zwalnianych przy wypadaniu z pamięci).
import { SvelteMap, SvelteSet } from 'svelte/reactivity';

/** Ile miniatur trzymamy w pamięci (ok. 1500 × 20 KB). */
export const THUMB_CACHE = 1500;
/** Najdłużej czekamy na klatkę filmu — zawieszony strumień nie może blokować miejsca w kolejce. */
const VIDEO_TIMEOUT_MS = 15_000;
/** Szerokość klatki filmu na kaflu (miniatury zdjęć z serwera mają 256 px). */
const VIDEO_FRAME_PX = 256;
/** Błąd przejściowy (sieć, kod HTTP, limit czasu) — ponawiamy w tle po 1, 2, 4 s; po tylu próbach kafel
 *  pokazuje ikonę, aż do zmiany folderu albo powrotu telefonu (`retryFailed`). */
const RETRIES = 3;
const RETRY_BASE_MS = 1000;

/** Pliku nie da się pokazać i ponawianie nic nie da (brak kodeka, nieczytelny obraz, „skażony” canvas). */
export class ThumbDecodeError extends Error {}

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
  /** Część `bad` po błędach przejściowych — `retryFailed` daje im kolejną szansę. */
  private readonly exhausted = new Set<string>();
  private readonly attempts = new Map<string, number>();
  private readonly waiting = new Map<string, ReturnType<typeof setTimeout>>();
  private priority = new Map<string, number>();
  private readonly pending = new Map<string, number>();
  private readonly running = new Map<string, AbortController>();
  private keep = new Set<string>();

  constructor(private readonly fetcher: ThumbFetcher, private readonly concurrency = 6) {}

  /** Miniatura z pamięci (reaktywnie w szablonie) albo `null`, gdy jeszcze jej nie ma. */
  get(url: string): Thumb | null {
    return this.cache.get(url) ?? null;
  }

  /** Miniatury nie będzie (np. HEVC bez kodeka albo telefon nie odpowiada mimo ponowień) — kafel
   *  pokazuje ikonę typu. */
  failed(url: string): boolean {
    return this.bad.has(url);
  }

  /** Dopisuje do kolejki; mniejszy `priority` = wcześniej. Ponowne `want` tylko podnosi priorytet. */
  want(url: string, priority: number): void {
    this.priority.set(url, Math.min(priority, this.priority.get(url) ?? Infinity));
    if (this.cache.has(url) || this.bad.has(url) || this.running.has(url) || this.waiting.has(url)) return;
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

  /** Cały plan pobierania naraz (galeria, po każdym przewinięciu): `wanted` zastępuje kolejkę razem z priorytetami,
   *  więc kafel, który wyjechał z okna, nie wyprzedza nowych; reszta jest anulowana. */
  plan(wanted: readonly (readonly [string, number])[]): void {
    this.priority = new Map(wanted);
    this.keep = new Set(this.priority.keys());
    for (const [url, ctl] of [...this.running]) {
      if (this.keep.has(url)) continue;
      ctl.abort();
      this.running.delete(url);
    }
    this.pending.clear();
    for (const [url, priority] of this.priority) {
      if (!this.cache.has(url) && !this.bad.has(url) && !this.running.has(url) && !this.waiting.has(url)) this.pending.set(url, priority);
    }
    this.pump();
  }

  /** Nowa szansa dla miniatur, które zawiodły przejściowo (zmiana folderu, telefon wrócił). Widoczne
   *  ruszają od razu. */
  retryFailed(): void {
    for (const timer of this.waiting.values()) clearTimeout(timer);
    this.waiting.clear();
    this.attempts.clear();
    for (const url of this.exhausted) this.bad.delete(url);
    this.exhausted.clear();
    for (const url of this.keep) this.want(url, this.priority.get(url) ?? 0);
  }

  /** `<img>` nie zdekodował pobranej miniatury — zwalnia ją i zostawia ikonę na stałe. */
  broken(url: string): void {
    const thumb = this.cache.get(url);
    if (thumb) URL.revokeObjectURL(thumb.src);
    this.cache.delete(url);
    this.bad.add(url);
  }

  /** Koniec eksploratora: wszystko anulowane, adresy `blob:` zwolnione. */
  clear(): void {
    this.cancelAllExcept(new Set());
    this.retryFailed();
    for (const thumb of this.cache.values()) URL.revokeObjectURL(thumb.src);
    this.cache.clear();
    this.bad.clear();
    this.priority.clear();
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
    }, (e: unknown) => {
      if (!mine()) return;
      this.running.delete(url);
      this.fail(url, e instanceof ThumbDecodeError);
    }).finally(() => this.pump());
  }

  private fail(url: string, permanent: boolean): void {
    const n = (this.attempts.get(url) ?? 0) + 1;
    this.attempts.set(url, n);
    if (permanent || n > RETRIES) {
      if (!permanent) this.exhausted.add(url);
      this.bad.add(url);
      return;
    }
    this.waiting.set(url, setTimeout(() => {
      this.waiting.delete(url);
      if (this.keep.has(url)) this.want(url, this.priority.get(url) ?? 0);
    }, RETRY_BASE_MS * 2 ** (n - 1)));
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
      signal.removeEventListener('abort', onAbort);
      video.removeAttribute('src');
      video.load();  // zwalnia połączenie ze strumieniem
    };
    const fail = (e: Error = new Error('video frame')) => {
      if (settled) return;
      done();
      reject(e);
    };
    const onAbort = () => fail();
    const timer = setTimeout(onAbort, VIDEO_TIMEOUT_MS);
    signal.addEventListener('abort', onAbort);
    video.crossOrigin = 'anonymous';
    video.preload = 'metadata';
    video.muted = true;
    // brak kodeka / nieobsługiwany format — na stałe; błąd sieci — przejściowy
    video.addEventListener('error', () => {
      const code = video.error?.code;
      const permanent = code === MediaError.MEDIA_ERR_DECODE || code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED;
      fail(permanent ? new ThumbDecodeError('video codec') : new Error('video network'));
    });
    video.addEventListener('loadedmetadata', () => {
      // dźwięk jest, a obrazu okno nie zdekoduje (np. MPEG-4 Part 2): lepsza ikona niż czarny kafel
      if (!video.videoWidth) {
        fail(new ThumbDecodeError('no picture'));
        return;
      }
      // pierwsza klatka bywa czarna — bierzemy chwilę dalej, ale nie poza krótki film
      video.currentTime = Math.min(1, (video.duration || 0) / 4);
    });
    video.addEventListener('seeked', () => {
      try {
        grab();
      } catch (e) {
        // np. „skażony” canvas (SecurityError) — ponawianie nic nie zmieni
        fail(new ThumbDecodeError(String(e)));
      }
    }, { once: true });
    const grab = () => {
      const w = VIDEO_FRAME_PX;
      const h = Math.max(1, Math.round((w * video.videoHeight) / Math.max(1, video.videoWidth)));
      const canvas = document.createElement('canvas');
      Object.assign(canvas, { width: w, height: h });
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('no 2d context');
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
        else reject(new ThumbDecodeError('video frame'));
      }, 'image/jpeg', 0.82);
    };
    video.src = url;
  });
}

/** Źródło kafla: miniatura z serwera (`…/thumb`) albo klatka z pliku filmu (`…/file`). */
export const mediaFetcher: ThumbFetcher = (url, signal) =>
  (new URL(url).pathname.endsWith('/thumb') ? fetchThumb : videoFrame)(url, signal);
