import { backOut, cubicOut } from 'svelte/easing';
import { fly, scale } from 'svelte/transition';

// Stałe ruchu (spec §6). Wszystkie przejścia w UI biorą czasy stąd.
// dialog: wejście Dialog.svelte (skala .96 → 1 + fade), spec §5.8.
// panel: przenikanie (crossfade) PlanPanel ⇄ PlanConfirm w prawym panelu, spec §5.5.
export const DUR = { micro: 140, enter: 300, screen: 300, success: 500, count: 400, flip: 300, dialog: 200, panel: 250, zoom: 450 } as const;
const STAGGER = 40;
const STAGGER_MAX = 10;

// Jedno zapytanie na okno (`matches` jest żywe): `matchMedia` w każdym kaflu galerii kosztował przy przewijaniu.
let query: MediaQueryList | undefined;
let queryFrom: typeof window.matchMedia | undefined;

export function reducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  if (queryFrom !== window.matchMedia) {
    queryFrom = window.matchMedia;
    query = window.matchMedia('(prefers-reduced-motion: reduce)');
  }
  return !!query?.matches;
}

export function ms(value: number): number {
  return reducedMotion() ? 0 : value;
}

export function stagger(i: number): number {
  return ms(Math.min(i, STAGGER_MAX) * STAGGER);
}

export function enter(node: Element, opts: { delay?: number; y?: number } = {}) {
  return fly(node, { y: opts.y ?? 10, duration: ms(DUR.enter), delay: opts.delay ?? 0, easing: cubicOut });
}

export function screenIn(node: Element, opts: { dir?: 1 | -1 } = {}) {
  return fly(node, { x: 16 * (opts.dir ?? 1), duration: ms(DUR.screen), easing: cubicOut });
}

export function pop(node: Element) {
  return scale(node, { start: 0.3, duration: ms(DUR.success), easing: backOut });
}
