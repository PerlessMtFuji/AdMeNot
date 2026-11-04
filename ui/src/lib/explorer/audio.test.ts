import { describe, expect, test, vi } from 'vitest';
import { AudioPlayer, BARS, barLevels, type ContextLike } from './audio';

function fakeContext() {
  const analyser = {
    fftSize: 0, smoothingTimeConstant: 0, frequencyBinCount: 64, connect: vi.fn(),
    getByteFrequencyData: vi.fn((out: Uint8Array) => out.fill(255)),
  };
  const source = { connect: vi.fn() };
  const ctx: ContextLike = {
    state: 'suspended', destination: {}, resume: vi.fn(async () => { ctx.state = 'running'; }),
    createMediaElementSource: vi.fn(() => source), createAnalyser: () => analyser, close: vi.fn(async () => {}),
  };
  return { ctx, analyser, source };
}

describe('audio', () => {
  test('barLevels folds the spectrum into 24 bars between 0 and 1', () => {
    const loud = barLevels(new Uint8Array(64).fill(255));
    expect(loud).toHaveLength(BARS);
    expect(loud.every((v) => v === 1)).toBe(true);
    expect(barLevels(new Uint8Array(64)).every((v) => v === 0)).toBe(true);
  });

  test('the analyser is wired once, on the first play, and levels come from it', async () => {
    const { ctx, analyser, source } = fakeContext();
    const factory = vi.fn(() => ctx);
    const player = new AudioPlayer(factory);
    expect(player.levels()).toEqual(new Array(BARS).fill(0));
    await player.play();
    await player.play();
    expect(factory).toHaveBeenCalledTimes(1);
    expect(ctx.createMediaElementSource).toHaveBeenCalledTimes(1);
    expect(source.connect).toHaveBeenCalledWith(analyser);
    expect(ctx.resume).toHaveBeenCalled();
    expect(player.levels().every((v) => v === 1)).toBe(true);
  });

  test('without AudioContext the player still plays and the bars stay flat', async () => {
    const player = new AudioPlayer(null);
    expect(player.analysable).toBe(false);
    await player.play();
    expect(player.el.play).toHaveBeenCalled();
    expect(player.levels()).toEqual(new Array(BARS).fill(0));
  });

  test('an element error is reported through onerror', () => {
    const player = new AudioPlayer(null);
    const onerror = vi.fn();
    player.onerror = onerror;
    player.el.dispatchEvent(new Event('error'));
    expect(onerror).toHaveBeenCalledOnce();
  });

  test('play() reports a failed start but not an interrupted one', async () => {
    const player = new AudioPlayer(null);
    vi.mocked(player.el.play).mockRejectedValueOnce(Object.assign(new Error('x'), { name: 'NotSupportedError' }));
    expect(await player.play()).toBe(false);
    vi.mocked(player.el.play).mockRejectedValueOnce(Object.assign(new Error('x'), { name: 'AbortError' }));
    expect(await player.play()).toBe(true);
  });

  test('if the analyser graph fails after the element was captured, the element is routed straight to the output', async () => {
    const { ctx, analyser, source } = fakeContext();
    analyser.connect.mockImplementation(() => { throw new Error('graph'); });
    const player = new AudioPlayer(() => ctx);
    expect(await player.play()).toBe(true);
    expect(source.connect).toHaveBeenLastCalledWith(ctx.destination);
    expect(player.levels()).toEqual(new Array(BARS).fill(0));
  });

  test('if even the direct route fails, play() reports an error instead of staying silent', async () => {
    const { ctx, analyser, source } = fakeContext();
    analyser.connect.mockImplementation(() => { throw new Error('graph'); });
    source.connect.mockImplementation(() => { throw new Error('route'); });
    const player = new AudioPlayer(() => ctx);
    expect(await player.play()).toBe(false);
  });
});
