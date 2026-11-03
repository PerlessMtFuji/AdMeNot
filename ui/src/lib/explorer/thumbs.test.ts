import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { THUMB_CACHE, ThumbQueue, type Fetched } from './thumbs';

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

  test('a failed download is remembered and not retried in a loop', async () => {
    const { calls, fetcher } = deferredFetcher();
    const q = new ThumbQueue(fetcher);
    q.want('bad', 0);
    await flush();
    calls[0].reject(new Error('HEVC'));
    await flush();
    expect(q.failed('bad')).toBe(true);
    q.want('bad', 0);
    await flush();
    expect(calls).toHaveLength(1);
  });

  test('the cache keeps 400 thumbnails and revokes the object URL of the one that falls out', async () => {
    const fetcher = async () => ({ blob: blob(), color: '#abcdef' });
    const q = new ThumbQueue(fetcher);
    for (let i = 0; i <= THUMB_CACHE; i++) {
      q.want(`u${i}`, 0);
      await flush();
    }
    expect(THUMB_CACHE).toBe(400);
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
