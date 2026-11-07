import type { EntryView } from '../types';

/** Tyle kursor musi stać na pliku, zanim wyskoczy pierwszy dymek. */
export const PEEK_DELAY_MS = 300;
/** Tyle kursor może być poza plikami, a przejazd (kolejne dymki bez opóźnienia) trwa dalej. */
export const PEEK_SWEEP_MS = 180;
/** Co przeglądarka pokaże w <img> (HEIC i RAW — nie). */
export const NATIVE_IMAGE: readonly string[] = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'avif', 'svg'];
/** Większych zdjęć nie trzymamy w pamięci na zapas ani nie pokazujemy w dymku w całości. */
export const PREFETCH_MAX = 40 * 1024 * 1024;

export type PeekKind = 'photo' | 'video' | 'audio' | 'pdf' | 'text';

/** Co dymek może pokazać dla pliku (zgodnie z pełnym podglądem); `null` — dymka nie ma. */
export function peekKind(e: EntryView): PeekKind | null {
  if (e.kind !== 'file') return null;
  const ext = e.ext.toLowerCase();
  if (e.type === 'image') {
    if (!e.url || !NATIVE_IMAGE.includes(ext)) return null;
    return e.size <= PREFETCH_MAX || e.thumb ? 'photo' : null;
  }
  if (e.type === 'video') return e.url ? 'video' : null;
  if (e.type === 'audio') return e.url ? 'audio' : null;
  if (ext === 'pdf' && e.url) return 'pdf';
  // Tekst idzie mostkiem, adres serwera mediów nie jest potrzebny.
  return e.type === 'text' ? 'text' : null;
}

/** Wymiary dymka (ze stopką). PDF: cała strona A4 ze stopką mieści się w najmniejszym oknie (663 px wysokości). */
export function peekSize(kind: PeekKind): { w: number; h: number } {
  switch (kind) {
    case 'photo':
    case 'video':
      return { w: 440, h: 330 };
    case 'pdf':
      return { w: 424, h: 640 };
    case 'text':
      return { w: 440, h: 460 };
    case 'audio':
      return { w: 320, h: 210 };
  }
}

export type PeekRect = { left: number; top: number; right: number; bottom: number };

const GAP = 12;
const MARGIN = 8;

/** Dymek obok kafla: po prawej, a bez miejsca — po lewej; zawsze cały w oknie. */
export function placeBubble(
  tile: PeekRect,
  size: { w: number; h: number },
  win: { w: number; h: number },
): { x: number; y: number } {
  let x = tile.right + GAP;
  if (x + size.w + MARGIN > win.w) x = tile.left - GAP - size.w;
  x = Math.max(MARGIN, Math.min(x, win.w - size.w - MARGIN));
  const y = (tile.top + tile.bottom) / 2 - size.h / 2;
  return { x, y: Math.max(MARGIN, Math.min(y, win.h - size.h - MARGIN)) };
}

/**
 * Czas dymka: pierwszy po `PEEK_DELAY_MS`, kolejne w przejeździe od razu, przejazd kończy się
 * po `PEEK_SWEEP_MS` poza plikami. `dismiss` (klik) zamyka i trzyma zamknięte, dopóki kursor
 * nie zjedzie z pliku; `hold` (przycisk myszy wciśnięty) zamyka i wstrzymuje wszystko.
 */
export class PeekTimer {
  private current: string | null = null;
  private dismissed: string | null = null;
  private shown = false;
  private sweeping = false;
  private held = false;
  private delay: ReturnType<typeof setTimeout> | undefined;
  private sweep: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly show: (path: string) => void, private readonly hide: () => void) {}

  hover(path: string | null): void {
    if (path === this.current) return;
    this.current = path;
    clearTimeout(this.delay);
    if (path === null) {
      this.dismissed = null;
      if (this.sweeping) {
        clearTimeout(this.sweep);
        this.sweep = setTimeout(() => this.endSweep(), PEEK_SWEEP_MS);
      }
      return;
    }
    if (path !== this.dismissed) this.dismissed = null;
    if (this.held || path === this.dismissed) return;
    clearTimeout(this.sweep);
    if (this.sweeping) this.open(path);
    else this.delay = setTimeout(() => this.open(path), PEEK_DELAY_MS);
  }

  dismiss(): void {
    this.dismissed = this.current;
    this.close();
  }

  hold(on: boolean): void {
    if (on === this.held) return;  // drugie puszczenie założyłoby drugi licznik, którego nikt już nie skasuje
    this.held = on;
    if (on) {
      this.close();
    } else if (this.current !== null && this.current !== this.dismissed) {
      const path = this.current;
      this.delay = setTimeout(() => this.open(path), PEEK_DELAY_MS);
    }
  }

  destroy(): void {
    clearTimeout(this.delay);
    clearTimeout(this.sweep);
  }

  private open(path: string): void {
    this.shown = true;
    this.sweeping = true;
    this.show(path);
  }

  private endSweep(): void {
    this.sweeping = false;
    if (this.shown) {
      this.shown = false;
      this.hide();
    }
  }

  private close(): void {
    clearTimeout(this.delay);
    clearTimeout(this.sweep);
    this.sweeping = false;
    if (this.shown) {
      this.shown = false;
      this.hide();
    }
  }
}
