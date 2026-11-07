<script lang="ts">
  import { tick, untrack } from 'svelte';
  import type { PDFDocumentProxy } from 'pdfjs-dist';
  import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
  import 'pdfjs-dist/web/pdf_viewer.css';
  import { findMatches } from '../../lib/explorer/find';
  import type { EntryView } from '../../lib/types';
  import { t } from '../../lib/i18n/index.svelte';
  import { observeSize } from '../../lib/resize';
  import Banner from '../../ui/Banner.svelte';
  import Icon from '../../ui/Icon.svelte';
  import FindBar from './FindBar.svelte';
  import PdfPage from './PdfPage.svelte';

  /** Czytnik PDF: strony jedna pod drugą w jednym przewijaniu, Ctrl+kółko przybliża wokół kursora. Układ jest liczony
   *  z rozmiarów stron, a rysowane są tylko te koło ekranu, więc długi dokument nie zjada pamięci. */
  let { entry }: { entry: EntryView } = $props();

  const GAP = 12;
  const PAD = 16;
  const ZOOM_MIN = 0.5;
  const ZOOM_MAX = 3;
  const ZOOM_STEP = 0.25;
  const WHEEL_STEP = 1.1;
  /** Ile ekranów nad i pod widocznym trzymamy gotowych. */
  const AHEAD = 1;
  /** Co tyle stron indeks trafia do stanu: każda aktualizacja przelicza układ wszystkich stron i wyszukiwanie. */
  const INDEX_BATCH = 16;

  type Size = { w: number; h: number };
  let pdf = $state.raw<PDFDocumentProxy | null>(null);
  let texts = $state.raw<string[]>([]);
  /** Rozmiary stron przy skali 1; strona jeszcze nieodczytana ma rozmiar pierwszej. */
  let sizes = $state.raw<Size[]>([]);
  let zoom = $state(1);
  let view = $state({ width: 700, height: 600 });
  let top = $state(0);
  let query = $state('');
  let whole = $state(false);
  let current = $state(0);
  let failed = $state(false);
  let loading = $state(true);
  let scroller: HTMLDivElement;

  const hits = $derived(texts.flatMap((text, i) => findMatches(text, query, whole).map(m => ({ ...m, page: i + 1 }))));
  const hit = $derived(hits[current] ?? null);
  /** Strona bieżącego trafienia: zmienia się tylko przy zmianie trafienia, nie przy dalszym indeksowaniu pliku. */
  const hitPage = $derived(hit?.page ?? null);
  /** Dekodery skanów (JBIG2, CCITT, JPEG 2000), mapy znaków CJK i czcionki bazowe; pliki kopiuje `vite.config.ts`. */
  const assets = (dir: string) => new URL(`pdfjs/${dir}/`, document.baseURI).href;

  const pages = $derived.by(() => {
    if (!pdf) return [];
    const first = sizes[0] ?? { w: 595, h: 842 };
    const base = (view.width - 2 * PAD) / first.w;
    let y = PAD;
    return Array.from({ length: pdf.numPages }, (_, i) => {
      const size = sizes[i] ?? first;
      const scale = Math.max(0.1, base * zoom);
      const page = { number: i + 1, top: y, width: size.w * scale, height: size.h * scale, scale };
      y += page.height + GAP;
      return page;
    });
  });
  const total = $derived(pages.length ? pages[pages.length - 1].top + pages[pages.length - 1].height + PAD : 0);
  const shown = $derived(pages.filter((p) => p.top + p.height >= top - AHEAD * view.height
    && p.top <= top + (1 + AHEAD) * view.height));
  /** Strona na środku ekranu; na końcach przewijania — pierwsza i ostatnia, nawet gdy są krótkie. */
  const number = $derived.by(() => {
    if (!pages.length) return 1;
    if (top + view.height >= total - 2) return pages.length;
    const middle = top + view.height / 2;
    return (pages.find((p) => middle <= p.top + p.height + GAP) ?? pages[pages.length - 1]).number;
  });

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
        const firstPage = await doc.getPage(1);
        if (stale) return;
        const { width, height } = firstPage.getViewport({ scale: 1 });
        sizes = [{ w: width, h: height }];
        pdf = doc;
        // Indeksujemy wszystkie strony do szukania; rysowane są tylko widoczne.
        const nextSizes: Size[] = [];
        const nextTexts: string[] = [];
        for (let i = 1; i <= doc.numPages && !stale; i++) {
          const page = await doc.getPage(i);
          const content = await page.getTextContent();
          if (stale) return;
          const box = page.getViewport({ scale: 1 });
          nextSizes.push({ w: box.width, h: box.height });
          nextTexts.push(content.items.flatMap(item => 'str' in item ? [item.str] : []).join(' '));
          if (i % INDEX_BATCH === 0 || i === doc.numPages) {
            sizes = [...nextSizes];
            texts = [...nextTexts];
          }
        }
      } catch { if (!stale) { failed = true; loading = false; } }
    })();
    return () => { stale = true; void destroy?.().catch(() => {}); };
  });

  function goTo(page: number): void {
    const target = pages[Math.min(pages.length, Math.max(1, page)) - 1];
    if (target) scroller.scrollTop = target.top - PAD;
  }
  $effect(() => { if (hitPage !== null) untrack(() => goTo(hitPage)); });

  /** Przybliżenie z punktem `at` (pozycja na ekranie) zostającym w tym samym miejscu dokumentu. */
  async function zoomTo(value: number, at = view.height / 2): Promise<void> {
    const next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value));
    if (next === zoom) return;
    const point = total ? (top + at) / total : 0;
    zoom = next;
    await tick();
    scroller.scrollTop = point * total - at;
  }

  function search(q: string, w: boolean): void {
    query = q;
    whole = w;
    current = 0;
  }
  function step(delta: number): void { if (hits.length) current = (current + delta + hits.length) % hits.length; }

  function stage(node: HTMLDivElement) {
    const stop = observeSize(node, (size) => { view = { width: size.width || 700, height: size.height || 600 }; });
    const onwheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();  // inaczej przybliżyłaby się cała strona programu
      void zoomTo(zoom * (e.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP), e.clientY - node.getBoundingClientRect().top);
    };
    node.addEventListener('wheel', onwheel, { passive: false });
    return { destroy: () => { stop(); node.removeEventListener('wheel', onwheel); } };
  }
