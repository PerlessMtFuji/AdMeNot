// „Zdjęcie rośnie z kafla” i kurczy się z powrotem (spec §5.4). Najpierw View Transition API
// (`view-transition-name` na kaflu i na zdjęciu), a gdy go nie ma — ręczne FLIP: zdjęcie startuje
// z prostokąta kafla i dojeżdża `transform`em na miejsce. Tylko transform/opacity, DUR.flip.
import { tick } from 'svelte';
import { DUR, reducedMotion } from '../motion';

const NAME = 'preview-photo';

/** Obraz kafla o tej ścieżce w galerii (null — kafla nie ma w DOM: lista albo poza oknem przewijania). */
export function tileImage(path: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-path="${CSS.escape(path)}"] img`);
}

/** Zdjęcie w oknie podglądu. */
export function photoImage(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[data-morph="photo"]');
}

type StartViewTransition = (cb: () => Promise<void> | void) => { finished: Promise<unknown> };

/**
 * Wykonuje `change` (otwarcie albo zamknięcie okna) tak, żeby `from` płynnie przeszedł w element
 * znaleziony po zmianie przez `to`. Bez ruchu (reduced motion, brak elementu) — sama zmiana.
 */
export async function morph(from: HTMLElement | null, change: () => void, to: () => HTMLElement | null): Promise<void> {
  if (!from || reducedMotion()) {
    change();
    return;
  }
  const doc = document as Document & { startViewTransition?: StartViewTransition };
  if (typeof doc.startViewTransition === 'function') {
    from.style.viewTransitionName = NAME;
    let target: HTMLElement | null = null;
    const transition = doc.startViewTransition(async () => {
      from.style.viewTransitionName = '';
      change();
      await tick();
      target = to();
      if (target) target.style.viewTransitionName = NAME;
    });
    try {
      await transition.finished;
    } catch {
      // przejście przerwane (np. kolejne) — stan i tak jest już docelowy
    } finally {
      from.style.viewTransitionName = '';
      (target as HTMLElement | null)?.style.removeProperty('view-transition-name');
    }
    return;
  }
  await flip(from.getBoundingClientRect(), change, to);
}

async function flip(first: DOMRect, change: () => void, to: () => HTMLElement | null): Promise<void> {
  change();
  await tick();
  const target = to();
  if (!target || typeof target.animate !== 'function') return;
  const last = target.getBoundingClientRect();
  if (!last.width || !last.height) return;
  const dx = first.left + first.width / 2 - (last.left + last.width / 2);
  const dy = first.top + first.height / 2 - (last.top + last.height / 2);
  target.animate(
    [{ transform: `translate(${dx}px, ${dy}px) scale(${first.width / last.width}, ${first.height / last.height})` },
      { transform: 'none' }],
    { duration: DUR.flip, easing: 'cubic-bezier(.2,.8,.2,1)' },
  );
}

/** Kafel → zdjęcie w oknie podglądu. */
export function openMorph(path: string, change: () => void): Promise<void> {
  return morph(tileImage(path), change, photoImage);
}

/** Zdjęcie w oknie podglądu → kafel (gdy go widać). Przybliżone zamyka się bez przejścia: przeglądarka robi
 *  zrzut elementu razem z powiększeniem, a przy 8× to 2,5 GB pamięci karty i klatkowanie całego komputera. */
export function closeMorph(path: string, change: () => void): Promise<void> {
  const photo = photoImage();
  return morph(photo?.dataset.zoomed === undefined ? photo : null, change, () => tileImage(path));
}
