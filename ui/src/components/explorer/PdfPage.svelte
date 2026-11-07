<script lang="ts">
  import type { PDFDocumentProxy, TextLayer as PdfTextLayer } from 'pdfjs-dist';
  import { findMatches } from '../../lib/explorer/find';

  /** Jedna strona PDF: obraz i warstwa tekstu. Montowana tylko w pobliżu ekranu; nowy obraz powstaje poza ekranem
   *  i podmienia stary, więc przy zmianie przybliżenia strona nie miga (do tego czasu stary jest rozciągany). */
  type Props = { doc: PDFDocumentProxy; number: number; scale: number; query: string; whole: boolean;
    /** Początek bieżącego trafienia, gdy jest na tej stronie. */
    active: number | null; onrendered: () => void; onfail: () => void };
  let { doc, number, scale, query, whole, active, onrendered, onfail }: Props = $props();

  /** Przerwa w kręceniu kółkiem, po której strona rysuje się w nowym przybliżeniu. */
  const SETTLE_MS = 120;
  /** Największy obraz strony: przy dużym zoomie 2× gęstości oznaczałoby setki MB na stronę. */
  const MAX_PIXELS = 16_000_000;

  let host: HTMLDivElement;
  let layer = $state.raw<PdfTextLayer | null>(null);
  let drawn = false;
  let marked = false;  // warstwa tekstu ma podświetlenia

  async function draw(zoom: number, isStale: () => boolean, setCancel: (cancel: () => void) => void): Promise<void> {
    const lib = await import('pdfjs-dist');
    const page = await doc.getPage(number);
    if (isStale()) return;
    const viewport = page.getViewport({ scale: zoom });
    const ratio = Math.min(2, window.devicePixelRatio || 1, Math.sqrt(MAX_PIXELS / (viewport.width * viewport.height)));
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(viewport.width * ratio);
    canvas.height = Math.ceil(viewport.height * ratio);
    canvas.className = 'absolute inset-0 h-full w-full';
    const render = page.render({ canvas, viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
    setCancel(() => render.cancel());
    void render.promise.catch(() => {});  // przerwany render odrzuca obietnicę także przed `await` niżej
    const box = document.createElement('div');
    box.className = 'textLayer';
    box.style.setProperty('--scale-factor', String(viewport.scale));
    box.style.setProperty('--total-scale-factor', String(viewport.scale));
    const old = [...host.children];
    host.append(box);
    const text = new lib.TextLayer({ textContentSource: await page.getTextContent(), container: box, viewport });
    setCancel(() => { render.cancel(); text.cancel(); box.remove(); });
    if (isStale()) {
      render.cancel();
      text.cancel();
      box.remove();
      return;
    }
    await Promise.all([render.promise, text.render()]);
    if (isStale()) return;
    host.prepend(canvas);
    for (const el of old) el.remove();
    marked = false;  // nowa warstwa jest czysta
    layer = text;
    drawn = true;
    onrendered();
  }

  $effect(() => {
    const zoom = scale;
    let stale = false;
    let cancel: (() => void) | undefined;
    const timer = setTimeout(() => {
      draw(zoom, () => stale, (c) => { cancel = c; }).catch(() => { if (!stale) onfail(); });
    }, drawn ? SETTLE_MS : 0);
    return () => {
      stale = true;
      clearTimeout(timer);
      cancel?.();
    };
  });

  // Podświetlenia kładziemy na spanach warstwy tekstu; trafienie może obejmować kilka spanów.
  $effect(() => {
    if (!layer) return;
    const hits = findMatches(layer.textContentItemsStr.join(' '), query, whole);
    if (!hits.length && !marked) return;  // tysiące spanów strony bez zmian
    marked = hits.length > 0;
    let offset = 0;
    for (let i = 0; i < layer.textDivs.length; i++) {
      const span = layer.textDivs[i];
      const text = layer.textContentItemsStr[i];
      span.replaceChildren();
      let at = 0;
      for (const hit of hits) {
        const start = Math.max(0, hit.start - offset);
        const end = Math.min(text.length, hit.end - offset);
        if (end <= start) continue;
        span.append(document.createTextNode(text.slice(at, start)));
        const mark = document.createElement('mark');
        mark.textContent = text.slice(start, end);
        mark.className = active === hit.start ? 'pdf-active' : 'pdf-match';
        span.append(mark);
        at = end;
      }
      span.append(document.createTextNode(text.slice(at)));
      offset += text.length + 1;
    }
    if (active !== null) host.querySelector('.pdf-active')?.scrollIntoView?.({ block: 'center' });
  });
</script>

<div bind:this={host} class="absolute inset-0 overflow-hidden"></div>

<style>
  :global(.textLayer mark.pdf-match) { background: #fde04799; color: transparent; }
  :global(.textLayer mark.pdf-active) { background: #fb923ccc; color: transparent; outline: 2px solid #ea580c; }
</style>
