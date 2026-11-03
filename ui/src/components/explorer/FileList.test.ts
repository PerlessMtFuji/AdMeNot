import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test } from 'vitest';
import type { ExplorerController } from '../../lib/explorer/controller';
import type { EntryView } from '../../lib/types';
import { setupCtl } from '../../test-utils';
import FileList from './FileList.svelte';

const NOW = new Date(2026, 10, 2, 12, 0);

function files(count: number): EntryView[] {
  const base = NOW.getTime() / 1000;
  return Array.from({ length: count }, (_, i) => {
    const name = `plik_${String(i).padStart(5, '0')}.txt`;
    return { name, path: `/sdcard/Download/${name}`, kind: 'file' as const, size: 10, mtime: base - i * 60,
      label: null, locked: false, type: 'text' as const, ext: 'txt', thumb: null, url: null };
  });
}

async function setup(entries: EntryView[]) {
  const env = await setupCtl('explorer');
  const ex: ExplorerController = env.ctl.explorer;
  await ex.open('R58T00TEST');
  ex.state.entries = entries;
  const view = render(FileList, { props: { ex, items: ex.items, now: NOW } });
  await tick();
  return { ex, view };
}

const rows = () => within(screen.getByRole('listbox', { name: 'Pliki w folderze' })).queryAllByRole('option');

describe('FileList', () => {
  test('12 000 files: only the visible rows (± 2) are in the DOM', async () => {
    await setup(files(12_000));
    expect(rows().length).toBeGreaterThan(10);
    expect(rows().length).toBeLessThan(100);
  });

  test('Space toggles the focused row; arrows move the selection', async () => {
    const { ex } = await setup(files(5));
    await fireEvent.keyDown(rows()[1], { key: ' ' });
    expect([...ex.state.selected]).toEqual([files(5)[1].path]);
    await fireEvent.keyDown(rows()[1], { key: ' ' });
    expect(ex.state.selected.size).toBe(0);
    await fireEvent.keyDown(rows()[1], { key: 'ArrowDown' });
    expect([...ex.state.selected]).toEqual([files(5)[2].path]);
  });

  test('the first visible row stays tabbable when the search hides the anchor', async () => {
    const { ex, view } = await setup(files(12));
    const tabbable = () => rows().filter((r) => r.tabIndex === 0).map((r) => r.dataset.path);
    ex.select(files(12)[3].path);
    await tick();
    expect(tabbable()).toEqual([files(12)[3].path]);
    ex.setQuery('plik_0001');  // zostają plik_00010 i plik_00011, kotwica (plik_00003) schowana
    await view.rerender({ ex, items: ex.items, now: NOW });
    expect(ex.state.anchor).toBe(files(12)[3].path);
    expect(tabbable()).toEqual([files(12)[10].path]);
  });

  test('the date column follows the "now" the screen passes in (no stale "today" after midnight)', async () => {
    const { ex, view } = await setup(files(1));
    expect(rows()[0].textContent).toContain('dziś');
    await view.rerender({ ex, items: ex.items, now: new Date(2026, 10, 3, 0, 5) });
    expect(rows()[0].textContent).toContain('wczoraj');
  });

  test('another folder opens at the top, not at the previous scroll offset', async () => {
    const { ex } = await setup(files(2000));
    const box = screen.getByRole('listbox', { name: 'Pliki w folderze' });
    box.scrollTop = 30_000;
    await fireEvent.scroll(box);
    expect(rows().some((r) => r.dataset.path === files(2)[1].path)).toBe(false);
    ex.state.path = '/sdcard/Documents';
    await tick();
    expect(box.scrollTop).toBe(0);
    expect(rows().some((r) => r.dataset.path === files(2)[1].path)).toBe(true);
  });
});
