<script lang="ts">
  import { untrack } from 'svelte';
  import type { PDFDocumentProxy, TextLayer as PdfTextLayer } from 'pdfjs-dist';
  import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
  import 'pdfjs-dist/web/pdf_viewer.css';
  import { findMatches } from '../../lib/explorer/find';
  import type { EntryView } from '../../lib/types';
  import { t } from '../../lib/i18n/index.svelte';
  import { observeSize } from '../../lib/resize';
  import Banner from '../../ui/Banner.svelte';
  import Icon from '../../ui/Icon.svelte';
  import FindBar from './FindBar.svelte';

  let { entry }: { entry: EntryView } = $props();
  let pdf = $state.raw<PDFDocumentProxy | null>(null);
  let layer = $state.raw<PdfTextLayer | null>(null);
  let texts = $state.raw<string[]>([]);
  let number = $state(1);
  let zoom = $state(1);
  let width = $state(700);
  let query = $state('');
  let whole = $state(false);
  let current = $state(0);
  let failed = $state(false);
  let loading = $state(true);
  let canvas: HTMLCanvasElement;
  let textBox: HTMLDivElement;
  const hits = $derived(texts.flatMap((text, i) => findMatches(text, query, whole).map(m => ({ ...m, page: i + 1 }))));
  /** Strona bieżącego trafienia: rośnie tylko przy zmianie trafienia, nie przy dalszym indeksowaniu pliku. */
  const hitPage = $derived(hits[current]?.page ?? null);
  /** Dekodery skanów (JBIG2, CCITT, JPEG 2000), mapy znaków CJK i czcionki bazowe; pliki kopiuje `vite.config.ts`. */
  const assets = (dir: string) => new URL(`pdfjs/${dir}/`, document.baseURI).href;

  $effect(() => {
    const url = entry.url;
    let stale = false;
    let destroy: (() => Promise<void>) | undefined;
    void (async () => {
      try {
        const lib = await import('pdfjs-dist');
        if (stale) return;
        lib.GlobalWorkerOptions.workerSrc = workerUrl;
        const task = lib.getDocument({ url: url!, wasmUrl: assets('wasm'), cMapUrl: assets('cmaps'),
          standardFontDataUrl: assets('standard_fonts'), iccUrl: assets('iccs') });
        destroy = () => task.destroy();
        const doc = await task.promise;
        if (stale) return;
        pdf = doc;
        // Indeksujemy wszystkie strony, ale rasteryzujemy tylko oglądaną.
        for (let i = 1; i <= doc.numPages && !stale; i++) {
          const page = await doc.getPage(i);
          const content = await page.getTextContent();
          if (stale) return;
          texts = [...texts, content.items.flatMap(item => 'str' in item ? [item.str] : []).join(' ')];
        }
      } catch { if (!stale) { failed = true; loading = false; } }
    })();
    return () => { stale = true; void destroy?.().catch(() => {}); };
  });

  $effect(() => {
    const doc = pdf;
    const pageNumber = number;
    const scaleWidth = width * zoom;
    if (!doc || !canvas || !textBox) return;
    let stale = false;
    let cancel: (() => void) | undefined;
    untrack(() => { layer = null; loading = true; failed = false; });
    void (async () => {
      try {
        const lib = await import('pdfjs-dist');
        const page = await doc.getPage(pageNumber);
        if (stale) return;
        const viewport = page.getViewport({ scale: Math.max(0.1, (scaleWidth - 32) / page.getViewport({ scale: 1 }).width) });
        const ratio = Math.min(2, window.devicePixelRatio || 1);
        canvas.width = Math.ceil(viewport.width * ratio);
        canvas.height = Math.ceil(viewport.height * ratio);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;
        textBox.replaceChildren();
        textBox.style.setProperty('--scale-factor', String(viewport.scale));
        textBox.style.setProperty('--total-scale-factor', String(viewport.scale));
        const render = page.render({ canvas, viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
        cancel = () => render.cancel();
        void render.promise.catch(() => {}); // cleanup może przerwać render przed odczytem tekstu
        const textLayer = new lib.TextLayer({ textContentSource: await page.getTextContent(), container: textBox, viewport });
        cancel = () => { render.cancel(); textLayer.cancel(); };
        if (stale) { cancel(); return; }
        await Promise.all([render.promise, textLayer.render()]);
        if (stale) return;
        layer = textLayer;
        loading = false;
      } catch { if (!stale) { failed = true; loading = false; } }
    })();
    return () => { stale = true; cancel?.(); };
  });

  $effect(() => { if (hitPage !== null) number = hitPage; });
  $effect(() => {
    if (!layer) return;
    const pageHits = findMatches(layer.textContentItemsStr.join(' '), query, whole);
    const active = hits[current];
    let offset = 0;
    for (let i = 0; i < layer.textDivs.length; i++) {
      const span = layer.textDivs[i];
      const text = layer.textContentItemsStr[i];
      span.replaceChildren();
      let at = 0;
      for (const hit of pageHits) {
        const start = Math.max(0, hit.start - offset);
        const end = Math.min(text.length, hit.end - offset);
        if (end <= start) continue;
        span.append(document.createTextNode(text.slice(at, start)));
        const mark = document.createElement('mark');
        mark.textContent = text.slice(start, end);
        mark.className = active?.page === number && active.start === hit.start ? 'pdf-active' : 'pdf-match';
        span.append(mark);
        at = end;
      }
      span.append(document.createTextNode(text.slice(at)));
      offset += text.length + 1;
    }
    textBox.querySelector('.pdf-active')?.scrollIntoView?.({ block: 'center' });
  });

  function search(q: string, w: boolean): void {
    query = q;
    whole = w;
    current = 0;
  }
  function step(delta: number): void { if (hits.length) current = (current + delta + hits.length) % hits.length; }
  function observe(node: HTMLElement) {
    return { destroy: observeSize(node, (size) => { width = size.width || 700; }) };
  }
</script>

<div class="absolute inset-0 flex flex-col gap-2 p-4" aria-label={t('explorer.preview.pdf_label')}>
  <FindBar total={hits.length} {current} onsearch={search} onstep={step} />
  <div class="flex flex-none items-center gap-3 text-xs text-white/80">
    <button type="button" onclick={() => number--} disabled={number <= 1} aria-label={t('explorer.preview.pdf_prev')} class="rounded-lg bg-white/10 p-2 disabled:opacity-40"><Icon name="chevron-left" size={14} /></button>
    <label class="flex items-center gap-2">{t('explorer.preview.pdf_page')}<input type="number" min="1" max={pdf?.numPages ?? 1} value={number}
      aria-label={t('explorer.preview.pdf_page')} class="w-16 rounded bg-white/10 px-2 py-1"
      onchange={(e) => { number = Math.min(pdf?.numPages ?? 1, Math.max(1, Number(e.currentTarget.value) || 1)); }} /></label>
    <span>/ {pdf?.numPages ?? '…'}</span>
    <button type="button" onclick={() => number++} disabled={!pdf || number >= pdf.numPages} aria-label={t('explorer.preview.pdf_next')} class="rounded-lg bg-white/10 p-2 disabled:opacity-40"><Icon name="chevron-right" size={14} /></button>
    <button type="button" onclick={() => zoom = Math.max(.5, zoom - .25)} aria-label={t('explorer.preview.pdf_zoom_out')} class="rounded-lg bg-white/10 px-3 py-1.5">−</button>
    <span>{Math.round(zoom * 100)}%</span>
    <button type="button" onclick={() => zoom = Math.min(3, zoom + .25)} aria-label={t('explorer.preview.pdf_zoom_in')} class="rounded-lg bg-white/10 px-3 py-1.5">+</button>
    {#if pdf && texts.length < pdf.numPages}<span role="status">{t('explorer.preview.pdf_index', { current: texts.length, total: pdf.numPages })}</span>{/if}
  </div>
  {#if failed}<Banner tone="bad" icon="triangle-alert">{t('explorer.preview.failed')}</Banner>{/if}
  {#if pdf && texts.length === pdf.numPages && !texts.some(text => text.trim())}
    <Banner tone="info" icon="info">{t('explorer.preview.pdf_no_text')}</Banner>
  {/if}
  {#if loading && !failed}<span class="spin" role="status" aria-label={t('explorer.preview.loading')}></span>{/if}
  <div use:observe class="min-h-0 flex-1 overflow-auto rounded-xl bg-black/20 p-4">
    <div class="relative mx-auto w-fit bg-white" style:visibility={loading || failed ? 'hidden' : 'visible'}>
      <canvas bind:this={canvas} aria-label={t('explorer.preview.pdf_label')}></canvas>
      <div bind:this={textBox} class="textLayer"></div>
    </div>
  </div>
</div>

<style>
  :global(.textLayer mark.pdf-match) { background: #fde04799; color: transparent; }
  :global(.textLayer mark.pdf-active) { background: #fb923ccc; color: transparent; outline: 2px solid #ea580c; }
</style>
