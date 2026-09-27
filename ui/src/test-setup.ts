import { cleanup } from '@testing-library/svelte';
import { afterEach } from 'vitest';

// jsdom nie ma matchMedia: testy działają jak przy prefers-reduced-motion (czasy animacji 0)
// i jasnym motywie systemu. Pojedyncze testy podmieniają window.matchMedia (vi.stubGlobal).
if (!window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: query.includes('reduce'),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}

// Przejścia Svelte 5 używają Web Animations API, którego jsdom nie ma.
if (!Element.prototype.animate) {
  Element.prototype.animate = function animate() {
    const animation = {
      onfinish: null as null | (() => void),
      oncancel: null,
      cancel() {},
      finish() {},
      pause() {},
      play() {},
      reverse() {},
      currentTime: 0,
      playState: 'finished',
      effect: null,
      finished: Promise.resolve(),
      addEventListener() {},
      removeEventListener() {},
    };
    queueMicrotask(() => animation.onfinish?.());
    return animation as unknown as Animation;
  };
}

// animate:flip (§6 „Przestawienie listy”) sprawdza trwające animacje przez getAnimations().
if (!Element.prototype.getAnimations) {
  Element.prototype.getAnimations = function getAnimations() {
    return [];
  };
}

afterEach(() => cleanup());
