<script lang="ts">
  import { tick, untrack } from 'svelte';
  import { findMatches, MARK_WINDOW, MAX_TEXT } from '../../lib/explorer/find';
  import { type ExplorerController } from '../../lib/explorer/controller';
  import { highlight, type Token } from '../../lib/explorer/highlight';
  import { formatBytes } from '../../lib/explorer/logic';
  import { rowAt, rowSegments, textRows, tokenStarts } from '../../lib/explorer/textrows';
  import { FALLBACK, type Viewport, viewport } from '../../lib/explorer/virtual';
  import { i18n, t, tp } from '../../lib/i18n/index.svelte';
  import type { EntryView } from '../../lib/types';
  import Banner from '../../ui/Banner.svelte';
  import Button from '../../ui/Button.svelte';
  import Icon from '../../ui/Icon.svelte';
  import FindBar from './FindBar.svelte';

  /** Podgląd tekstu: czcionka stała, numery linii, kodowanie, „Kopiuj tekst”, „Pokaż więcej” i kolorowanie JSON/XML. */
  let { ex, entry }: { ex: ExplorerController; entry: EntryView } = $props();

  const COPIED_MS = 1500;
  /** Wysokość wiersza (13 px × 1,6), odstęp treści od góry i dołu. */
  const ROW_H = 20.8;
  const PAD_Y = 12;
  /** Tyle wierszy pokazujemy w całości: krótki plik zaznacza się i kopiuje jak zwykły tekst. Dłuższy ma w DOM tylko
   *  okno wokół ekranu (całość kopiuje przycisk). */
  const FULL_ROWS = 1500;
  const AROUND = 60;
  /** Powyżej tego kolorowanie (obiekt na każdy token) kosztowałoby więcej niż jest warte. */
  const HIGHLIGHT_MAX = 4 * 1024 * 1024;
  let text = $state('');
  let encoding = $state('');
  let truncated = $state(false);
  let loading = $state(true);
  let failed = $state(false);
  let copied = $state(false);
  let copyTimer: ReturnType<typeof setTimeout> | undefined;
  let query = $state('');
  let whole = $state(false);
  let current = $state(0);
  let content: HTMLElement;
  let loadingAll = $state(false);
  let disposed = false;
  const matches = $derived(findMatches(text, query, whole));
  /** Więcej pliku nie wczytamy, choć jeszcze jest. */
  const capped = $derived(truncated && text.length >= MAX_TEXT);
  const markFrom = $derived(Math.max(0, current - MARK_WINDOW));
  const marked = $derived(matches.slice(markFrom, current + MARK_WINDOW));
  let vp = $state.raw<Viewport>({ top: 0, ...FALLBACK });
  const kind = $derived(({ json: 'json', xml: 'xml' } as const)[entry.ext.toLowerCase() as 'json' | 'xml']);
  const tokens = $derived<Token[]>(kind && text.length <= HIGHLIGHT_MAX ? highlight(text, kind) : [{ cls: '', text }]);
  const starts = $derived(tokenStarts(tokens));
  const rows = $derived(textRows(text));
  const first = $derived(rows.count <= FULL_ROWS ? 0 : Math.max(0, Math.floor((vp.top - PAD_Y) / ROW_H) - AROUND));
  const last = $derived(rows.count <= FULL_ROWS ? rows.count : Math.min(rows.count, Math.ceil((vp.top + vp.height) / ROW_H) + AROUND));
  const pieces = $derived(rowSegments(text, rows, tokens, starts, first, last, marked, markFrom));
  const gutter = $derived(Array.from(rows.lines.subarray(first, last), (n) => n || '').join('\n'));

  /** Bieżące trafienie na ekran: najpierw wiersz (może go nie być w DOM), potem znacznik w poziomie. */
  async function showHit(): Promise<void> {
    const hit = matches[current];
    if (!hit || !content) return;
    const target = PAD_Y + rowAt(rows, hit.start) * ROW_H;
    if (target < content.scrollTop || target + ROW_H > content.scrollTop + content.clientHeight) {
      content.scrollTop = target - content.clientHeight / 2;
      vp = { ...vp, top: content.scrollTop };
    }
    await tick();
    content?.querySelector<HTMLElement>(`[data-hit="${current}"]`)?.scrollIntoView?.({ block: 'nearest', inline: 'center' });
  }
  $effect(() => {
    void matches;
    void current;
    untrack(() => void showHit());
  });

  function search(q: string, w: boolean): void {
    query = q;
    whole = w;
    current = 0;
  }
  function step(delta: number): void {
    if (matches.length) current = (current + delta + matches.length) % matches.length;
  }
  async function loadAll(): Promise<void> {
    loadingAll = true;
    try { while (truncated && !capped && !failed && !disposed) await load(true); }
    finally { loadingAll = false; }
  }

  const lines = $derived(rows.total);

  async function load(more: boolean): Promise<void> {
    const path = entry.path;
    loading = true;
    const r = await ex.text(path, more);
    if (disposed || path !== entry.path) return;  // przeskok na inny plik w trakcie odczytu
    loading = false;
    if (!r) {
      failed = true;
      return;
    }
    text = more ? text + r.text : r.text;
    encoding = r.encoding;
    truncated = r.truncated;
  }
  $effect(() => {
    void entry.path;
    disposed = false;
    void load(false);
    return () => { disposed = true; clearTimeout(copyTimer); };
  });

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      return;  // schowek zablokowany — bez udawania, że się udało
    }
    copied = true;
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => (copied = false), COPIED_MS);
  }
