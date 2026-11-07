import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { EntryView } from '../types';
import { fitBubble, PeekTimer, peekKind, peekSize, placeBubble } from './peek';

describe('PeekTimer', () => {
  let show: ReturnType<typeof vi.fn<(path: string, sweep: boolean) => void>>;
  let hide: ReturnType<typeof vi.fn<() => void>>;
  let t: PeekTimer;

  beforeEach(() => {
    vi.useFakeTimers();
    show = vi.fn<(path: string, sweep: boolean) => void>();
    hide = vi.fn<() => void>();
    t = new PeekTimer(show, hide);
  });
  afterEach(() => {
    t.destroy();
    vi.useRealTimers();
  });

  it('pierwszy dymek po 300 ms, następny w przejeździe od razu i z oznaczeniem przejazdu', () => {
    t.hover('a'); vi.advanceTimersByTime(299); expect(show).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1); expect(show).toHaveBeenLastCalledWith('a', false);
    t.hover(null); vi.advanceTimersByTime(100); t.hover('b');
    expect(show).toHaveBeenLastCalledWith('b', true); expect(hide).not.toHaveBeenCalled();
  });

  it('po 180 ms poza plikami przejazd się kończy', () => {
    t.hover('a'); vi.advanceTimersByTime(300);
    t.hover(null); vi.advanceTimersByTime(179); expect(hide).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1); expect(hide).toHaveBeenCalledTimes(1);
    show.mockClear();
    t.hover('b'); vi.advanceTimersByTime(299); expect(show).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1); expect(show).toHaveBeenLastCalledWith('b', false);
  });

  it('szybki przejazd przed upływem opóźnienia nic nie otwiera', () => {
    t.hover('a'); vi.advanceTimersByTime(100);
    t.hover('b'); vi.advanceTimersByTime(100);
    t.hover('c'); vi.advanceTimersByTime(100);
    t.hover(null); vi.advanceTimersByTime(1000);
    expect(show).not.toHaveBeenCalled();
  });

  it('dismiss zamyka i ten sam plik nie wraca, dopóki kursor z niego nie zjedzie', () => {
    t.hover('a'); vi.advanceTimersByTime(300); show.mockClear();
    t.dismiss(); expect(hide).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1000); expect(show).not.toHaveBeenCalled();
    t.hover(null); t.hover('a'); vi.advanceTimersByTime(300);
    expect(show).toHaveBeenLastCalledWith('a', false);
  });

  it('hold zamyka, a po puszczeniu plik pod kursorem czeka pełne opóźnienie', () => {
    t.hover('a'); vi.advanceTimersByTime(300); show.mockClear();
    t.hold(true); expect(hide).toHaveBeenCalledTimes(1);
    t.hover('b'); vi.advanceTimersByTime(1000); expect(show).not.toHaveBeenCalled();
    t.hold(false); vi.advanceTimersByTime(299); expect(show).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1); expect(show).toHaveBeenLastCalledWith('b', false);
  });

  it('dwa razy hold(false) nie zostawia drugiego licznika', () => {
    t.hover('a'); t.hold(true);
    t.hold(false); t.hold(false);
    vi.advanceTimersByTime(1000);
    expect(show).toHaveBeenCalledTimes(1);
  });

  it('hold nie otwiera ponownie pliku zamkniętego przez dismiss', () => {
    t.hover('a'); vi.advanceTimersByTime(300); show.mockClear();
    t.dismiss(); t.hold(true); t.hold(false);
    vi.advanceTimersByTime(1000); expect(show).not.toHaveBeenCalled();
    t.hover(null); t.hover('a'); vi.advanceTimersByTime(300);
    expect(show).toHaveBeenLastCalledWith('a', false);
  });

  it('destroy odwołuje oczekujące zegary', () => {
    t.hover('a'); t.destroy(); vi.advanceTimersByTime(1000);
    expect(show).not.toHaveBeenCalled();
  });
});

