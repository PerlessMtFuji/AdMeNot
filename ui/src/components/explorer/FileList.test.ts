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
    const { ex, view } = await setup(files(5));
    ex.select(files(5)[3].path);
    ex.setQuery('plik_0000');  // pasuje do wszystkich
    ex.setQuery('plik_00001');
    await view.rerender({ ex, items: ex.items, now: NOW });
    expect(rows().filter((r) => r.tabIndex === 0).map((r) => r.dataset.path)).toEqual([files(5)[1].path]);
  });

  test('the date column follows the "now" the screen passes in (no stale "today" after midnight)', async () => {
    const { ex, view } = await setup(files(1));
    expect(rows()[0].textContent).toContain('dziś');
    await view.rerender({ ex, items: ex.items, now: new Date(2026, 10, 3, 0, 5) });
    expect(rows()[0].textContent).toContain('wczoraj');
  });
});
