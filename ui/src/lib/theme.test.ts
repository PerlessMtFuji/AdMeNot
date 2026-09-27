import { afterEach, describe, expect, test, vi } from 'vitest';
import { applyTheme, resolveTheme } from './theme';

function fakeMedia(initial: boolean) {
  const listeners = new Set<() => void>();
  const mq = {
    matches: initial,
    media: '(prefers-color-scheme: dark)',
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
  };
  const set = (dark: boolean) => { mq.matches = dark; listeners.forEach((fn) => fn()); };
  return { mq, set, listeners };
}

afterEach(() => vi.unstubAllGlobals());

describe('theme', () => {
  test('resolveTheme', () => {
    expect(resolveTheme('system', true)).toBe('dark');
    expect(resolveTheme('system', false)).toBe('light');
    expect(resolveTheme('light', true)).toBe('light');
    expect(resolveTheme('dark', false)).toBe('dark');
  });

  test('system follows Windows live; an explicit theme stops following', () => {
    const media = fakeMedia(false);
    vi.stubGlobal('matchMedia', () => media.mq);
    const root = document.createElement('html');
    applyTheme('system', root);
    expect(root.dataset.theme).toBe('light');
    media.set(true);
    expect(root.dataset.theme).toBe('dark');
    applyTheme('light', root);
    expect(root.dataset.theme).toBe('light');
    media.set(false);
    media.set(true);
    expect(root.dataset.theme).toBe('light');
    expect(media.listeners.size).toBe(0);
  });
});
