<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import type { WhoView } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  let { ask }: { ask: () => Promise<WhoView | null> } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  let busy = $state(false);
  let view = $state<WhoView | null>(null);
  const serial = $derived(s.device?.serial ?? s.serial);
  const canMirror = $derived(serial !== null && s.mirror.available && !ctl.mirrorActive(serial));

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
  <div class="flex flex-wrap items-center gap-3">
    <Button disabled={busy} onclick={run}><Icon name="scan-search" />{t('who.button')}</Button>
    <span class="text-xs text-mut">{t('who.hint')}</span>
    {#if canMirror && serial}
      <button type="button" class="text-sm font-semibold text-accent hover:underline"
        onclick={() => ctl.mirrorStart(serial, s.device?.name ?? serial)}>{t('mirror.wait_for_ad')}</button>
    {/if}
  </div>
  {#if view}
    <div class="well p-3 text-sm" role="status">
      <p>{view.resumed ? t('who.resumed', { name: view.resumed.name }) : t('who.unknown')}</p>
      <p>
        {#if view.overlays === null}{t('who.overlays_unknown')}
        {:else if view.overlays.length}{t('who.overlays', { names: view.overlays.map((o) => o.name).join(', ') })}
        {:else}{t('who.none')}{/if}
      </p>
      {#if serial}
        <div class="mt-2"><Button size="sm" variant="ghost" disabled={s.shotBusy} onclick={() => ctl.takeScreenshot(serial)}>
          <Icon name="camera" />{t('shot.with_caption')}</Button></div>
      {/if}
    </div>
  {/if}
</div>
