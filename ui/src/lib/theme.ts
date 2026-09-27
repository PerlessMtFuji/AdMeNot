import type { Theme } from './types';

const QUERY = '(prefers-color-scheme: dark)';
let stopFollowing: (() => void) | null = null;

export function resolveTheme(theme: Theme, prefersDark: boolean): 'light' | 'dark' {
  if (theme === 'system') return prefersDark ? 'dark' : 'light';
  return theme;
}

/** Ustawia data-theme na <html>; przy „system” śledzi motyw Windows na żywo. */
export function applyTheme(theme: Theme, root: HTMLElement = document.documentElement): void {
  stopFollowing?.();
  stopFollowing = null;
  const mq = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(QUERY) : null;
  const set = () => { root.dataset.theme = resolveTheme(theme, mq?.matches ?? false); };
  set();
  if (theme === 'system' && mq) {
    mq.addEventListener('change', set);
    stopFollowing = () => mq.removeEventListener('change', set);
  }
}