describe('placeBubble', () => {
  const win = { w: 1000, h: 800 };
  it('po prawej, a bez miejsca po lewej, zawsze w oknie', () => {
    expect(placeBubble({ left: 10, top: 100, right: 120, bottom: 210 }, { w: 400, h: 300 }, win))
      .toEqual({ x: 132, y: 8 });
    expect(placeBubble({ left: 800, top: 600, right: 910, bottom: 710 }, { w: 400, h: 300 }, win))
      .toEqual({ x: 388, y: 492 });
  });
  it('okno węższe niż dymek: x = 8', () => {
    expect(placeBubble({ left: 10, top: 100, right: 120, bottom: 210 }, { w: 400, h: 300 }, { w: 300, h: 800 }).x).toBe(8);
  });
});

describe('fitBubble', () => {
  const win = { w: 1280, h: 800 };

  it('film 9:16 wypełnia wysokość PDF zamiast stać w pasach', () => {
    expect(fitBubble(9 / 16, win)).toEqual({ w: 340, h: 640 });
  });
  it('zdjęcia 3:4, 4:3 i kwadrat mają szerokość zwykłego dymka', () => {
    expect(fitBubble(3 / 4, win)).toEqual({ w: 440, h: 623 });
    expect(fitBubble(4 / 3, win)).toEqual({ w: 440, h: 366 });
    expect(fitBubble(1, { w: 1280, h: 1000 })).toEqual({ w: 440, h: 476 });
  });
  it('małe okno ścina dymek, a proporcje zostają', () => {
    expect(fitBubble(9 / 16, { w: 1010, h: 400 })).toEqual({ w: 240, h: 384 });
    expect(fitBubble(16 / 9, { w: 300, h: 800 })).toEqual({ w: 284, h: 196 });
  });
  it('skrajne proporcje nie zgniatają stopki i nie wychodzą poza okno', () => {
    expect(fitBubble(1 / 20, win)).toEqual({ w: 240, h: 640 });
    expect(fitBubble(20, win)).toEqual({ w: 440, h: 156 });
  });
});

describe('peekKind', () => {
  const e = (o: Partial<EntryView>): EntryView => ({
    name: 'f', path: '/f', kind: 'file', size: 1000, mtime: 0, label: null, locked: false,
    type: 'other', ext: '', thumb: null, url: 'http://x/f', ...o,
  } as EntryView);

  it('rozpoznaje rodzaj treści dymka', () => {
    expect(peekKind(e({ type: 'image', ext: 'JPG' }))).toBe('photo');
    expect(peekKind(e({ type: 'image', ext: 'heic' }))).toBeNull();
    expect(peekKind(e({ type: 'image', ext: 'jpg', url: null }))).toBeNull();
    expect(peekKind(e({ type: 'video', ext: 'mp4' }))).toBe('video');
    expect(peekKind(e({ type: 'audio', ext: 'mp3' }))).toBe('audio');
    expect(peekKind(e({ type: 'video', ext: 'mp4', url: null }))).toBeNull();
    expect(peekKind(e({ type: 'doc', ext: 'pdf' }))).toBe('pdf');
    expect(peekKind(e({ type: 'doc', ext: 'pdf', url: null }))).toBeNull();
    expect(peekKind(e({ type: 'text', ext: 'txt', url: null }))).toBe('text');
    expect(peekKind(e({ kind: 'dir', type: 'other' }))).toBeNull();
    expect(peekKind(e({ type: 'apk', ext: 'apk' }))).toBeNull();
  });
  it('zdjęcie 50 MB tylko z miniaturą', () => {
    const big = 50 * 1024 * 1024;
    expect(peekKind(e({ type: 'image', ext: 'jpg', size: big }))).toBeNull();
    expect(peekKind(e({ type: 'image', ext: 'jpg', size: big, thumb: 'http://x/t' }))).toBe('photo');
  });
  it('rozmiary dymków', () => {
    expect(peekSize('photo')).toEqual({ w: 440, h: 330 });
    expect(peekSize('audio')).toEqual({ w: 320, h: 210 });
    expect(peekSize('text')).toEqual({ w: 440, h: 460 });
    expect(peekSize('pdf')).toEqual({ w: 424, h: 640 });
  });
});
