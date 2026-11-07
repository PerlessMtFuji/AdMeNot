import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MusicHold, RESUME_WAIT_MS, type HeldMusic } from './musichold';

describe('MusicHold', () => {
  let music: HeldMusic & { pause: ReturnType<typeof vi.fn>; play: ReturnType<typeof vi.fn> };
  let hold: MusicHold;

  beforeEach(() => {
    vi.useFakeTimers();
    music = {
      paused: false,
      source: 'a.mp3',
      pause: vi.fn(() => {
        music.paused = true;
      }),
      play: vi.fn(() => {
        music.paused = false;
      }),
    };
    hold = new MusicHold(music);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('wstrzymuje grającą muzykę i wznawia po 400 ms od zwolnienia', () => {
    hold.take();
    expect(music.pause).toHaveBeenCalledTimes(1);
    hold.release();
    vi.advanceTimersByTime(RESUME_WAIT_MS - 1);
    expect(music.play).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(music.play).toHaveBeenCalledTimes(1);
  });

  it('nie wznawia muzyki zapauzowanej wcześniej', () => {
    music.paused = true;
    hold.take();
    hold.release();
    vi.advanceTimersByTime(RESUME_WAIT_MS);
    expect(music.pause).not.toHaveBeenCalled();
    expect(music.play).not.toHaveBeenCalled();
  });

  it('kolejne take w przejeździe nie gubi stanu', () => {
    hold.take();
    hold.take();
    hold.release();
    vi.advanceTimersByTime(RESUME_WAIT_MS);
    expect(music.pause).toHaveBeenCalledTimes(1);
    expect(music.play).toHaveBeenCalledTimes(1);
  });

  it('nowy dymek z dźwiękiem w czasie oczekiwania anuluje wznowienie', () => {
    hold.take();
    hold.release();
    vi.advanceTimersByTime(100);
    hold.take();
    vi.advanceTimersByTime(1000);
    expect(music.play).not.toHaveBeenCalled();
  });

  it('nie wznawia, gdy zmienił się utwór albo muzyka już gra', () => {
    hold.take();
    hold.release();
    music.source = 'b.mp3';
    vi.advanceTimersByTime(RESUME_WAIT_MS);
    expect(music.play).not.toHaveBeenCalled();

    music.source = 'a.mp3';
    music.paused = false;
    hold.take();
    music.paused = false;
    hold.release();
    vi.advanceTimersByTime(RESUME_WAIT_MS);
    expect(music.play).not.toHaveBeenCalled();
  });

  it('forget porzuca wznowienie', () => {
    hold.take();
    hold.forget();
    hold.release();
    vi.advanceTimersByTime(RESUME_WAIT_MS);
    expect(music.play).not.toHaveBeenCalled();
  });
});
