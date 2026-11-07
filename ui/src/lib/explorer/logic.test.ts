import { describe, expect, test } from 'vitest';
import { i18n } from '../i18n/index.svelte';
import type { EntryView } from '../types';
import { days, defaultView, fileType, folderSummary, formatBytes, parentPath, sortEntries, visible } from './logic';

const at = (iso: string) => Math.floor(new Date(iso).getTime() / 1000);

function entry(name: string, extra: Partial<EntryView> = {}): EntryView {
  const dir = extra.kind === 'dir';
  return { name, path: `/sdcard/Download/${name}`, kind: 'file', size: 100, mtime: at('2026-11-01T10:00'),
    label: null, locked: false, type: dir ? 'other' : fileType(name), ext: dir ? '' : name.split('.').pop()!.toLowerCase(),
    thumb: null, url: null, ...extra };
}

describe('fileType', () => {
  test('maps extensions to the bridge kinds, case-insensitive', () => {
    const names = ['a.jpg', 'B.JPG', 'c.heic', 'd.mp4', 'e.mkv', 'f.mp3', 'g.m4a', 'h.opus', 'i.txt', 'j.log',
      'k.json', 'l.xml', 'm.csv', 'n.apk', 'o.pdf', 'p.docx', 'q.zip', 'bez_rozszerzenia'];
    expect(names.map(fileType)).toEqual(['image', 'image', 'image', 'video', 'video', 'audio', 'audio', 'audio',
      'text', 'text', 'text', 'text', 'text', 'apk', 'doc', 'doc', 'other', 'other']);
  });
});

describe('visible', () => {
  const entries = [
    entry('zdjęcie.jpg', { size: 300, mtime: at('2026-11-02T09:00') }),
    entry('Alfa', { kind: 'dir', size: 4096, mtime: at('2026-10-01T09:00') }),
    entry('faktura.pdf', { size: 50, mtime: at('2026-10-30T09:00') }),
    entry('aplikacja.apk', { size: 900, mtime: at('2026-10-31T09:00') }),
    entry('Zeta', { kind: 'dir', size: 4096, mtime: at('2026-11-01T09:00') }),
    entry('notatka.txt', { size: 10, mtime: at('2026-10-29T09:00') }),
    entry('film.mp4', { size: 5000, mtime: at('2026-10-28T09:00') }),
  ];
  const names = (list: EntryView[]) => list.map((e) => e.name);

  test('sorts by name, date or size in both directions, folders always first', () => {
    expect(names(visible(entries, 'all', '', { key: 'name', dir: 1 }))).toEqual(
      ['Alfa', 'Zeta', 'aplikacja.apk', 'faktura.pdf', 'film.mp4', 'notatka.txt', 'zdjęcie.jpg']);
    expect(names(visible(entries, 'all', '', { key: 'name', dir: -1 }))).toEqual(
      ['Zeta', 'Alfa', 'zdjęcie.jpg', 'notatka.txt', 'film.mp4', 'faktura.pdf', 'aplikacja.apk']);
    expect(names(visible(entries, 'all', '', { key: 'date', dir: -1 }))).toEqual(
      ['Zeta', 'Alfa', 'zdjęcie.jpg', 'aplikacja.apk', 'faktura.pdf', 'notatka.txt', 'film.mp4']);
    // rozmiar folderu (4096) nic nie mówi: foldery po nazwie
    expect(names(visible(entries, 'all', '', { key: 'size', dir: -1 }))).toEqual(
      ['Alfa', 'Zeta', 'film.mp4', 'aplikacja.apk', 'zdjęcie.jpg', 'faktura.pdf', 'notatka.txt']);
  });

  test('filters files by type (documents include text) and by name; folders stay for navigation', () => {
    const byName = { key: 'name', dir: 1 } as const;
    expect(names(visible(entries, 'image', '', byName))).toEqual(['Alfa', 'Zeta', 'zdjęcie.jpg']);
    expect(names(visible(entries, 'video', '', byName))).toEqual(['Alfa', 'Zeta', 'film.mp4']);
    expect(names(visible(entries, 'doc', '', byName))).toEqual(['Alfa', 'Zeta', 'faktura.pdf', 'notatka.txt']);
    expect(names(visible(entries, 'apk', '', byName))).toEqual(['Alfa', 'Zeta', 'aplikacja.apk']);
    expect(names(visible(entries, 'all', 'ZE', byName))).toEqual(['Zeta']);
    expect(names(visible(entries, 'all', ' zdj ', byName))).toEqual(['zdjęcie.jpg']);
  });

  test('a human label (app folder) is searchable too', () => {
    const wa = entry('com.whatsapp', { kind: 'dir', label: 'WhatsApp' });
    expect(names(visible([wa, entries[0]], 'all', 'whatsapp', { key: 'name', dir: 1 }))).toEqual(['com.whatsapp']);
    expect(names(visible([wa], 'all', 'whats', { key: 'name', dir: 1 }))).toEqual(['com.whatsapp']);
  });
});

