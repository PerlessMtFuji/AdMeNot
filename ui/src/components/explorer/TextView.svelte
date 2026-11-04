<script lang="ts">
  import { type ExplorerController } from '../../lib/explorer/controller';
  import { highlight, type Token } from '../../lib/explorer/highlight';
  import { t, tp } from '../../lib/i18n/index.svelte';
  import type { EntryView } from '../../lib/types';
  import Banner from '../../ui/Banner.svelte';
  import Button from '../../ui/Button.svelte';
  import Icon from '../../ui/Icon.svelte';

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

  const kind = $derived(({ json: 'json', xml: 'xml' } as const)[entry.ext.toLowerCase() as 'json' | 'xml']);
  const lines = $derived(text === '' ? 0 : text.split('\n').length - (text.endsWith('\n') ? 1 : 0));
  const tokens = $derived<Token[]>(kind ? highlight(text, kind) : [{ cls: '', text }]);
  const gutter = $derived(Array.from({ length: lines }, (_, i) => i + 1).join('\n'));

  async function load(more: boolean): Promise<void> {
    const path = entry.path;
    loading = true;
    const r = await ex.text(path, more);
    if (path !== entry.path) return;  // przeskok na inny plik w trakcie odczytu
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
    void load(false);
    return () => clearTimeout(copyTimer);
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
  <div class="min-h-0 flex-1 overflow-auto rounded-2xl bg-white/[.06] shadow-[inset_0_0_0_1px_rgb(255_255_255/.08)]">
    {#if failed}
      <div class="p-4"><Banner tone="bad" icon="triangle-alert">{t('explorer.preview.failed')}</Banner></div>
    {:else}
      <div class="flex min-w-max font-mono text-[13px] leading-[1.6] text-white/90">
        <pre aria-hidden="true" class="sticky left-0 flex-none bg-[#11141b] px-3 py-3 text-right text-white/35 select-none">{gutter}</pre>
        <pre class="flex-1 px-4 py-3">{#each tokens as tok, i (i)}<span class={tok.cls}>{tok.text}</span>{/each}</pre>
      </div>
      {#if loading}<span class="spin m-4 inline-block" role="status" aria-label={t('explorer.preview.loading')}></span>{/if}
    {/if}
    {#if truncated && !loading}
      <div class="sticky left-0 p-4">
        <Button size="sm" variant="secondary" onclick={() => load(true)}>{t('explorer.preview.more')}</Button>
      </div>
    {/if}
  </div>
</div>

<style>
  .tok-key, .tok-tag { color: #93c5fd; }
  .tok-str, .tok-val { color: #86efac; }
  .tok-num { color: #fcd34d; }
  .tok-lit { color: #f0abfc; }
  .tok-attr { color: #fdba74; }
  .tok-com { color: #94a3b8; font-style: italic; }
</style>
