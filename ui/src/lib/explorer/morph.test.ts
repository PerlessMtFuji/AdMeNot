import { afterEach, describe, expect, test, vi } from 'vitest';
import { closeMorph, morph } from './morph';

const motionOn = () => vi.stubGlobal('matchMedia', () => ({ matches: false }));

afterEach(() => {
  vi.unstubAllGlobals();
  delete (document as { startViewTransition?: unknown }).startViewTransition;
  document.body.innerHTML = '';
});

describe('morph', () => {
  test('with reduced motion (or no source element) it only runs the change', async () => {
    const change = vi.fn();
    await morph(document.body.appendChild(document.createElement('img')), change, () => null);
    await morph(null, change, () => null);
    expect(change).toHaveBeenCalledTimes(2);
  });

  test('uses the View Transitions API: the name moves from the source to the target and is cleaned up', async () => {
    motionOn();
    const from = document.body.appendChild(document.createElement('img'));
    const target = document.body.appendChild(document.createElement('div'));
    const seen: string[] = [];
    (document as unknown as { startViewTransition: unknown }).startViewTransition = (cb: () => Promise<void>) => {
      seen.push(from.style.viewTransitionName);  // stare zdjęcie ma nazwę w chwili zrzutu
      return { finished: cb().then(() => { seen.push(target.style.viewTransitionName); }) };
    };
    const change = vi.fn();
    await morph(from, change, () => target);
    expect(seen).toEqual(['preview-photo', 'preview-photo']);
    expect(change).toHaveBeenCalledOnce();
    expect(from.style.viewTransitionName).toBe('');
    expect(target.style.viewTransitionName).toBeFalsy();
  });

  test('without View Transitions it animates the target from the source rectangle (FLIP, transform only)', async () => {
    motionOn();
    const from = document.body.appendChild(document.createElement('img'));
    const target = document.body.appendChild(document.createElement('div'));
    from.getBoundingClientRect = () => ({ left: 10, top: 20, width: 100, height: 100 }) as DOMRect;
    target.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 200 }) as DOMRect;
    const animate = vi.fn();
    target.animate = animate;
    await morph(from, () => {}, () => target);
    const [frames, options] = animate.mock.calls[0];
    expect(frames[0].transform).toBe('translate(-140px, -30px) scale(0.25, 0.5)');
    expect(frames[1].transform).toBe('none');
    expect(options.duration).toBe(300);
  });
});

describe('closeMorph', () => {
  const photo = (): HTMLElement => {
    const el = document.body.appendChild(document.createElement('div'));
    el.dataset.morph = 'photo';
    return el;
  };
  const stubTransition = () => {
    const start = vi.fn((cb: () => Promise<void>) => ({ finished: cb() }));
    (document as unknown as { startViewTransition: unknown }).startViewTransition = start;
    return start;
  };

  test('a photo at normal size shrinks back with a view transition', async () => {
    motionOn();
    photo();
    const start = stubTransition();
    await closeMorph('/sdcard/a.jpg', () => {});
    expect(start).toHaveBeenCalledOnce();
  });

  test('a zoomed photo closes without one: its snapshot at 8x took 2.5 GB of graphics memory', async () => {
    motionOn();
    photo().dataset.zoomed = '';
    const start = stubTransition();
    const change = vi.fn();
    await closeMorph('/sdcard/a.jpg', change);
    expect(start).not.toHaveBeenCalled();
    expect(change).toHaveBeenCalledOnce();
  });
});
