import { DUR, reducedMotion } from '../motion';

/** Przybliżenie przy wejściu w folder (spec §5.6): stara zawartość rośnie `scale(2.4)` i znika (`opacity 0`, `blur(4px)`)
 *  od środka klikniętego kafla, nowa wjeżdża z `scale(.6)` do 1. Wyżej — odwrotnie (stara maleje do .6, nowa
 *  przybliża się z 2.4). Tylko `transform`, `opacity` i `filter`; przy ograniczonym ruchu nic się nie dzieje. */
export const ZOOM_NEAR = 2.4;
export const ZOOM_FAR = 0.6;
const EASING = 'cubic-bezier(.4, 0, .2, 1)';
const BLUR = 'blur(4px)';

export type ZoomDir = 'in' | 'out';

export interface Zoom {
  /** Migawka starej zawartości — leży nad sceną, bez interakcji, i znika po animacji. */
  ghost: HTMLElement;
  dir: ZoomDir;
  origin: string;
}

/** Wejście w głąb (albo skok w bok) przybliża, wyjście wyżej oddala. */
export function zoomDirection(from: string, to: string): ZoomDir {
  return from.startsWith(`${to}/`) ? 'out' : 'in';
}

/** Kopia sceny sprzed podmiany zawartości (wołać tuż przed aktualizacją DOM). `at` — punkt kliknięcia względem
 *  sceny; bez niego (klawiatura, okruszki, wyjście wyżej) ruch zaczyna się od środka. null: ruch wyłączony. */
export function zoomSnapshot(
  host: HTMLElement, stage: HTMLElement, from: string, to: string, at: { x: number; y: number } | null,
): Zoom | null {
  if (reducedMotion() || typeof stage.animate !== 'function' || from === to) return null;
  const dir = zoomDirection(from, to);
  const ghost = stage.cloneNode(true) as HTMLElement;
  ghost.setAttribute('aria-hidden', 'true');
  ghost.setAttribute('inert', '');
  ghost.removeAttribute('id');
  Object.assign(ghost.style, {
    position: 'absolute', left: `${stage.offsetLeft}px`, top: `${stage.offsetTop}px`, width: `${stage.offsetWidth}px`,
    height: `${stage.offsetHeight}px`, pointerEvents: 'none', overflow: 'hidden',
  });
  // przewinięcie nie przechodzi przez `cloneNode`: bez tego migawka skoczyłaby na górę listy
  const live = stage.querySelectorAll<HTMLElement>('*');
  ghost.querySelectorAll<HTMLElement>('*').forEach((el, i) => {
    if (live[i]?.scrollTop) el.scrollTop = live[i].scrollTop;
  });
  host.appendChild(ghost);
  const point = dir === 'in' && at ? at : { x: stage.offsetWidth / 2, y: stage.offsetHeight / 2 };
  return { ghost, dir, origin: `${Math.round(point.x)}px ${Math.round(point.y)}px` };
}

/** Rusza przybliżenie: migawka odpływa, nowa zawartość sceny przypływa. */
export function zoomRun(stage: HTMLElement, zoom: Zoom): void {
  const { ghost, dir, origin } = zoom;
  const rest = { transform: 'scale(1)', opacity: 1, filter: 'blur(0px)' };
  const away = { opacity: 0, filter: BLUR };
  const options = { duration: DUR.zoom, easing: EASING, fill: 'both' as const };
  ghost.style.transformOrigin = origin;
  stage.style.transformOrigin = origin;
  const gone = ghost.animate([rest, { ...away, transform: `scale(${dir === 'in' ? ZOOM_NEAR : ZOOM_FAR})` }], options);
  gone.onfinish = gone.oncancel = () => ghost.remove();
  const came = stage.animate([{ ...away, transform: `scale(${dir === 'in' ? ZOOM_FAR : ZOOM_NEAR})` }, rest], options);
  came.onfinish = came.oncancel = () => came.cancel();
}
