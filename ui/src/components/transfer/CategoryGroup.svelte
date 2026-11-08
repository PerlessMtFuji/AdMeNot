<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../../lib/i18n/index.svelte';

  // Karta z nagłówkiem grupy i wierszami `CategoryRow` rozdzielonymi cienką linią.
  // `empty`: kategorie (`missingKey` — przedrostek, domyślnie „Brak w kopii”), których nie ma w kopii — jedna szara linia na dole.
  let { title, children, empty, missingKey = 'transfer.row.missing' }: { title: string; children: Snippet; empty?: string; missingKey?: string } = $props();
</script>

<section class="card overflow-hidden rounded-2xl border border-line shadow-sm" aria-label={title}>
  <h3 class="px-4 pt-2.5 pb-0.5 text-xs font-bold tracking-wider text-soft uppercase">{title}</h3>
  <div class="flex flex-col divide-y divide-line">
    {@render children()}
  </div>
  {#if empty}
    <p class="border-t border-line px-4 py-2 text-xs text-soft">{t(missingKey, { what: empty })}</p>
  {/if}
</section>
