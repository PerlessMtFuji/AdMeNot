import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { ExplorerController } from '../../lib/explorer/controller';
import { type Fetched, ThumbQueue } from '../../lib/explorer/thumbs';
import { GRID } from '../../lib/explorer/virtual';
import type { EntryView } from '../../lib/types';
import { setupCtl } from '../../test-utils';
import Gallery from './Gallery.svelte';

const NOW = new Date(2026, 10, 2, 12, 0);  // 2 listopada 2026, południe
const DAY = 86_400;

/** `count` zdjęć, po `perDay` z każdego dnia wstecz od dziś. */
function photos(count: number, perDay = count): EntryView[] {
  const base = NOW.getTime() / 1000;
  return Array.from({ length: count }, (_, i) => {
    const name = `IMG_${String(i).padStart(5, '0')}.jpg`;
    return { name, path: `/sdcard/DCIM/Camera/${name}`, kind: 'file' as const, size: 1000, mtime: base - Math.floor(i / perDay) * DAY - i,
      label: null, locked: false, type: 'image' as const, ext: 'jpg', thumb: `http://127.0.0.1:1/t/${i}`, url: null };
  });
}

async function setup(entries: EntryView[], fetcher = (): Promise<Fetched> => new Promise(() => {})) {
  const env = await setupCtl('explorer');
  const ex: ExplorerController = env.ctl.explorer;
  await ex.open('R58T00TEST');
  ex.state.entries = entries;
  const thumbs = new ThumbQueue(fetcher);
  render(Gallery, { props: { ex, items: ex.items, now: NOW, thumbs } });
  await tick();
  return { ex, thumbs };
}

const grid = () => screen.getByRole('listbox', { name: 'Pliki w folderze' });
const tiles = () => within(grid()).queryAllByRole('option');
const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };

beforeEach(() => {
  let n = 0;
  URL.createObjectURL = () => `blob:${++n}`;
  URL.revokeObjectURL = () => {};
});

afterEach(() => {
  Object.assign(URL, { createObjectURL: original.create, revokeObjectURL: original.revoke });
  vi.unstubAllGlobals();
});

describe('Gallery', () => {
  test('12 000 photos: only the visible rows (± 2) are in the DOM', async () => {
    await setup(photos(12_000, 300));
    expect(tiles().length).toBeGreaterThan(20);
    expect(tiles().length).toBeLessThan(400);
  });

  test('clicking a day header selects that day, clicking again clears it', async () => {
    const { ex } = await setup(photos(9, 3));
    const today = screen.getByRole('button', { name: /Dziś · 2 listopada/ });
    await fireEvent.click(today);
    expect([...ex.state.selected].sort()).toEqual(photos(3).map((e) => e.path));
    expect(tiles().filter((t) => t.getAttribute('aria-selected') === 'true')).toHaveLength(3);
    await fireEvent.click(screen.getByRole('button', { name: /Wczoraj/ }));
    expect(ex.state.selected.size).toBe(6);
    await fireEvent.click(today);
    expect(ex.state.selected.size).toBe(3);
  });

  test('dragging a rectangle selects the tiles it crosses; Ctrl adds to the selection', async () => {
    const { ex } = await setup(photos(20));
    const area = grid();
    // jsdom: układ 948 px szerokości → 7 słupków po ~128,6 px; prostokąt przecina 3 pierwsze kafle 1. wiersza
    const y = GRID.header + 5;
    await fireEvent.mouseDown(area, { button: 0, clientX: 5, clientY: y });
    await fireEvent.mouseMove(window, { clientX: 300, clientY: y + 15 });
    expect(screen.getByTestId('lasso')).toBeTruthy();
    await fireEvent.mouseUp(window, { clientX: 300, clientY: y + 15 });
    expect(screen.queryByTestId('lasso')).toBeNull();
    const first = photos(20).map((e) => e.path);
    expect([...ex.state.selected]).toEqual(first.slice(0, 3));
    // drugi wiersz z Ctrl — dopisany
    const y2 = y + 140;
    await fireEvent.mouseDown(area, { button: 0, clientX: 5, clientY: y2, ctrlKey: true });
    await fireEvent.mouseMove(window, { clientX: 20, clientY: y2 + 5, ctrlKey: true });
    await fireEvent.mouseUp(window, { clientX: 20, clientY: y2 + 5, ctrlKey: true });
    expect([...ex.state.selected].sort()).toEqual([...first.slice(0, 3), first[7]].sort());
  });

  test('click selects, Space toggles the focused tile, arrows move by row', async () => {
    const { ex } = await setup(photos(20));
    await fireEvent.click(tiles()[0]);
    expect([...ex.state.selected]).toEqual([tiles()[0].dataset.path]);
    await fireEvent.keyDown(tiles()[0], { key: 'ArrowDown' });
    const below = tiles().find((t) => t.dataset.path === photos(20)[7].path)!;
    expect(ex.state.selected.has(below.dataset.path!)).toBe(true);
    await fireEvent.keyDown(below, { key: ' ' });
    expect(ex.state.selected.has(below.dataset.path!)).toBe(false);
    await fireEvent.keyDown(below, { key: ' ' });
    expect(ex.state.selected.has(below.dataset.path!)).toBe(true);
  });

  test('exactly one tile is tabbable, also when the anchor is hidden by the search', async () => {
    const { ex } = await setup(photos(20));
    const tabbable = () => tiles().filter((t) => t.tabIndex === 0);
    expect(tabbable().map((t) => t.dataset.path)).toEqual([photos(20)[0].path]);
    ex.select(photos(20)[5].path);
    await tick();
    expect(tabbable().map((t) => t.dataset.path)).toEqual([photos(20)[5].path]);
  });

  test('thumbnails sharpen in a cascade; with prefers-reduced-motion they appear without the animation', async () => {
    const fetcher = async (): Promise<Fetched> => ({ blob: {} as Blob, color: '#336699' });
    await setup(photos(4), fetcher);
    await vi.waitFor(() => expect(grid().querySelectorAll('img')).toHaveLength(4));
    expect(grid().querySelectorAll('img.sharpen')).toHaveLength(0);  // test-setup: reduced motion
    // kolor dominujący dnia w tle nagłówka
    expect(screen.getByRole('button', { name: /Dziś/ }).closest('[data-day]')?.getAttribute('style')).toContain('#336699');
  });

  test('without reduced motion the first visible tiles get the sharpening animation', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} }));
    const fetcher = async (): Promise<Fetched> => ({ blob: {} as Blob, color: '#336699' });
    await setup(photos(4), fetcher);
    await vi.waitFor(() => expect(grid().querySelectorAll('img.sharpen')).toHaveLength(4));
  });
});
