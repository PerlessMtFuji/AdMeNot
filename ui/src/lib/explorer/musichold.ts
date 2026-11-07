/** Tyle po zwolnieniu czekamy z wznowieniem muzyki; pokrywa dwuklik (zamknięcie dymka i otwarcie podglądu). */
export const RESUME_WAIT_MS = 400;

/** To, czego potrzebujemy od odtwarzacza muzyki w tle. */
export type HeldMusic = {
  paused: boolean;
  source: string | null;
  pause(): void;
  play(): void;
};

/**
 * Wstrzymuje muzykę w tle, gdy dymek gra dźwięk, i wznawia ją po `RESUME_WAIT_MS` od zwolnienia.
 * Wznawia tylko to, co sami zatrzymaliśmy, i tylko ten sam utwór. `forget` (otwarty pełny podgląd,
 * który przejmuje dźwięk) porzuca wznowienie.
 */
export class MusicHold {
  private held = false;
  private source: string | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly music: HeldMusic) {}

  take(): void {
    clearTimeout(this.timer);
    if (this.held || this.music.paused || this.music.source === null) return;
    this.held = true;
    this.source = this.music.source;
    this.music.pause();
  }

  release(): void {
    if (!this.held) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.resume(), RESUME_WAIT_MS);
  }

  forget(): void {
    clearTimeout(this.timer);
    this.held = false;
    this.source = null;
  }

  private resume(): void {
    const same = this.music.paused && this.music.source === this.source;
    this.held = false;
    this.source = null;
    if (same) this.music.play();
  }
}
