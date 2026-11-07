import { beforeEach, describe, expect, it, vi } from 'vitest';

const lib = vi.hoisted(() => {
  const state = { destroy: 0, render: 0, cancel: 0, getPage: 0, created: 0, options: [] as Record<string, unknown>[],
    onOpen: null as (() => void) | null, onDestroy: null as (() => void) | null, onCancel: null as (() => void) | null,
    loading: null as Promise<unknown> | null, drawing: null as Promise<void> | null };
  const page = {
    getViewport: ({ scale }: { scale: number }) => ({ width: 200 * scale, height: 300 * scale }),
    render: () => {
      state.render++;
      return { promise: state.drawing ?? Promise.resolve(), cancel: () => { state.cancel++; state.onCancel?.(); } };
    },
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
        return { promise: state.loading ?? Promise.resolve(doc), destroy: async () => { state.destroy++; state.onDestroy?.(); } };
      },
    },
  };
});
vi.mock('pdfjs-dist', () => lib.mock);

import { closePdfWorker, drawFirstPage } from './pdf';

beforeEach(() => {
  closePdfWorker();
  Object.assign(lib.state, { destroy: 0, render: 0, cancel: 0, getPage: 0, created: 0, options: [], onOpen: null,
    onDestroy: null, onCancel: null, loading: null, drawing: null });
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

  it('przerwanie w trakcie ładowania od razu niszczy zadanie, a jego odrzucenie kończy rysowanie', async () => {
    let fail!: (e: Error) => void;
    lib.state.loading = new Promise((_, reject) => { fail = reject; });
    lib.state.onDestroy = () => fail(new Error('pdf.js: zadanie zniszczone'));
    const abort = new AbortController();
    const run = drawFirstPage('http://x/a.pdf', document.createElement('canvas'), 400, abort.signal);
    await vi.waitFor(() => expect(lib.state.options).toHaveLength(1));
    expect(lib.state.destroy).toBe(0);
    abort.abort();
    expect(lib.state.destroy).toBe(1);  // bez czekania na `task.promise`
    await expect(run).rejects.toThrow('zniszczone');
    expect(lib.state.getPage).toBe(0);
    expect(lib.state.render).toBe(0);
    expect(lib.state.cancel).toBe(0);  // rysowanie jeszcze nie ruszyło
    expect(lib.state.destroy).toBe(1);  // `finally` nie niszczy drugi raz
  });

  it('przerwanie w trakcie rysowania anuluje je i niszczy dokument raz', async () => {
    let fail!: (e: Error) => void;
    lib.state.drawing = new Promise((_, reject) => { fail = reject; });
    lib.state.onCancel = () => fail(new Error('pdf.js: rysowanie anulowane'));
    const abort = new AbortController();
    const run = drawFirstPage('http://x/a.pdf', document.createElement('canvas'), 400, abort.signal);
    await vi.waitFor(() => expect(lib.state.render).toBe(1));
    abort.abort();
    expect(lib.state.cancel).toBe(1);
    expect(lib.state.destroy).toBe(1);
    await expect(run).rejects.toThrow('anulowane');
    expect(lib.state.destroy).toBe(1);
  });

  it('po zakończeniu rysowania sygnał nic już nie rusza', async () => {
    const abort = new AbortController();
    await drawFirstPage('http://x/a.pdf', document.createElement('canvas'), 400, abort.signal);
    abort.abort();
    expect(lib.state.cancel).toBe(0);
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
