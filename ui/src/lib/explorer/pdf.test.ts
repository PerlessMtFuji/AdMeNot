import { beforeEach, describe, expect, it, vi } from 'vitest';

const lib = vi.hoisted(() => {
  const state = { destroy: 0, render: 0, getPage: 0, created: 0, options: [] as Record<string, unknown>[],
    onOpen: null as (() => void) | null };
  const page = {
    getViewport: ({ scale }: { scale: number }) => ({ width: 200 * scale, height: 300 * scale }),
    render: () => { state.render++; return { promise: Promise.resolve(), cancel: () => {} }; },
  };
  const doc = { getPage: async () => { state.getPage++; return page; } };
  return {
    state,
    mock: {
      GlobalWorkerOptions: {} as Record<string, unknown>,
      PDFWorker: { create: () => { state.created++; return { destroyed: false, destroy() { this.destroyed = true; } }; } },
      getDocument: (options: Record<string, unknown>) => {
        state.options.push(options);
        state.onOpen?.();
        return { promise: Promise.resolve(doc), destroy: async () => { state.destroy++; } };
      },
    },
  };
});
vi.mock('pdfjs-dist', () => lib.mock);

import { closePdfWorker, drawFirstPage } from './pdf';

beforeEach(() => {
  closePdfWorker();
  Object.assign(lib.state, { destroy: 0, render: 0, getPage: 0, created: 0, options: [], onOpen: null });
});

describe('drawFirstPage', () => {
  it('pyta o dokument bez pobierania reszty i sprząta po sobie', async () => {
    const canvas = document.createElement('canvas');
    await drawFirstPage('http://x/a.pdf', canvas, 400, new AbortController().signal);
    await drawFirstPage('http://x/b.pdf', canvas, 400, new AbortController().signal);
    const [first, second] = lib.state.options;
    expect(first).toMatchObject({ url: 'http://x/a.pdf', disableAutoFetch: true, disableStream: true, rangeChunkSize: 8 * 1024 * 1024 });
    expect(first.worker).toBeTruthy();
    expect(second.worker).toBe(first.worker);
    expect(lib.state.created).toBe(1);
    expect(lib.state.render).toBe(2);
    expect(lib.state.destroy).toBe(2);
    expect(canvas.width).toBeGreaterThanOrEqual(400);
  });

  it('przerwanie sygnałem niszczy dokument i nie rysuje', async () => {
    const abort = new AbortController();
    lib.state.onOpen = () => abort.abort();  // sygnał pada, gdy dokument już się otwiera, przed pobraniem strony
    const canvas = document.createElement('canvas');
    await expect(drawFirstPage('http://x/a.pdf', canvas, 400, abort.signal)).rejects.toBeTruthy();
    expect(lib.state.getPage).toBe(0);
    expect(lib.state.render).toBe(0);
    expect(lib.state.destroy).toBe(1);
  });

  it('po zamknięciu workera zakłada nowy', async () => {
    const canvas = document.createElement('canvas');
    await drawFirstPage('http://x/a.pdf', canvas, 400, new AbortController().signal);
    closePdfWorker();
    await drawFirstPage('http://x/a.pdf', canvas, 400, new AbortController().signal);
    expect(lib.state.created).toBe(2);
  });
});
