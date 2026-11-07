import { cleanup, fireEvent, render } from '@testing-library/svelte';
import { flushSync, tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { PEEK_DELAY_MS, PREFETCH_MAX } from '../../lib/explorer/peek';
import { RESUME_WAIT_MS } from '../../lib/explorer/musichold';
import { ThumbQueue } from '../../lib/explorer/thumbs';
import type { ExplorerController } from '../../lib/explorer/controller';
import type { EntryView } from '../../lib/types';
import { setupCtl } from '../../test-utils';
import PeekBubble from './PeekBubble.svelte';

const { players, pdf } = vi.hoisted(() => ({
  players: [] as { el: HTMLAudioElement; calls: string[]; onerror: (() => void) | null; analysable: boolean }[],
  pdf: { draw: null as unknown as Mock<(...args: unknown[]) => Promise<void>>, close: null as unknown as Mock<() => void> },
}));

vi.mock('../../lib/explorer/audio', async (original) => ({
  ...(await original<typeof import('../../lib/explorer/audio')>()),
  AudioPlayer: class {
    el = document.createElement('audio');
    calls: string[] = [];
    onerror: (() => void) | null = null;
    analysable = false;
    constructor() { players.push(this); }
    load(url: string) { this.calls.push(`load ${url}`); this.el.setAttribute('src', url); }
    async play() { this.calls.push('play'); return true; }
    pause() { this.calls.push('pause'); }
    stop() { this.calls.push('stop'); this.el.removeAttribute('src'); }
    levels() { return []; }
    dispose() { this.calls.push('dispose'); }
  },
}));

vi.mock('../../lib/explorer/pdf', () => ({
  drawFirstPage: (...args: unknown[]) => pdf.draw(...args),
  closePdfWorker: () => pdf.close(),
}));

const entry = (name: string, type: EntryView['type'], ext: string, over: Partial<EntryView> = {}): EntryView => ({
  name, path: `/sdcard/Test/${name}`, kind: 'file', size: 2048, mtime: 1790413200, label: null, locked: false,
  type, ext, thumb: null, url: `http://127.0.0.1:1/${encodeURIComponent(name)}`, ...over,
});

const PHOTO = entry('a.jpg', 'image', 'jpg', { thumb: 'http://127.0.0.1:1/thumb-a' });
const PHOTO2 = entry('b.jpg', 'image', 'jpg');
const HEIC = entry('c.heic', 'image', 'heic');
const MOVIE = entry('film.mp4', 'video', 'mp4', { thumb: 'http://127.0.0.1:1/thumb-film' });
const SONG = entry('utwor.mp3', 'audio', 'mp3');
const SONG2 = entry('drugi.mp3', 'audio', 'mp3');
const DOC = entry('faktura.pdf', 'doc', 'pdf');
const NOTE = entry('notatka.txt', 'text', 'txt');
const DIR: EntryView = { ...entry('Folder', 'other', ''), kind: 'dir' };
const ODD = entry(`dziwny "plik" o'nazwie zażółć gęślą jaźń.jpg`, 'image', 'jpg');
const ALL = [PHOTO, PHOTO2, HEIC, MOVIE, SONG, SONG2, DOC, NOTE, DIR, ODD];

const bubble = () => document.querySelector<HTMLElement>('[data-testid="peek"]');

/** Sygnał zdarzenia wskaźnika: jsdom nie zawsze ma PointerEvent, a nas interesuje tylko `pointerType`. */
function pointer(type: string, pointerType: string, clientX = 0): void {
  window.dispatchEvent(Object.assign(new Event(type), { pointerType, clientX }));
}

describe('PeekBubble', () => {
  let ex: ExplorerController;
  let bridge: Awaited<ReturnType<typeof setupCtl>>['bridge'];
  let view: ReturnType<typeof render>;
  let load: ReturnType<typeof vi.spyOn>;

  /** Kafel na ekranie: dymek szuka go po `data-path`. */
  function tile(e: EntryView, left = 100): HTMLElement {
    const el = document.createElement('div');
    el.dataset.path = e.path;
    el.getBoundingClientRect = () => ({ left, right: left + 100, top: 100, bottom: 200, x: left, y: 100, width: 100, height: 100 }) as DOMRect;
    document.body.append(el);
    return el;
  }

  /** Najechanie i pełne opóźnienie. */
  async function hover(e: EntryView | null): Promise<void> {
    ex.state.hover = e?.path ?? null;
    flushSync();
    vi.advanceTimersByTime(PEEK_DELAY_MS);
    await settle();
  }

  async function settle(): Promise<void> {
    flushSync();
    await tick();
    flushSync();
  }

  /** Muzyka gra w tle; `calls` to zapis wywołań na głównym odtwarzaczu, `paused` ustawia stan elementu. */
  function backgroundMusic() {
    ex.state.playing = { path: '/sdcard/x.mp3', title: 'x', cover: null, url: 'http://127.0.0.1:1/x.mp3' };
    const music = ex.audio;
    music.el.setAttribute('src', 'http://127.0.0.1:1/x.mp3');
    const paused = (value: boolean) => Object.defineProperty(music.el, 'paused', { configurable: true, value });
    paused(false);
    return { calls: (music as unknown as { calls: string[] }).calls, paused, music };
  }

  /** Najechanie, zjazd z pliku i powrót przed końcem przejazdu. */
  async function backAgain(e: EntryView): Promise<void> {
    await hover(e);
    ex.state.hover = null;
    flushSync();
    vi.advanceTimersByTime(100);
    ex.state.hover = e.path;
    await settle();
    vi.advanceTimersByTime(1000);
    await settle();
  }

  beforeEach(async () => {
    players.length = 0;
    pdf.draw = vi.fn(async () => {});
    pdf.close = vi.fn();
    const env = await setupCtl('explorer');
    bridge = env.bridge;
    ex = env.ctl.explorer;
    ex.state.entries = ALL;
    for (const e of ALL) tile(e);
    vi.spyOn(window.HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    vi.spyOn(window.HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
    load = vi.spyOn(window.HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
    vi.useFakeTimers();
    view = render(PeekBubble, { props: { ex, thumbs: new ThumbQueue(async () => { throw new Error('bez sieci'); }) } });
    flushSync();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('pokazuje dymek dla s.hover po opóźnieniu, ze stopką i rozmiarem', async () => {
    ex.state.hover = PHOTO.path;
    flushSync();
    vi.advanceTimersByTime(PEEK_DELAY_MS - 1);
    await settle();
    expect(bubble()).toBeNull();
    vi.advanceTimersByTime(1);
    await settle();
    expect(bubble()?.textContent).toContain('a.jpg');
    expect(bubble()?.textContent).toContain('2');
    expect(bubble()?.getAttribute('aria-hidden')).toBe('true');
    expect(bubble()?.className).toContain('pointer-events-none');
    expect(bubble()?.parentElement).toBe(document.body);
    expect(bubble()?.querySelector('img')?.getAttribute('src')).toBe(PHOTO.thumb);
  });

  it('zdjęcie wyostrza się po wczytaniu pełnego pliku, a duże zostaje przy miniaturze', async () => {
    await hover(PHOTO);
    const full = bubble()!.querySelector<HTMLImageElement>(`img[src="${PHOTO.url}"]`)!;
    expect(full.className).toContain('opacity-0');
    await fireEvent.load(full);
    expect(full.className).not.toContain('opacity-0');
    await hover(null);
    vi.advanceTimersByTime(1000);
    await settle();

    const big = { ...PHOTO, path: '/sdcard/Test/duze.jpg', size: PREFETCH_MAX + 1 };
    ex.state.entries = [...ALL, big];
    tile(big);
    await hover(big);
    expect(bubble()!.querySelectorAll('img')).toHaveLength(1);
    expect(bubble()!.querySelector('img')?.getAttribute('src')).toBe(PHOTO.thumb);
  });

  it('zamknięcie dymka przerywa pobieranie pełnego zdjęcia', async () => {
    await hover(PHOTO);
    const full = bubble()!.querySelector<HTMLImageElement>(`img[src="${PHOTO.url}"]`)!;
    await fireEvent.mouseDown(window);
    await settle();
    expect(bubble()).toBeNull();
    expect(full.hasAttribute('src')).toBe(false);
  });

  it('nie otwiera się przy s.peek === false, dla folderu, HEIC ani po dotyku', async () => {
    ex.state.peek = false;
    await hover(PHOTO);
    expect(bubble()).toBeNull();
    await hover(null);
    ex.state.peek = true;
    await hover(DIR);
    expect(bubble()).toBeNull();
    await hover(HEIC);
    expect(bubble()).toBeNull();
    await hover(null);
    pointer('pointerdown', 'touch');
    await hover(PHOTO);
    expect(bubble()).toBeNull();
    await hover(null);
    pointer('pointermove', 'mouse');
    await hover(PHOTO);
    expect(bubble()).not.toBeNull();
  });

  it('folder i HEIC liczą się jak miejsce poza plikami: dymek gaśnie po końcu przejazdu', async () => {
    await hover(NOTE);
    ex.state.hover = DIR.path;
    await settle();
    vi.advanceTimersByTime(100);
    await settle();
    expect(bubble()?.textContent).toContain('notatka.txt');
    ex.state.hover = HEIC.path;
    await settle();
    vi.advanceTimersByTime(79);
    await settle();
    expect(bubble()?.textContent).toContain('notatka.txt');
    vi.advanceTimersByTime(1);
    await settle();
    expect(bubble()).toBeNull();
  });

  it.each([
    ['mousedown', () => fireEvent.mouseDown(window)],
    ['keydown', () => fireEvent.keyDown(window, { key: 'a' })],
    ['wheel', () => fireEvent.wheel(window)],
    ['dragstart', () => fireEvent.dragStart(window)],
    ['s.path', async () => { ex.state.path = '/sdcard/Inny'; }],
    ['s.offline', async () => { ex.state.offline = true; }],
    ['s.preview', async () => { ex.state.preview = PHOTO.path; }],
    ['s.problems', async () => { ex.state.problems = { kind: 'to_phone', list: [] }; }],
    ['blur okna', () => fireEvent.blur(window)],
    ['opuszczenie dokumentu', () => fireEvent.mouseLeave(document.documentElement)],
  ])('zamyka się przy %s', async (_name, act) => {
    await hover(NOTE);
    expect(bubble()).not.toBeNull();
    await act();
    await settle();
    expect(bubble()).toBeNull();
  });

  it('blur pola tekstowego nie jest blurem okna', async () => {
    await hover(NOTE);
    const input = document.body.appendChild(document.createElement('input'));
    await fireEvent.blur(input);
    await settle();
    expect(bubble()).not.toBeNull();
  });

  it('klik zamyka, a plik pod kursorem nie wraca po puszczeniu przycisku', async () => {
    await hover(NOTE);
    await fireEvent.mouseDown(window);
    await settle();
    await fireEvent.mouseUp(window);
    await settle();
    vi.advanceTimersByTime(1000);
    await settle();
    expect(bubble()).toBeNull();
  });

  it('wciśnięty przycisk wstrzymuje nowy dymek do puszczenia', async () => {
    await fireEvent.mouseDown(window);
    await hover(NOTE);
    expect(bubble()).toBeNull();
    await fireEvent.mouseUp(window);
    await settle();
    vi.advanceTimersByTime(PEEK_DELAY_MS);
    await settle();
    expect(bubble()).not.toBeNull();
  });

  it('po przewijaniu wraca dla pliku pod kursorem po 120 ms ciszy i zwykłym opóźnieniu', async () => {
    await hover(NOTE);
    await fireEvent.wheel(window);
    await settle();
    expect(bubble()).toBeNull();
    vi.advanceTimersByTime(100);
    await fireEvent.scroll(document.body);  // przewijanie trwa: cisza liczy się od nowa
    await settle();
    vi.advanceTimersByTime(119);
    await settle();
    ex.state.hover = PHOTO.path;  // pod nieruchomym kursorem przesunął się inny plik
    flushSync();
    vi.advanceTimersByTime(1);
    await settle();
    vi.advanceTimersByTime(PEEK_DELAY_MS - 1);
    await settle();
    expect(bubble()).toBeNull();
    vi.advanceTimersByTime(1);
    await settle();
    expect(bubble()?.textContent).toContain('a.jpg');
  });

  it('plik znika z s.byPath: dymek się zamyka', async () => {
    await hover(NOTE);
    ex.state.entries = ALL.filter((e) => e !== NOTE);
    await settle();
    expect(bubble()).toBeNull();
  });

  it('kafel znika z DOM przy otwartym dymku: dymek się zamyka bez błędu', async () => {
    await hover(NOTE);
    expect(bubble()).not.toBeNull();
    document.querySelector(`[data-path="${CSS.escape(NOTE.path)}"]`)?.remove();
    await settle();
    expect(bubble()).toBeNull();
    expect(ex.state.error).toBeNull();
    vi.advanceTimersByTime(1000);
    await settle();
    expect(bubble()).toBeNull();
  });

  it('kafla nie ma w DOM przy otwarciu: dymka nie ma', async () => {
    document.querySelector(`[data-path="${CSS.escape(NOTE.path)}"]`)?.remove();
    await hover(NOTE);
    expect(bubble()).toBeNull();
  });

  it('film i muzyka biorą MusicHold, zdjęcie nie; zamknięcie zwalnia źródło', async () => {
    ex.state.playing = { path: '/sdcard/x.mp3', title: 'x', cover: null, url: 'http://127.0.0.1:1/x.mp3' };
    const music = ex.audio;
    music.el.setAttribute('src', 'http://127.0.0.1:1/x.mp3');
    Object.defineProperty(music.el, 'paused', { configurable: true, value: false });
    const calls = (music as unknown as { calls: string[] }).calls;

    await hover(PHOTO);
    await hover(null);
    vi.advanceTimersByTime(1000);
    await settle();
    expect(calls).toEqual([]);

    await hover(MOVIE);
    const video = bubble()!.querySelector('video')!;
    expect(video.autoplay).toBe(true);
    expect(video.getAttribute('poster')).toBe(MOVIE.thumb);
    expect(calls).toEqual(['pause']);
    Object.defineProperty(music.el, 'paused', { configurable: true, value: true });

    load.mockClear();
    ex.state.hover = null;
    flushSync();
    vi.advanceTimersByTime(180);
    await settle();
    expect(bubble()).toBeNull();
    expect(video.hasAttribute('src')).toBe(false);
    expect(load).toHaveBeenCalled();
    expect(calls).toEqual(['pause']);  // muzyka czeka chwilę: dwuklik mógł otworzyć podgląd
    vi.advanceTimersByTime(RESUME_WAIT_MS);
    expect(calls).toEqual(['pause', 'play']);

    Object.defineProperty(music.el, 'paused', { configurable: true, value: false });
    await hover(SONG);
    expect(calls).toEqual(['pause', 'play', 'pause']);
    const own = players.find((p) => p !== (music as unknown))!;
    expect(own.calls).toEqual([`load ${SONG.url}`, 'play']);
    await hover(null);
    vi.advanceTimersByTime(1000);
    await settle();
    expect(own.calls.at(-1)).toBe('stop');
  });

  it('bez grającej muzyki dymek nie tworzy głównego odtwarzacza i ma jeden własny', async () => {
    await hover(SONG);
    ex.state.hover = SONG2.path;  // przejazd: następny plik od razu
    await settle();
    expect(players).toHaveLength(1);
    expect(players[0].calls).toEqual([`load ${SONG.url}`, 'play', 'stop', `load ${SONG2.url}`, 'play']);
    expect(players[0].el.getAttribute('src')).toBe(SONG2.url);
  });

  it('zmiana utworu w tle nie restartuje dźwięku dymka', async () => {
    await hover(SONG);
    const before = players[0].calls.length;
    ex.state.playing = { path: '/sdcard/x.mp3', title: 'x', cover: null, url: 'http://127.0.0.1:1/x.mp3' };
    await settle();
    expect(players[0].calls).toHaveLength(before);
  });

  it('otwarcie podglądu woła forget', async () => {
    ex.state.playing = { path: '/sdcard/x.mp3', title: 'x', cover: null, url: 'http://127.0.0.1:1/x.mp3' };
    const music = ex.audio;
    music.el.setAttribute('src', 'http://127.0.0.1:1/x.mp3');
    Object.defineProperty(music.el, 'paused', { configurable: true, value: false });
    const calls = (music as unknown as { calls: string[] }).calls;
    await hover(MOVIE);
    expect(calls).toEqual(['pause']);
    Object.defineProperty(music.el, 'paused', { configurable: true, value: true });
    await fireEvent.mouseDown(window);
    await settle();
    ex.state.preview = MOVIE.path;
    await settle();
    vi.advanceTimersByTime(RESUME_WAIT_MS * 2);
    expect(calls).toEqual(['pause']);
  });

  it('odłączony telefon zatrzymuje własny odtwarzacz i nie wznawia muzyki z martwego strumienia', async () => {
    const { calls, paused } = backgroundMusic();
    await hover(SONG);
    expect(calls).toEqual(['pause']);
    paused(true);
    ex.state.offline = true;
    await settle();
    expect(bubble()).toBeNull();
    const own = players.find((p) => p.calls.includes('play'))!;
    expect(own.calls.at(-1)).toBe('stop');
    vi.advanceTimersByTime(1000);
    expect(calls).toEqual(['pause']);
  });

  it('odłączenie w czasie oczekiwania na wznowienie też porzuca muzykę', async () => {
    const { calls, paused } = backgroundMusic();
    await hover(MOVIE);
    paused(true);
    await fireEvent.mouseDown(window);
    await settle();
    vi.advanceTimersByTime(100);
    ex.state.offline = true;
    await settle();
    vi.advanceTimersByTime(1000);
    expect(calls).toEqual(['pause']);
  });

  it.each([
    ['blur okna', () => fireEvent.blur(window)],
    ['opuszczenie dokumentu', () => fireEvent.mouseLeave(document.documentElement)],
  ])('%s przy grającym dymku zatrzymuje go i wznawia muzykę raz po 400 ms', async (_name, act) => {
    const { calls, paused, music } = backgroundMusic();
    await hover(SONG);
    paused(true);
    await act();
    await settle();
    expect(bubble()).toBeNull();
    const own = players.find((p) => p !== (music as unknown))!;
    expect(own.calls.at(-1)).toBe('stop');
    vi.advanceTimersByTime(RESUME_WAIT_MS - 1);
    expect(calls).toEqual(['pause']);
    vi.advanceTimersByTime(1);
    expect(calls).toEqual(['pause', 'play']);
    vi.advanceTimersByTime(1000);
    expect(calls).toEqual(['pause', 'play']);
  });

  it('powrót na ten sam plik w przejeździe nie zaczyna muzyki od nowa', async () => {
    await backAgain(SONG);
    expect(bubble()?.textContent).toContain('utwor.mp3');
    expect(players[0].calls).toEqual([`load ${SONG.url}`, 'play']);
  });

  it('powrót na ten sam plik w przejeździe nie rysuje PDF od nowa', async () => {
    await backAgain(DOC);
    expect(bubble()?.textContent).toContain('faktura.pdf');
    expect(pdf.draw).toHaveBeenCalledTimes(1);
  });

  it('powrót na ten sam plik w przejeździe nie czyta tekstu od nowa', async () => {
    const head = vi.spyOn(ex, 'textHead');
    await backAgain(NOTE);
    expect(bubble()?.textContent).toContain('notatka.txt');
    expect(head).toHaveBeenCalledTimes(1);
  });

  it('czas trwania dochodzi do stopki z loadedmetadata', async () => {
    await hover(MOVIE);
    expect(bubble()!.textContent).not.toContain('1:05');
    const video = bubble()!.querySelector('video')!;
    Object.defineProperty(video, 'duration', { value: 65 });
    await fireEvent.loadedMetadata(video);
    expect(bubble()!.textContent).toContain('1:05');
  });

  it('film bez obrazu pokazuje ikonę typu i gra dalej', async () => {
    await hover(MOVIE);
    const video = bubble()!.querySelector('video')!;
    await fireEvent.loadedMetadata(video);  // videoWidth 0: kodek obrazu nieobsługiwany
    expect(bubble()!.querySelector('video')).toBe(video);
    expect(bubble()!.querySelector('[data-peek-icon]')).not.toBeNull();
  });

  it('zdjęcie i film bez miniatury mają ikonę typu do pierwszej treści', async () => {
    await hover(PHOTO2);
    expect(bubble()!.querySelector('[data-peek-icon]')).not.toBeNull();
    await fireEvent.load(bubble()!.querySelector('img')!);
    expect(bubble()!.querySelector('[data-peek-icon]')).toBeNull();
    await hover(null);
    vi.advanceTimersByTime(1000);
    await settle();

    const bare = { ...MOVIE, path: '/sdcard/Test/bez.mp4', thumb: null };
    ex.state.entries = [...ALL, bare];
    tile(bare);
    await hover(bare);
    const video = bubble()!.querySelector('video')!;
    expect(bubble()!.querySelector('[data-peek-icon]')).not.toBeNull();
    await fireEvent.loadedData(video);
    expect(bubble()!.querySelector('[data-peek-icon]')).toBeNull();
  });

  it('tekst: najpierw ikona, potem początek pliku; nie woła odczytu pełnego podglądu', async () => {
    bridge.answerNext('explorer_text_head', { text: 'Pierwsza linia', truncated: true });
    ex.state.hover = NOTE.path;
    flushSync();
    vi.advanceTimersByTime(PEEK_DELAY_MS);
    flushSync();
    expect(bubble()!.querySelector('[data-peek-icon]')).not.toBeNull();
    await vi.waitFor(async () => {
      await vi.advanceTimersByTimeAsync(1);
      expect(bubble()!.querySelector('pre')?.textContent).toBe('Pierwsza linia');
    });
    expect(bubble()!.querySelector('[data-peek-icon]')).toBeNull();
    const methods = bridge.calls.map((c) => c.method);
    expect(methods).not.toContain('explorer_text');
    expect(methods).not.toContain('explorer_meta');
  });

  it('wynik tekstu po zmianie pliku jest porzucany', async () => {
    let finish!: (v: { text: string; truncated: boolean } | null) => void;
    vi.spyOn(ex, 'textHead').mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    await hover(NOTE);
    ex.state.hover = PHOTO.path;
    await settle();
    finish({ text: 'stary tekst', truncated: false });
    await settle();
    expect(bubble()?.textContent).not.toContain('stary tekst');
    expect(bubble()?.textContent).toContain('a.jpg');
  });

  it('spóźniony błąd tekstu nie zamyka dymka następnego pliku', async () => {
    let finish!: (v: null) => void;
    vi.spyOn(ex, 'textHead').mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    await hover(NOTE);
    ex.state.hover = PHOTO.path;
    await settle();
    finish(null);
    await settle();
    expect(bubble()?.textContent).toContain('a.jpg');
  });

  it('PDF: ikona do czasu treści, odjechanie przerywa rysowanie bez zamykania następnego dymka', async () => {
    let fail!: (e: Error) => void;
    pdf.draw = vi.fn(() => new Promise((_, reject) => { fail = reject; }));
    await hover(DOC);
    expect(pdf.draw).toHaveBeenCalledTimes(1);
    const [url, canvas, width, signal] = pdf.draw.mock.calls[0] as [string, HTMLCanvasElement, number, AbortSignal];
    expect(url).toBe(DOC.url);
    expect(canvas).toBeInstanceOf(HTMLCanvasElement);
    expect(width).toBeGreaterThan(0);
    expect(bubble()!.querySelector('[data-peek-icon]')).not.toBeNull();

    ex.state.hover = NOTE.path;
    await settle();
    expect(signal.aborted).toBe(true);
    fail(new Error('pdf.js: przerwano'));
    await settle();
    expect(bubble()?.textContent).toContain('notatka.txt');
  });

  it('PDF narysowany chowa ikonę', async () => {
    await hover(DOC);
    await settle();
    expect(bubble()!.querySelector('[data-peek-icon]')).toBeNull();
  });

  it.each([
    ['PDF', DOC, async () => {}],
    ['tekst', NOTE, async () => {}],
    ['film', MOVIE, async () => { await fireEvent.error(bubble()!.querySelector('video')!); }],
    ['muzyka', SONG, async () => { players[0].onerror?.(); }],
    ['zdjęcie', PHOTO2, async () => { await fireEvent.error(bubble()!.querySelector('img')!); }],
  ])('błąd (%s) zamyka dymek bez s.error', async (_name, e, act) => {
    pdf.draw = vi.fn(async () => { throw new Error('zły plik'); });
    bridge.failNext('explorer_text_head', 'explorer_read');
    const seen = ex.state.error;
    ex.state.hover = e.path;
    flushSync();
    await vi.advanceTimersByTimeAsync(PEEK_DELAY_MS);
    await settle();
    await act();
    await vi.advanceTimersByTimeAsync(1);
    await settle();
    expect(bubble()).toBeNull();
    expect(ex.state.error).toBe(seen);
    vi.advanceTimersByTime(1000);  // plik pod kursorem nie wraca sam
    await settle();
    expect(bubble()).toBeNull();
  });

  it('pozycja przy kaflu ze ścieżką ze znakami specjalnymi', async () => {
    document.querySelector(`[data-path="${CSS.escape(ODD.path)}"]`)?.remove();
    tile(ODD, 250);
    ex.state.view = 'grid';
    pointer('pointermove', 'mouse', 700);  // w siatce kursor nie ma znaczenia
    await hover(ODD);
    expect(bubble()?.style.left).toBe('362px');  // prawa krawędź 350 + odstęp 12
  });

  it('na liście dymek stoi przy kursorze, bo wiersz zajmuje całą szerokość', async () => {
    ex.state.view = 'list';
    pointer('pointermove', 'mouse', 300);
    await hover(NOTE);
    expect(bubble()?.style.left).toBe('312px');  // kursor 300 + odstęp 12
  });

  it('na liście bez miejsca po prawej dymek staje po lewej od kursora', async () => {
    ex.state.view = 'list';
    pointer('pointermove', 'mouse', 900);
    await hover(NOTE);
    expect(bubble()?.style.left).toBe('448px');  // kursor 900 - odstęp 12 - szerokość 440
  });

  it('koniec ekranu zwalnia własny odtwarzacz i worker PDF', async () => {
    await hover(SONG);
    view.unmount();
    expect(players[0].calls).toContain('dispose');
    expect(pdf.close).toHaveBeenCalledTimes(1);
    expect(bubble()).toBeNull();
  });
});
