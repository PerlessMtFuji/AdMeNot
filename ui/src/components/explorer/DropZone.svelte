<script lang="ts">
  import { fade } from 'svelte/transition';
  import { formatBytes } from '../../lib/explorer/logic';
  import type { DropInfo } from '../../lib/explorer/state.svelte';
  import { i18n, t, tp } from '../../lib/i18n/index.svelte';
  import { DUR, ms } from '../../lib/motion';
  import Icon from '../../ui/Icon.svelte';

  /** Strefa upuszczania nad listą: pliki z Eksploratora Windows trafią do bieżącego folderu telefonu. */
  let { drop, folder }: { drop: DropInfo; folder: string } = $props();
  const facts = $derived([
    drop.count !== null ? tp('explorer.drop.items', drop.count) : null,
    drop.bytes !== null ? formatBytes(drop.bytes, i18n.lang) : null,
  ].filter(Boolean).join(' · '));
</script>

<div transition:fade={{ duration: ms(DUR.micro) }}
  class="pointer-events-none absolute inset-0 z-20 grid place-items-center rounded-2xl border-2 border-dashed border-accent bg-accent-soft/90">
  <div class="flex flex-col items-center gap-1.5 text-center">
    <span class="grid h-12 w-12 place-items-center rounded-2xl bg-accent text-white"><Icon name="upload" size={22} /></span>
    <b class="text-ink">{drop.dropped ? t('explorer.drop.preparing', { folder }) : t('explorer.drop.title', { folder })}</b>
    {#if facts}<span class="text-sm text-mut">{facts}</span>{/if}
  </div>
</div>
