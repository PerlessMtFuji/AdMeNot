import { fireEvent, render, screen } from '@testing-library/svelte';
import { tick } from 'svelte';
import { expect, test, vi } from 'vitest';
import type { AppView } from '../lib/types';
import ReasonTiles from './ReasonTiles.svelte';

const app = {
  symptoms: [{ category: 'ads', severity: 'bad', text: 'x' }, { category: 'origin', severity: 'neutral', text: 'y' },
    { category: 'removal', severity: 'warn', text: 'z' }],
} as unknown as AppView;

test('one tile per symptom, named by the category', () => {
  render(ReasonTiles, { props: { app } });
  const tiles = screen.getAllByRole('img');
  expect(tiles.map((x) => x.getAttribute('aria-label'))).toEqual(['Reklamy', 'Pochodzenie', 'Utrudnia usunięcie']);
  expect(tiles[0].className).toContain('bg-bad-soft');
  expect(tiles[1].className).toContain('bg-neutral-soft');
  expect(tiles[2].className).toContain('bg-warn-soft');
});

test('safe app without symptoms renders no tiles', () => {
  render(ReasonTiles, { props: { app: { symptoms: [] } as unknown as AppView } });
  expect(screen.queryAllByRole('img')).toHaveLength(0);
});

test('category name appears as a tooltip on hover and on focus', async () => {
  vi.useFakeTimers();
  try {
    render(ReasonTiles, { props: { app } });
    const [first, second] = screen.getAllByRole('img');
    await fireEvent.mouseEnter(first.parentElement!);
    await vi.advanceTimersByTimeAsync(350);
    expect(screen.getByRole('tooltip').textContent).toBe('Reklamy');
    await fireEvent.mouseLeave(first.parentElement!);
    second.focus();
    await vi.advanceTimersByTimeAsync(350);
    await tick();
    expect(screen.getByRole('tooltip').textContent).toBe('Pochodzenie');
  } finally { vi.useRealTimers(); }
});

test('focusable=false removes the tab stop but keeps the hover tooltip', async () => {
  vi.useFakeTimers();
  try {
    render(ReasonTiles, { props: { app, focusable: false } });
    const [first] = screen.getAllByRole('img');
    expect(first.hasAttribute('tabindex')).toBe(false);
    await fireEvent.mouseEnter(first.closest('[data-tooltip-host]')!);
    await vi.advanceTimersByTimeAsync(350);
    expect(screen.getByRole('tooltip').textContent).toBe('Reklamy');
  } finally { vi.useRealTimers(); }
});

test('tiles are focusable by default', () => {
  render(ReasonTiles, { props: { app } });
  expect(screen.getAllByRole('img').every((x) => x.getAttribute('tabindex') === '0')).toBe(true);
});
