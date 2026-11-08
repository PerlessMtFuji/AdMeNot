<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import { VERDICT_TONE } from '../lib/logic';
  import type { Verdict } from '../lib/types';
  import Pill from '../ui/Pill.svelte';

  // Puste kategorie groźnych werdyktów w jednym wierszu: „Szkodliwe 0 · Podejrzane 0 — nic nie znaleziono”.
  let { verdicts }: { verdicts: Verdict[] } = $props();
</script>

{#if verdicts.length > 0}
  <div data-testid="empty-verdicts" class="flex flex-wrap items-center gap-2 text-xs font-bold tracking-wide text-soft uppercase">
    {#each verdicts as v, i (v)}
      {#if i > 0}<span aria-hidden="true">·</span>{/if}
      <Pill tone={VERDICT_TONE[v]}>{t(`groups.${v}`)}</Pill><span class="mono">0</span>
    {/each}
    <span class="font-semibold normal-case">— {t('groups.empty')}</span>
  </div>
{/if}
