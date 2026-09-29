<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  let { serial, name }: { serial: string; name: string } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const mine = $derived(s.mirror.serial === serial);
  const state = $derived(mine ? s.mirror.state : 'stopped');
  const active = $derived(state === 'starting' || state === 'running');
  const missingId = $derived(`mirror-missing-${serial}`);
</script>

<div class="flex flex-col gap-2">
  <div class="flex flex-wrap items-center gap-2">
    <Button size="sm" disabled={!s.mirror.available || state === 'starting'}
      describedby={s.mirror.available ? undefined : missingId}
      onclick={() => (active ? ctl.mirrorStop() : ctl.mirrorStart(serial, name))}>
      <Icon name={active ? 'screen-share-off' : 'screen-share'} />
      {state === 'starting' ? t('mirror.starting') : active ? t('mirror.stop') : t('mirror.start')}
    </Button>
    <Button size="sm" variant="ghost" disabled={s.shotBusy} onclick={() => ctl.takeScreenshot(serial)}>
      <Icon name="camera" />{s.shotBusy ? t('shot.busy') : t('shot.take')}
    </Button>
  </div>
  {#if !s.mirror.available}<span id={missingId} class="text-xs text-mut">{t('mirror.missing')}</span>{/if}
  {#if mine && active && s.mirror.blocked}
    <Banner tone="warn" icon="info" title={t('mirror.blocked_title')}>{t('mirror.blocked_text')}</Banner>
  {/if}
  {#if s.lastShot && s.lastShotSerial === serial}
    <div class="flex items-center gap-2 text-xs text-mut" role="status">
      {#if s.lastShot.image}<img src={s.lastShot.image} alt="" class="h-10 w-auto rounded-md border border-line" />{/if}
      <span>{tp('shot.count', s.shotCount)}{s.lastShot.black ? ` · ${t('shot.black')}` : ''}</span>
    </div>
  {/if}
</div>
