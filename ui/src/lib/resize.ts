export interface Size { width: number; height: number }

/** Odczyt początkowy od razu, kolejne zmiany poza cyklem dostarczania ResizeObserver.
 * Zmiana DOM w jego callbacku może ponownie zmienić rozmiar i wywołać błąd pętli.
 * Scalanie i porównanie wymiarów ogranicza też zbędne przeliczenia wirtualizacji. */
export function observeSize(node: HTMLElement, onchange: (size: Size) => void): () => void {
  let previous: Size | undefined;
  let frame: number | null = null;
  let active = true;
  const update = () => {
    frame = null;
    if (!active) return;
    const size = { width: node.clientWidth, height: node.clientHeight };
    if (previous?.width === size.width && previous.height === size.height) return;
    previous = size;
    onchange(size);
  };
  update();
  const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
    if (active && frame === null) frame = requestAnimationFrame(update);
  });
  observer?.observe(node);
  return () => {
    active = false;
    observer?.disconnect();
    if (frame !== null) cancelAnimationFrame(frame);
  };
}
