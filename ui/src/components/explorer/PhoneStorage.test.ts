import { render, screen, within } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, test } from 'vitest';
import type { StorageView } from '../../lib/types';
import { setupCtl } from '../../test-utils';
import Places from './Places.svelte';
import PhoneStorage from './PhoneStorage.svelte';

const GB = 1024 ** 3;
const usage = (used: number, over: Partial<StorageView['groups']> = {}): StorageView => ({
  total: 100 * GB, used: used * GB, groups: { photos: 20 * GB, videos: 10 * GB, whatsapp: 5 * GB, other: (used - 35) * GB, ...over },
});

describe('PhoneStorage', () => {
  test('the liquid level and the label show used / total', () => {
    render(PhoneStorage, { props: { usage: usage(50) } });
    expect(screen.getByRole('img', { name: 'Zajęte 50% pamięci telefonu' })).toBeTruthy();
    expect(screen.getByText('50%')).toBeTruthy();
    expect(document.querySelector('[data-level]')?.getAttribute('data-level')).toBe('50');
    expect(screen.getByText(/50 GB z 100 GB/)).toBeTruthy();
    expect(screen.getByText(/wolne 50 GB/)).toBeTruthy();
  });

  test('the legend splits the used space into photos, videos, WhatsApp and other', () => {
    render(PhoneStorage, { props: { usage: usage(50) } });
    const legend = screen.getByRole('list');
    const rows = within(legend).getAllByRole('listitem').map((li) => li.textContent?.replace(/\s+/g, ' ').trim());
    expect(rows).toEqual(['Zdjęcia 20 GB', 'Filmy 10 GB', 'WhatsApp 5 GB', 'Inne 15 GB']);
  });

  test('without data the silhouette is empty: no percent, no legend', () => {
    render(PhoneStorage, { props: { usage: null } });
    expect(screen.getByRole('img', { name: 'Zajęte 0% pamięci telefonu' })).toBeTruthy();
    expect(screen.queryByRole('list')).toBeNull();
    expect(document.querySelector('[data-level]')?.getAttribute('data-level')).toBe('0');
  });

  test('the level follows the explorer:storage event in the Places panel', async () => {
    const { bridge, ctl } = await setupCtl('explorer');
    const ex = ctl.explorer;
    await ex.open('R58T00TEST');
    render(Places, { props: { places: ex.state.places, recent: [], path: '/', get storage() { return ex.state.storage; }, ongo: () => {} } });
    await new Promise((r) => setTimeout(r, 0));
    expect(bridge.calls.some((c) => c.method === 'explorer_storage')).toBe(true);
    expect(ex.state.storage?.used).toBe(71 * GB);
    bridge.emit('explorer:storage', usage(80));
    await tick();
    expect(ex.state.storage?.used).toBe(80 * GB);
    expect(document.querySelector('[data-level]')?.getAttribute('data-level')).toBe('80');
    expect(screen.getByText('80%')).toBeTruthy();
  });
});
