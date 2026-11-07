import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { type Fetched, SPARE, THUMB_CACHE, ThumbDecodeError, ThumbQueue, videoFrame } from './thumbs';

/** Atrapa pobierania: każde wywołanie czeka, aż test je rozstrzygnie. */
function deferredFetcher() {
  const calls: { url: string; signal: AbortSignal; resolve: (v: Fetched) => void; reject: (e: unknown) => void }[] = [];
  const fetcher = (url: string, signal: AbortSignal) => new Promise<Fetched>((resolve, reject) => {
    calls.push({ url, signal, resolve, reject });
  });
  return { calls, fetcher };
}

const blob = () => ({ size: 1 }) as Blob;
const flush = async () => {
  for (let i = 0; i < 6; i++) await Promise.resolve();
};

let created = 0;
const revoked: string[] = [];
const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };

// jsdom nie ma URL.createObjectURL — atrapa liczy utworzone i zwolnione adresy.
beforeEach(() => {
  created = 0;
  revoked.length = 0;
  URL.createObjectURL = () => `blob:${++created}`;
  URL.revokeObjectURL = (u: string) => void revoked.push(u);
});

afterEach(() => Object.assign(URL, { createObjectURL: original.create, revokeObjectURL: original.revoke }));

describe('ThumbQueue', () => {
  test('runs at most 6 downloads at once; visible (lower priority number) go first', async () => {
    const { calls, fetcher } = deferredFetcher();
    const q = new ThumbQueue(fetcher);
    for (let i = 0; i < 10; i++) q.want(`u${i}`, 100 + i);  // poza ekranem
    q.want('v0', 0);
    q.want('v1', 1);
    await flush();
    expect(calls.map((c) => c.url)).toEqual(['u0', 'u1', 'u2', 'u3', 'u4', 'u5']);
    calls[0].resolve({ blob: blob(), color: '#112233' });
    await flush();
    // zwolnione miejsce bierze widoczny kafel, nie kolejny spoza ekranu
    expect(calls.map((c) => c.url).slice(6)).toEqual(['v0']);
    expect(q.get('u0')).toEqual({ src: 'blob:1', color: '#112233' });
    expect(q.get('u1')).toBeNull();
  });

  test('cancelAllExcept drops queued and aborts running downloads of the previous folder', async () => {
    const { calls, fetcher } = deferredFetcher();
    const q = new ThumbQueue(fetcher);
    for (let i = 0; i < 8; i++) q.want(`old${i}`, i);
    await flush();
    expect(calls).toHaveLength(6);
    q.cancelAllExcept(new Set(['new0', 'old1']));
    q.want('new0', 0);
    await flush();
    expect(calls.filter((c) => c.signal.aborted).map((c) => c.url)).toEqual(['old0', 'old2', 'old3', 'old4', 'old5']);
    expect(calls.map((c) => c.url).slice(6)).toEqual(['new0']);  // old6, old7 nie ruszyły
    calls[0].resolve({ blob: blob(), color: '#000000' });  // spóźniona odpowiedź anulowanego
    await flush();
    expect(q.get('old0')).toBeNull();
    expect(created).toBe(0);
  });

  test('a codec/decode error is permanent: the tile shows the type icon and is not retried', async () => {
    const { calls, fetcher } = deferredFetcher();
    const q = new ThumbQueue(fetcher);
    q.want('hevc', 0);
    await flush();
    calls[0].reject(new ThumbDecodeError('codec'));
    await flush();
    expect(q.failed('hevc')).toBe(true);
    q.want('hevc', 0);
    q.retryFailed();
    await flush();
    expect(calls).toHaveLength(1);
  });

  test('a transient error (network, HTTP, timeout) is retried in the background with backoff', async () => {
    vi.useFakeTimers();
    try {
      const { calls, fetcher } = deferredFetcher();
      const q = new ThumbQueue(fetcher);
      q.cancelAllExcept(new Set(['slow']));
      q.want('slow', 0);
      for (const wait of [1000, 2000, 4000]) {
        await flush();
        calls.at(-1)!.reject(new Error('network'));
        await flush();
        expect(q.failed('slow')).toBe(false);  // kafel czeka w kolorze, bez ikony
        q.want('slow', 0);  // w trakcie odczekiwania bez dodatkowego pobrania
        await flush();
        const before = calls.length;
        vi.advanceTimersByTime(wait - 1);
        expect(calls).toHaveLength(before);
        vi.advanceTimersByTime(1);
        expect(calls).toHaveLength(before + 1);
      }
      await flush();
      calls.at(-1)!.reject(new Error('network'));
      await flush();
      expect(q.failed('slow')).toBe(true);  // po 3 ponowieniach — ikona
      expect(calls).toHaveLength(4);
      q.retryFailed();  // zmiana folderu / telefon wrócił: widoczne ruszają od razu
      await flush();
      expect(q.failed('slow')).toBe(false);
      expect(calls).toHaveLength(5);
      calls[4].resolve({ blob: blob(), color: '#010203' });
      await flush();
      expect(q.get('slow')?.color).toBe('#010203');
    } finally {
      vi.useRealTimers();
    }
  });

  test('pauseSpare: zapas czeka, widoczne kafle ruszają, a po wznowieniu zapas rusza sam', async () => {
    const { calls, fetcher } = deferredFetcher();
    const q = new ThumbQueue(fetcher, 2);
    q.pauseSpare(true);
    q.plan([['zapas1', SPARE + 1], ['widoczny', 5], ['w-dom', 100_000]]);
    await flush();
    expect(calls.map((c) => c.url)).toEqual(['widoczny', 'w-dom']);
    calls[0].resolve({ blob: blob(), color: '' });
    await flush();
    expect(calls).toHaveLength(2);  // wolne miejsce nie idzie na zapas
    q.want('zapas2', SPARE + 2);
    await flush();
    expect(calls).toHaveLength(2);
    q.want('nowy', 1);  // widoczny kafel po przewinięciu
    await flush();
    expect(calls.map((c) => c.url).slice(2)).toEqual(['nowy']);
    calls[1].resolve({ blob: blob(), color: '' });
    calls[2].resolve({ blob: blob(), color: '' });
    await flush();
    expect(calls).toHaveLength(3);
    q.pauseSpare(false);
    await flush();
    expect(calls.map((c) => c.url).slice(3)).toEqual(['zapas1', 'zapas2']);
  });

  test('pauseSpare nie przerywa zapasu, który już się pobiera', async () => {
    const { calls, fetcher } = deferredFetcher();
    const q = new ThumbQueue(fetcher);
    q.want('zapas', SPARE);
    await flush();
    q.pauseSpare(true);
    expect(calls[0].signal.aborted).toBe(false);
    calls[0].resolve({ blob: blob(), color: '#010203' });
    await flush();
    expect(q.get('zapas')?.color).toBe('#010203');
  });

  test('an image the browser cannot decode is released and falls back to the icon', async () => {
    const q = new ThumbQueue(async () => ({ blob: blob(), color: '#abcdef' }));
    q.want('u', 0);
    await flush();
    expect(q.get('u')?.src).toBe('blob:1');
    q.broken('u');
    expect(revoked).toEqual(['blob:1']);
    expect(q.get('u')).toBeNull();
    expect(q.failed('u')).toBe(true);
  });

  test('the cache keeps 1500 thumbnails and revokes the object URL of the one that falls out', async () => {
    const fetcher = async () => ({ blob: blob(), color: '#abcdef' });
    const q = new ThumbQueue(fetcher);
    for (let i = 0; i <= THUMB_CACHE; i++) {
      q.want(`u${i}`, 0);
      await flush();
    }
    expect(THUMB_CACHE).toBe(1500);
    expect(revoked).toEqual(['blob:1']);
    expect(q.get('u0')).toBeNull();
    expect(q.get(`u${THUMB_CACHE}`)?.src).toBe(`blob:${THUMB_CACHE + 1}`);
    q.clear();
    expect(revoked).toHaveLength(THUMB_CACHE + 1);
  });

  test('thumbnails of the visible tiles are evicted last', async () => {
    const fetcher = async () => ({ blob: blob(), color: '#abcdef' });
    const q = new ThumbQueue(fetcher);
    q.want('keep', 0);
    await flush();
    q.cancelAllExcept(new Set(['keep']));
    for (let i = 0; i < THUMB_CACHE; i++) {
      q.want(`u${i}`, 0);
      await flush();
    }
    expect(q.get('keep')).not.toBeNull();
    expect(q.get('u0')).toBeNull();
  });
});

test('a video without a decodable picture gets the icon for good, no black tile', async () => {
  const real = document.createElement.bind(document);
  let video!: HTMLVideoElement;
  const spy = vi.spyOn(document, 'createElement').mockImplementation((name: string) => {
    const el = real(name);
    if (name === 'video') video = el as HTMLVideoElement;
    return el;
  });
  const frame = videoFrame('http://127.0.0.1:1/f', new AbortController().signal);
  spy.mockRestore();
  video.dispatchEvent(new Event('loadedmetadata'));
  await expect(frame).rejects.toBeInstanceOf(ThumbDecodeError);
});