</script>

<div class="absolute inset-0 flex flex-col gap-3 p-6">
  <div class="flex flex-none items-center gap-3 text-xs text-white/70">
    {#if encoding}<span class="rounded-full bg-white/10 px-2.5 py-0.5 font-semibold">{t('explorer.preview.encoding', { encoding })}</span>{/if}
    {#if lines > 0}<span class="tabular-nums">{tp('explorer.preview.lines', lines)}</span>{/if}
    <span class="flex-1"></span>
    <button type="button" onclick={copy} disabled={!text}
      class="inline-flex items-center gap-1.5 rounded-[10px] bg-white/10 px-3 py-1.5 font-semibold text-white transition duration-150
        enabled:hover:bg-white/20 disabled:opacity-50">
      <Icon name={copied ? 'check' : 'copy'} size={14} />{copied ? t('explorer.preview.text_copied') : t('explorer.preview.copy_text')}
    </button>
  </div>
  <FindBar total={matches.length} {current} onsearch={search} onstep={step} />
  {#if capped}
    <p class="flex-none text-xs text-white/70">{t('explorer.preview.text_limit', { size: formatBytes(MAX_TEXT, i18n.lang) })}</p>
  {:else if query && truncated}
    <div class="flex flex-none items-center justify-between gap-3 text-xs text-white/70">
      <span>{t('explorer.preview.find_partial')}</span>
      <Button size="sm" disabled={loading || loadingAll} onclick={loadAll}>{t('explorer.preview.find_load_all')}</Button>
    </div>
  {/if}
  <div bind:this={content} {@attach viewport((v) => (vp = v))}
    class="min-h-0 flex-1 overflow-auto rounded-2xl bg-white/[.06] shadow-[inset_0_0_0_1px_rgb(255_255_255/.08)]">
    {#if failed}
      <div class="p-4"><Banner tone="bad" icon="triangle-alert">{t('explorer.preview.failed')}</Banner></div>
    {:else}
      <div class="relative font-mono text-[13px] leading-[1.6] text-white/90" data-lines
        style:height="{rows.count * ROW_H + 2 * PAD_Y}px" style:min-width="calc({rows.width}ch + {String(rows.total).length}ch + 3.5rem)">
        <div class="absolute inset-x-0 flex min-w-max" style:top="{first * ROW_H}px">
          <pre aria-hidden="true" class="sticky left-0 flex-none bg-[#11141b] px-3 py-3 text-right text-white/35 select-none"
            style:min-width="calc({String(rows.total).length}ch + 1.5rem)">{gutter}</pre>
          <pre class="flex-1 px-4 py-3">{#each pieces as tok, i (i)}{#if tok.hit >= 0}<mark data-hit={tok.hit} class:active={tok.hit === current}>{tok.text}</mark>{:else}<span class={tok.cls}>{tok.text}</span>{/if}{/each}</pre>
        </div>
      </div>
      {#if loading}<span class="spin m-4 inline-block" role="status" aria-label={t('explorer.preview.loading')}></span>{/if}
    {/if}
    {#if truncated && !capped && !loading}
      <div class="sticky left-0 p-4">
        <Button size="sm" variant="secondary" disabled={loadingAll} onclick={() => load(true)}>{t('explorer.preview.more')}</Button>
      </div>
    {/if}
  </div>
</div>

<style>
  mark { background: #fde68a; color: #111827; border-radius: 2px; }
  mark.active { background: #fb923c; outline: 2px solid #fff; }
  .tok-key, .tok-tag { color: #93c5fd; }
  .tok-str, .tok-val { color: #86efac; }
  .tok-num { color: #fcd34d; }
  .tok-lit { color: #f0abfc; }
  .tok-attr { color: #fdba74; }
  .tok-com { color: #94a3b8; font-style: italic; }
</style>