describe('days', () => {
  test('groups three days with Polish labels, newest first, in input order', () => {
    i18n.lang = 'pl';
    const now = new Date('2026-11-02T12:00');
    const list = [
      entry('a.jpg', { mtime: at('2026-11-02T08:00') }),
      entry('b.jpg', { mtime: at('2026-11-02T00:10') }),
      entry('c.jpg', { mtime: at('2026-11-01T23:50') }),
      entry('d.jpg', { mtime: at('2026-10-14T18:00') }),
      entry('e.jpg', { mtime: at('2026-10-14T09:00') }),
    ];
    const out = days(list, now);
    expect(out.map((d) => d.label)).toEqual(['Dziś · 2 listopada', 'Wczoraj', '14 października']);
    expect(out.map((d) => d.key)).toEqual(['2026-11-02', '2026-11-01', '2026-10-14']);
    expect(out.map((d) => d.items.map((e) => e.name))).toEqual([['a.jpg', 'b.jpg'], ['c.jpg'], ['d.jpg', 'e.jpg']]);
  });

  test('another year shows the year; English labels', () => {
    i18n.lang = 'en';
    const out = days([entry('a.jpg', { mtime: at('2026-11-02T08:00') }), entry('x.jpg', { mtime: at('2025-12-24T08:00') })],
      new Date('2026-11-02T12:00'));
    expect(out.map((d) => d.label)).toEqual(['Today · 2 November', '24 December 2025']);
    i18n.lang = 'pl';
  });
});

describe('defaultView', () => {
  test('a grid for media places, a list elsewhere', () => {
    expect(['camera', 'screenshots', 'movies', 'whatsapp'].map(defaultView)).toEqual(['grid', 'grid', 'grid', 'grid']);
    expect(['downloads', 'music', 'documents', 'all'].map(defaultView)).toEqual(['list', 'list', 'list', 'list']);
    expect(defaultView(null)).toBe('list');
  });
});

describe('helpers', () => {
  test('parentPath stops at the storage root', () => {
    expect(parentPath('/sdcard/DCIM/Camera')).toBe('/sdcard/DCIM');
    expect(parentPath('/sdcard/DCIM')).toBe('/sdcard');
    expect(parentPath('/sdcard')).toBeNull();
  });

  test('formatBytes uses the language decimal separator', () => {
    expect(formatBytes(0, 'pl')).toBe('0 B');
    expect(formatBytes(676, 'pl')).toBe('676 B');
    expect(formatBytes(1536, 'pl')).toBe('1,5 KB');
    expect(formatBytes(310 * 1024, 'pl')).toBe('310 KB');
    expect(formatBytes(6.1 * 1024 ** 3, 'en')).toBe('6.1 GB');
  });
});

describe('folder sizes', () => {
  const dir = (name: string): EntryView => ({ name, path: `/sdcard/${name}`, kind: 'dir', size: 4096, mtime: 0, label: null,
    locked: false, type: 'other', ext: '', thumb: null, url: null });
  const file = (name: string, size: number): EntryView => ({ ...dir(name), kind: 'file', size, ext: 'jpg', type: 'image' });
  const stats = (files: number, bytes: number, partial = false, approx = false) => ({ files, bytes, partial, approx });

  test('sorting by size orders folders by their content; uncounted ones go last', () => {
    const entries = [dir('Mały'), dir('Nieznany'), file('a.jpg', 5), dir('Duży'), dir('Błąd')];
    const dirs = { '/sdcard/Mały': stats(1, 10), '/sdcard/Duży': stats(9, 9000), '/sdcard/Błąd': { failed: true as const } };
    const names = (key: 'size', dir: 1 | -1) => sortEntries(entries, { key, dir }, 'pl', dirs).map((e) => e.name);
    expect(names('size', -1)).toEqual(['Duży', 'Mały', 'Błąd', 'Nieznany', 'a.jpg']);
    expect(names('size', 1)).toEqual(['Mały', 'Duży', 'Błąd', 'Nieznany', 'a.jpg']);
    expect(sortEntries(entries, { key: 'size', dir: -1 }, 'pl').map((e) => e.name).slice(0, 4))
      .toEqual(['Błąd', 'Duży', 'Mały', 'Nieznany']);  // bez liczb: po nazwie, jak dotąd
  });

  test('summary: files and size, partial and approximate marks, empty and failed', () => {
    i18n.lang = 'pl';
    expect(folderSummary(undefined)).toBeNull();
    expect(folderSummary(stats(1213, 23 * 1024 * 1024))).toEqual({ files: '1213 plików', size: formatBytes(23 * 1024 * 1024, 'pl'), hint: '' });
    const partial = folderSummary(stats(2, 2048, true, true))!;
    expect(partial.files).toBe('≥ 2 pliki');
    expect(partial.size).toBe(`≥ ≈ ${formatBytes(2048, 'pl')}`);
    expect(partial.hint).toContain('bez dostępu');
    expect(partial.hint).toContain('przybliżony');
    expect(folderSummary(stats(0, 0))!.files).toBe('pusty');
    expect(folderSummary({ failed: true })).toEqual({ files: 'nie udało się policzyć', size: '—', hint: 'nie udało się policzyć' });
  });
});
