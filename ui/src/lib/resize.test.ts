import { afterEach, expect, test, vi } from 'vitest';
import { observeSize } from './resize';
import { viewport } from './explorer/virtual';

afterEach(() => vi.unstubAllGlobals());

function setup() {
  let notify: ResizeObserverCallback;
  const disconnect = vi.fn();
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: ResizeObserverCallback) { notify = callback; }
    observe() {}
    disconnect = disconnect;
  });
  const frames = new Map<number, FrameRequestCallback>();
  let sequence = 0;
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frames.set(++sequence, callback);
    return sequence;
  });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
  const size = { width: 400, height: 300 };
  const node = document.createElement('div');
  Object.defineProperties(node, {
    clientWidth: { get: () => size.width }, clientHeight: { get: () => size.height },
  });
  return { node, size, frames, disconnect,
    resize: () => notify!([], {} as ResizeObserver),
    flush: () => {
      const pending = [...frames.values()];
      frames.clear();
      pending.forEach(callback => callback(0));
    },
  };
}

test('resize updates are deferred, coalesced and read the latest dimensions', () => {
  const env = setup();
  const changed = vi.fn();
  observeSize(env.node, changed);
  expect(changed).toHaveBeenLastCalledWith({ width: 400, height: 300 });
  env.size.width = 600;
  env.resize();
  env.size.width = 700;
  env.resize();
  expect(changed).toHaveBeenCalledTimes(1);
  expect(env.frames.size).toBe(1);
  env.flush();
  expect(changed).toHaveBeenLastCalledWith({ width: 700, height: 300 });
});

test('identical dimensions do not cause another layout update', () => {
  const env = setup();
  const changed = vi.fn();
  observeSize(env.node, changed);
  env.resize();
  env.flush();
  expect(changed).toHaveBeenCalledTimes(1);
});

test('layout changes caused by the consumer are delivered in a later frame', () => {
  const env = setup();
  let calls = 0;
  observeSize(env.node, () => {
    calls++;
    if (env.size.width === 600) { env.size.width = 700; env.resize(); }
  });
  env.size.width = 600;
  env.resize();
  env.flush();
  expect(calls).toBe(2);
  expect(env.frames.size).toBe(1);
  env.flush();
  expect(calls).toBe(3);
});

test('unmount disconnects and cancels pending updates, including stale deliveries', () => {
  const env = setup();
  const changed = vi.fn();
  const stop = observeSize(env.node, changed);
  env.size.height = 500;
  env.resize();
  const queued = [...env.frames.values()][0];
  stop();
  expect(env.disconnect).toHaveBeenCalledOnce();
  expect(env.frames.size).toBe(0);
  queued(0);
  env.resize();
  expect(changed).toHaveBeenCalledTimes(1);
  expect(env.frames.size).toBe(0);
});

test('virtualized viewport still updates scrolling immediately and ignores duplicates', () => {
  const env = setup();
  const changed = vi.fn();
  const stop = viewport(changed)(env.node);
  env.node.scrollTop = 123;
  env.node.dispatchEvent(new Event('scroll'));
  expect(changed).toHaveBeenLastCalledWith({ top: 123, width: 400, height: 300 });
  env.node.dispatchEvent(new Event('scroll'));
  env.resize();
  env.flush();
  expect(changed).toHaveBeenCalledTimes(2);
  stop();
});
