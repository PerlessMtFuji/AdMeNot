<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import type { ShotView } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Dialog from '../ui/Dialog.svelte';

  let { order }: { order: string } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const view = $derived(s.shots[order]);
  const chosen = $derived(view ? view.items.filter((i) => i.in_report).length : 0);
  let zoom = $state<ShotView | null>(null);

  onMount(() => {
    if (!s.shots[order]) void ctl.loadShots(order);
  });
</script>

{#if view && view.items.length}
  <div class="flex flex-col gap-2">
    <div class="flex items-center justify-between gap-2">
      <span class="lbl">{t('shot.strip_title')}</span>
      <span class="text-xs text-mut tabular-nums">{t('shot.chosen', { count: chosen, limit: view.limit })}</span>
    </div>
    <ul class="flex flex-wrap gap-2">
      {#each view.items as item (item.id)}
        <li class="flex w-[72px] flex-col items-center gap-1">
          <button type="button" class="block overflow-hidden rounded-lg border border-line bg-surface-2"
            aria-label={t('shot.zoom', { caption: item.caption })} title={item.caption} onclick={() => (zoom = item)}>
            {#if item.image}<img src={item.image} alt="" class="h-[112px] w-[64px] object-cover" />{/if}
          </button>
          <label class="flex items-center gap-1 text-2xs text-mut">
            <input type="checkbox" checked={item.in_report} disabled={!item.in_report && chosen >= view.limit}
              onchange={(e) => ctl.setShotInReport(order, item.id, e.currentTarget.checked)} />{t('shot.in_report')}
          </label>
        </li>
      {/each}
    </ul>
  </div>
{/if}

{#if zoom}
  {@const shown = zoom}
  <Dialog title={shown.caption} oncancel={() => (zoom = null)}>
    {#if shown.image}<img src={shown.image} alt={shown.caption} class="mx-auto max-h-[70vh] w-auto rounded-lg" />{/if}
    {#snippet actions()}<Button onclick={() => (zoom = null)}>{t('common.close')}</Button>{/snippet}
  </Dialog>
{/if}
