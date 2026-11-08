import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { RECHECK_MS, recheck } from './recheck';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('recheck', () => {
  test('runs the check every interval while active', async () => {
    const fn = vi.fn().mockResolvedValue(undefined);
    const stop = recheck(fn, () => true);
    expect(RECHECK_MS).toBe(5000);
    await vi.advanceTimersByTimeAsync(RECHECK_MS);
    expect(fn).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(RECHECK_MS * 2);
    expect(fn).toHaveBeenCalledTimes(3);
    stop();
  });

  test('does not call while inactive and resumes when active again', async () => {
    const fn = vi.fn().mockResolvedValue(undefined);
    let on = false;
    const stop = recheck(fn, () => on, 1000);
    await vi.advanceTimersByTimeAsync(3000);
    expect(fn).not.toHaveBeenCalled();
    on = true;
    await vi.advanceTimersByTimeAsync(1000);
    expect(fn).toHaveBeenCalledTimes(1);
    stop();
  });

  test('never overlaps calls when a check takes longer than the interval', async () => {
    let running = 0;
    let peak = 0;
    const fn = vi.fn(async () => {
      running++;
      peak = Math.max(peak, running);
      await new Promise((r) => setTimeout(r, 2500));
      running--;
    });
    const stop = recheck(fn, () => true, 1000);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(peak).toBe(1);
    expect(fn.mock.calls.length).toBeGreaterThan(1);
    stop();
  });

  test('keeps going after a failed check', async () => {
    const fn = vi.fn().mockRejectedValue(new Error('x'));
    const stop = recheck(fn, () => true, 1000);
    await vi.advanceTimersByTimeAsync(3000);
    expect(fn).toHaveBeenCalledTimes(3);
    stop();
  });

  test('stop halts further calls, even for a check already running', async () => {
    const fn = vi.fn().mockResolvedValue(undefined);
    const stop = recheck(fn, () => true, 1000);
    await vi.advanceTimersByTimeAsync(1000);
    stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
