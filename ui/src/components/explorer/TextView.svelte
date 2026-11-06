<script lang="ts">
  import { findMatches, MARK_WINDOW, MAX_TEXT } from '../../lib/explorer/find';
  import { type ExplorerController } from '../../lib/explorer/controller';
  import { highlight, type Token } from '../../lib/explorer/highlight';
  import { formatBytes } from '../../lib/explorer/logic';
  import { i18n, t, tp } from '../../lib/i18n/index.svelte';
  import type { EntryView } from '../../lib/types';
  import Banner from '../../ui/Banner.svelte';
  import Button from '../../ui/Button.svelte';
  import Icon from '../../ui/Icon.svelte';
  import FindBar from './FindBar.svelte';

  /** Podgląd tekstu: czcionka stała, numery linii, kodowanie, „Kopiuj tekst”, „Pokaż więcej” i kolorowanie JSON/XML. */
  let { ex, entry }: { ex: ExplorerController; entry: EntryView } = $props();

  const COPIED_MS = 1500;
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
  const foundTokens = $derived.by(() => {
    let offset = 0;
    let hit = 0;
    const out: { text: string; cls: string; hit: number }[] = [];
    for (const token of tokens) {
      const end = offset + token.text.length;
      let at = offset;
      while (at < end) {
        while (hit < marked.length && marked[hit].end <= at) hit++;
        const match = marked[hit];
        const inside = match && match.start <= at;
        const to = Math.min(end, match ? inside ? match.end : match.start : end);
        out.push({ text: token.text.slice(at - offset, to - offset), cls: token.cls, hit: inside ? markFrom + hit : -1 });
        at = to;
      }
      offset = end;
    }
    return out;
  });
  $effect(() => { void matches; content?.querySelector<HTMLElement>(`[data-hit="${current}"]`)?.scrollIntoView?.({ block: 'center' }); });

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

  const kind = $derived(({ json: 'json', xml: 'xml' } as const)[entry.ext.toLowerCase() as 'json' | 'xml']);
  const lines = $derived(text === '' ? 0 : text.split('\n').length - (text.endsWith('\n') ? 1 : 0));
  const tokens = $derived<Token[]>(kind ? highlight(text, kind) : [{ cls: '', text }]);
  const gutter = $derived(Array.from({ length: lines }, (_, i) => i + 1).join('\n'));

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
  <div bind:this={content} class="min-h-0 flex-1 overflow-auto rounded-2xl bg-white/[.06] shadow-[inset_0_0_0_1px_rgb(255_255_255/.08)]">
    {#if failed}
      <div class="p-4"><Banner tone="bad" icon="triangle-alert">{t('explorer.preview.failed')}</Banner></div>
    {:else}
      <div class="flex min-w-max font-mono text-[13px] leading-[1.6] text-white/90">
        <pre aria-hidden="true" class="sticky left-0 flex-none bg-[#11141b] px-3 py-3 text-right text-white/35 select-none">{gutter}</pre>
        <pre class="flex-1 px-4 py-3">{#each foundTokens as tok, i (i)}{#if tok.hit >= 0}<mark data-hit={tok.hit} class:active={tok.hit === current}>{tok.text}</mark>{:else}<span class={tok.cls}>{tok.text}</span>{/if}{/each}</pre>
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
