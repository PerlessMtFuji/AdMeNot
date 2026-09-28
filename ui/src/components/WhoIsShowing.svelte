<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';
  import type { WhoView } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  let { ask }: { ask: () => Promise<WhoView | null> } = $props();
  let busy = $state(false);
  let view = $state<WhoView | null>(null);

  async function run() {
    busy = true;
    try {
      view = await ask();
    } finally {
      busy = false;
    }
  }
</script>

<div class="flex flex-col gap-2">
  <div class="flex items-center gap-3">
    <Button disabled={busy} onclick={run}><Icon name="scan-search" />{t('who.button')}</Button>
    <span class="text-xs text-mut">{t('who.hint')}</span>
  </div>
  {#if view}
    <div class="well p-3 text-sm" role="status">
      <p>{view.resumed ? t('who.resumed', { name: view.resumed.name }) : t('who.unknown')}</p>
      <p>{view.overlays.length ? t('who.overlays', { names: view.overlays.map((o) => o.name).join(', ') }) : t('who.none')}</p>
    </div>
  {/if}
</div>