</script>

<div class="absolute inset-0 flex flex-col gap-2 p-4" aria-label={t('explorer.preview.pdf_label')}>
  <FindBar total={hits.length} {current} onsearch={search} onstep={step} />
  <div class="flex flex-none items-center gap-3 text-xs text-white/80">
    <button type="button" onclick={() => goTo(number - 1)} disabled={number <= 1} aria-label={t('explorer.preview.pdf_prev')} class="rounded-lg bg-white/10 p-2 disabled:opacity-40"><Icon name="chevron-left" size={14} /></button>
    <label class="flex items-center gap-2">{t('explorer.preview.pdf_page')}<input type="number" min="1" max={pdf?.numPages ?? 1} value={number}
      aria-label={t('explorer.preview.pdf_page')} class="w-16 rounded bg-white/10 px-2 py-1"
      onchange={(e) => goTo(Number(e.currentTarget.value) || 1)} /></label>
    <span>/ {pdf?.numPages ?? '…'}</span>
    <button type="button" onclick={() => goTo(number + 1)} disabled={!pdf || number >= pdf.numPages} aria-label={t('explorer.preview.pdf_next')} class="rounded-lg bg-white/10 p-2 disabled:opacity-40"><Icon name="chevron-right" size={14} /></button>
    <button type="button" onclick={() => zoomTo(zoom - ZOOM_STEP)} aria-label={t('explorer.preview.pdf_zoom_out')} class="rounded-lg bg-white/10 px-3 py-1.5">−</button>
    <span>{Math.round(zoom * 100)}%</span>
    <button type="button" onclick={() => zoomTo(zoom + ZOOM_STEP)} aria-label={t('explorer.preview.pdf_zoom_in')} class="rounded-lg bg-white/10 px-3 py-1.5">+</button>
    {#if pdf && texts.length < pdf.numPages}<span role="status">{t('explorer.preview.pdf_index', { current: texts.length, total: pdf.numPages })}</span>{/if}
  </div>
  {#if failed}<Banner tone="bad" icon="triangle-alert">{t('explorer.preview.failed')}</Banner>{/if}
  {#if pdf && texts.length === pdf.numPages && !texts.some(text => text.trim())}
    <Banner tone="info" icon="info">{t('explorer.preview.pdf_no_text')}</Banner>
  {/if}
  {#if loading && !failed}<span class="spin" role="status" aria-label={t('explorer.preview.loading')}></span>{/if}
  <div bind:this={scroller} use:stage onscroll={() => { top = scroller.scrollTop; }} data-pdf-scroll
    class="relative min-h-0 flex-1 overflow-auto rounded-xl bg-black/20">
    <div class="relative" style:height="{total}px" style:min-width="{(pages[0]?.width ?? 0) + 2 * PAD}px">
      {#each shown as p (p.number)}
        <div class="absolute left-1/2 -translate-x-1/2 bg-white" data-page={p.number}
          style:top="{p.top}px" style:width="{p.width}px" style:height="{p.height}px">
          <PdfPage doc={pdf!} number={p.number} scale={p.scale} {query} {whole}
            active={hit?.page === p.number ? hit.start : null}
            onrendered={() => { loading = false; }} onfail={() => { failed = true; loading = false; }} />
        </div>
      {/each}
    </div>
  </div>
</div>
