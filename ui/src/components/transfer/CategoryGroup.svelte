<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../../lib/i18n/index.svelte';

  // Karta z nagłówkiem grupy i wierszami `CategoryRow` rozdzielonymi cienką linią.
  // `bare`: karta bez widocznego nagłówka (ekran wyniku: jedna karta, tytuł tylko dla czytników ekranu).
  // `empty`: kategorie (`missingKey` — przedrostek, domyślnie „Brak w kopii”), których nie ma w kopii — jedna szara linia na dole.
  let { title, children, empty, missingKey = 'transfer.row.missing', bare = false }: { title: string; children: Snippet; empty?: string; missingKey?: string; bare?: boolean } = $props();
</script>

<section class="card shrink-0 overflow-hidden rounded-2xl border border-line shadow-sm" aria-label={title}>
  <h3 class={bare ? 'sr-only' : 'px-4 pt-2.5 pb-0.5 text-xs font-bold tracking-wider text-soft uppercase'}>{title}</h3>
  <div class="flex flex-col divide-y divide-line">
    {@render children()}
  </div>
  {#if empty}
    <p class="border-t border-line px-4 py-2 text-xs text-soft">{t(missingKey, { what: empty })}</p>
  {/if}
</section>
