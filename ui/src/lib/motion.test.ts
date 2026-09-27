import { afterEach, expect, test, vi } from 'vitest';
import { DUR, ms, reducedMotion, stagger } from './motion';

afterEach(() => vi.unstubAllGlobals());

test('reduced motion zeroes every duration', () => {
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce') }));
  expect(reducedMotion()).toBe(true);
  expect(ms(DUR.enter)).toBe(0);
  expect(stagger(3)).toBe(0);
});

test('normal motion keeps durations and caps the stagger at 10 items', () => {
  vi.stubGlobal('matchMedia', () => ({ matches: false }));
  expect(ms(DUR.enter)).toBe(300);
  expect(stagger(2)).toBe(80);
  expect(stagger(25)).toBe(400);
});
