import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PhotoPrefetch } from './prefetch';

const flush = async () => {
  for (let i = 0; i < 10; i++) await Promise.resolve();
};

describe('PhotoPrefetch', () => {
  let revoked: string[];
  let aborted: string[];

  beforeEach(() => {
    revoked = [];
    aborted = [];
    let n = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      init.signal?.addEventListener('abort', () => aborted.push(url));
      if (url.includes('zly')) return { ok: false, status: 404 };
      return { ok: true, blob: async () => new Blob(['x']) };
    }));
    URL.createObjectURL = vi.fn(() => `blob:${++n}`);
    URL.revokeObjectURL = vi.fn((src: string) => { revoked.push(src); });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('pobiera sąsiadów i oddaje adres gotowego zdjęcia', async () => {
    const photos = new PhotoPrefetch();
    expect(photos.get('a')).toBeNull();
    photos.keep([], ['a']);
    await flush();
    expect(photos.get('a')).toBe('blob:1');
  });

  it('bieżącego zdjęcia nie pobiera drugi raz, ale go nie zwalnia', async () => {
    const photos = new PhotoPrefetch();
    photos.keep([], ['a']);
    await flush();
    photos.keep(['a'], ['b']);
    await flush();
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(photos.get('a')).toBe('blob:1');
    expect(revoked).toEqual([]);
  });

  it('zwalnia to, co wypadło z okolicy, i przerywa trwające pobieranie', async () => {
    const photos = new PhotoPrefetch();
    photos.keep([], ['a']);
    await flush();
    photos.keep([], ['b']);
    expect(revoked).toEqual(['blob:1']);
    expect(aborted).toContain('a');
    expect(photos.get('a')).toBeNull();
  });

  it('nieudane pobieranie nie zostaje i może być ponowione', async () => {
    const photos = new PhotoPrefetch();
    photos.keep([], ['zly']);
    await flush();
    expect(photos.get('zly')).toBeNull();
    photos.keep([], ['zly']);
    await flush();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('wiele `keep` z tym samym adresem pobiera go raz', async () => {
    const photos = new PhotoPrefetch();
    photos.keep([], ['a']);
    photos.keep([], ['a']);
    await flush();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('`clear` zwalnia wszystko', async () => {
    const photos = new PhotoPrefetch();
    photos.keep([], ['a', 'b']);
    await flush();
    photos.clear();
    expect(revoked.sort()).toEqual(['blob:1', 'blob:2']);
    expect(photos.get('a')).toBeNull();
  });
});
