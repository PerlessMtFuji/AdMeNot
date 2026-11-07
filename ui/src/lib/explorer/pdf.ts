import type { PDFWorker } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

/** Największy obraz strony: przy dużej gęstości pikseli ekranu oznaczałoby setki MB na stronę (jak w `PdfPage`). */
const MAX_PIXELS = 16_000_000;
/** Kawałek odczytu dymka. Każdy zakres to osobny strumień z telefonu, a 64 KB pdf.js to dziesiątki kolejnych odczytów:
 *  plik do 16 MB (2 kawałki) czyta się w całości, jednym strumieniem, większy nadal zakresami. */
const PEEK_CHUNK = 8 * 1024 * 1024;

/** Biblioteka PDF z ustawionym workerem; ładowana dopiero przy pierwszym PDF-ie. */
export async function pdfLib(): Promise<typeof import('pdfjs-dist')> {
  const lib = await import('pdfjs-dist');
  lib.GlobalWorkerOptions.workerSrc = workerUrl;
  return lib;
}

/** Dekodery skanów (JBIG2, CCITT, JPEG 2000), mapy znaków CJK i czcionki bazowe; pliki kopiuje `vite.config.ts`. */
export function pdfAssets(): { wasmUrl: string; cMapUrl: string; standardFontDataUrl: string; iccUrl: string } {
  const dir = (name: string) => new URL(`pdfjs/${name}/`, document.baseURI).href;
  return { wasmUrl: dir('wasm'), cMapUrl: dir('cmaps'), standardFontDataUrl: dir('standard_fonts'), iccUrl: dir('iccs') };
}

/** Jeden worker na wszystkie dymki: kolejne najechania nie startują go za każdym razem od nowa. */
let worker: PDFWorker | null = null;

/** Zamyka worker dymków (np. gdy podgląd przestał być potrzebny); następne rysowanie założy nowy. */
export function closePdfWorker(): void {
  worker?.destroy();
  worker = null;
}

/** Rysuje pierwszą stronę PDF na `canvas` w zadanej szerokości — lekko: bez pobierania reszty pliku i bez warstwy
 *  tekstu. Błąd albo przerwanie `signal` odrzuca obietnicę; dokument jest zawsze niszczony. */
export async function drawFirstPage(url: string, canvas: HTMLCanvasElement, width: number, signal: AbortSignal): Promise<void> {
  const lib = await pdfLib();
  signal.throwIfAborted();
  if (!worker || worker.destroyed) worker = lib.PDFWorker.create({});
  const task = lib.getDocument({ url, worker, disableAutoFetch: true, disableStream: true, rangeChunkSize: PEEK_CHUNK, ...pdfAssets() });
  let destroyed = false;
  const destroy = () => {
    if (destroyed) return;
    destroyed = true;
    void Promise.resolve(task.destroy()).catch(() => {});
  };
  let cancel: (() => void) | undefined;
  const onAbort = () => { cancel?.(); destroy(); };  // przerwanie w trakcie ładowania odrzuca `task.promise`
  signal.addEventListener('abort', onAbort);
  try {
    const doc = await task.promise;
    signal.throwIfAborted();
    const page = await doc.getPage(1);
    signal.throwIfAborted();
    const viewport = page.getViewport({ scale: width / page.getViewport({ scale: 1 }).width });
    const ratio = Math.min(2, window.devicePixelRatio || 1, Math.sqrt(MAX_PIXELS / (viewport.width * viewport.height)));
    canvas.width = Math.ceil(viewport.width * ratio);
    canvas.height = Math.ceil(viewport.height * ratio);
    const render = page.render({ canvas, viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
    cancel = () => render.cancel();
    await render.promise;
  } finally {
    signal.removeEventListener('abort', onAbort);
    destroy();
  }
}
