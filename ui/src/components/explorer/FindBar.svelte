<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';
  import { MAX_MATCHES } from '../../lib/explorer/find';
  import Icon from '../../ui/Icon.svelte';

  /** Pasek szukania podglądu tekstu i PDF-a. Zapytanie trafia dalej z małym opóźnieniem, żeby pisanie nie
   *  czekało na przeszukanie dużego pliku. Ctrl+F przenosi do pola; Esc czyści je, a w pustym — zamyka podgląd. */
  type Props = { total: number; current: number; onsearch: (query: string, whole: boolean) => void;
    onstep: (delta: number) => void };
  let { total, current, onsearch, onstep }: Props = $props();

  const DEBOUNCE_MS = 120;
  const BTN = 'rounded-lg bg-white/10 p-2 disabled:opacity-40';
  let value = $state('');
  let whole = $state(false);
  let input: HTMLInputElement;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function changed(delay = DEBOUNCE_MS): void {
    clearTimeout(timer);
    timer = setTimeout(() => onsearch(value, whole), delay);
  }
  $effect(() => () => clearTimeout(timer));

  function onkey(e: KeyboardEvent): void {
    if (e.key === 'Enter') {
      e.preventDefault();
      onstep(e.shiftKey ? -1 : 1);
    } else if (e.key === 'Escape' && value) {
      e.stopPropagation();
      value = '';
      changed(0);
    }
  }
  function onwindowkey(e: KeyboardEvent): void {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
      e.preventDefault();
      input?.focus();
      input?.select();
    }
  }
  const count = $derived(t(total >= MAX_MATCHES ? 'explorer.preview.find_count_many' : 'explorer.preview.find_count',
    { current: total ? current + 1 : 0, total }));
</script>

<svelte:window onkeydown={onwindowkey} />

<div class="flex flex-none flex-wrap items-center gap-2 text-xs text-white/80">
  <input bind:this={input} bind:value type="search" aria-label={t('explorer.preview.find_label')} oninput={() => changed()}
    placeholder={t('explorer.preview.find_placeholder')} onkeydown={onkey}
    class="min-w-0 flex-1 rounded-lg bg-white/10 px-3 py-2 outline-none focus:ring-2 focus:ring-accent" />
  <label class="flex items-center gap-1.5">
    <input type="checkbox" bind:checked={whole} onchange={() => changed(0)} />{t('explorer.preview.find_whole')}
  </label>
  <span role="status" aria-live="polite">{count}</span>
  <button type="button" disabled={!total} onclick={() => onstep(-1)} aria-label={t('explorer.preview.find_prev')} class={BTN}>
    <Icon name="chevron-left" size={14} />
  </button>
  <button type="button" disabled={!total} onclick={() => onstep(1)} aria-label={t('explorer.preview.find_next')} class={BTN}>
    <Icon name="chevron-right" size={14} />
  </button>
</div>
