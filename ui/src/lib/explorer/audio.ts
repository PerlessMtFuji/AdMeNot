// Odtwarzacz muzyki eksploratora: jeden element <audio> żyje dłużej niż okno podglądu (po jego zamknięciu
// gra dalej w mini-odtwarzaczu), a AnalyserNode daje poziomy 24 słupków. AudioContext wstrzykiwany
// (jsdom go nie ma; wtedy słupki stoją).

export const BARS = 24;

/** Minimalny kształt AudioContext, którego używamy (do atrapy w testach). */
export interface ContextLike {
  state: string;
  resume(): Promise<void>;
  createMediaElementSource(el: HTMLMediaElement): { connect(node: unknown): void };
  createAnalyser(): AnalyserLike;
  destination: unknown;
  close(): Promise<void>;
}

export interface AnalyserLike {
  fftSize: number;
  smoothingTimeConstant: number;
  readonly frequencyBinCount: number;
  getByteFrequencyData(out: Uint8Array<ArrayBuffer>): void;
  connect(node: unknown): void;
}

export type ContextFactory = () => ContextLike;

export function defaultContext(): ContextFactory | null {
  const g = globalThis as unknown as { AudioContext?: new () => ContextLike; webkitAudioContext?: new () => ContextLike };
  const Ctor = g.AudioContext ?? g.webkitAudioContext;
  return Ctor ? () => new Ctor() : null;
}

/** Widmo → `n` poziomów 0..1: dolne ~70% pasma (głos i muzyka), słupki o rosnącej szerokości. */
export function barLevels(data: ArrayLike<number>, n = BARS): number[] {
  const usable = Math.max(n, Math.floor(data.length * 0.7));
  const out: number[] = [];
  let from = 0;
  for (let i = 0; i < n; i++) {
    const to = Math.max(from + 1, Math.round(Math.pow((i + 1) / n, 1.6) * usable));
    let sum = 0;
    for (let j = from; j < to && j < data.length; j++) sum += data[j];
    out.push(Math.min(1, sum / (to - from) / 255));
    from = to;
  }
  return out;
}

export class AudioPlayer {
  readonly el: HTMLAudioElement;
  private ctx: ContextLike | null = null;
  private analyser: AnalyserLike | null = null;
  private buffer: Uint8Array<ArrayBuffer> | null = null;
  private wired = false;

  constructor(private readonly factory: ContextFactory | null = defaultContext()) {
    this.el = new Audio();
    this.el.preload = 'metadata';
    this.el.crossOrigin = 'anonymous';  // serwer mediów daje CORS; bez tego analizator widzi ciszę
  }

  /** Czy słupki mają skąd brać dane. */
  get analysable(): boolean {
    return this.factory !== null;
  }

  load(url: string): void {
    if (this.el.getAttribute('src') !== url) this.el.src = url;
  }

  async play(): Promise<void> {
    this.wire();
    try {
      if (this.ctx?.state === 'suspended') await this.ctx.resume();
      await this.el.play();
    } catch {
      // przerwane kolejnym load()/pause() albo autoodtwarzanie zablokowane — przycisk zostaje „odtwórz”
    }
  }

  pause(): void {
    this.el.pause();
  }

  /** Koniec odtwarzania: zwalnia źródło (strumień z telefonu przestaje płynąć). */
  stop(): void {
    this.el.pause();
    this.el.removeAttribute('src');
    this.el.load();
  }

  /** Bieżące poziomy słupków (zera, gdy brak analizatora). */
  levels(): number[] {
    if (!this.analyser || !this.buffer) return new Array<number>(BARS).fill(0);
    this.analyser.getByteFrequencyData(this.buffer);
    return barLevels(this.buffer);
  }

  dispose(): void {
    this.stop();
    void this.ctx?.close().catch(() => {});
    this.ctx = null;
    this.analyser = null;
  }

  /** `createMediaElementSource` wolno wywołać raz na element — przy pierwszym odtworzeniu (gest użytkownika). */
  private wire(): void {
    if (this.wired || !this.factory) return;
    this.wired = true;
    try {
      const ctx = this.factory();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 128;
      analyser.smoothingTimeConstant = 0.8;
      ctx.createMediaElementSource(this.el).connect(analyser);
      analyser.connect(ctx.destination);
      this.ctx = ctx;
      this.analyser = analyser;
      this.buffer = new Uint8Array(analyser.frequencyBinCount);
    } catch {
      this.ctx = null;  // bez analizatora muzyka gra normalnie
      this.analyser = null;
    }
  }
}
