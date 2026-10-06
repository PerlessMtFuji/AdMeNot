<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import type { WhoView } from '../lib/types';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import ShotStatus from './ShotStatus.svelte';

  let { ask }: { ask: () => Promise<WhoView | null> } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  let busy = $state(false);
  let saved = $state(false); // potwierdzenie tuż pod przyciskiem, nie tylko w panelu bocznym
  const view = $derived(s.who);
  const serial = $derived(s.device?.serial ?? s.serial);

  async function run() {
    busy = true;
    saved = false;
    try {
      s.who = await ask();
    } finally {
      busy = false;
    }
  }

  async function shoot(serial: string) {
    await ctl.takeScreenshot(serial);
    saved = s.lastShotSerial === serial;
  }
</script>

<div class="flex items-center gap-2">
  <h2 class="min-w-0 flex-1 text-md font-bold">{t('diag.title')}</h2>
  <Button size="sm" variant="ghost" onclick={() => ctl.closeDiagnostics()}><Icon name="arrow-left" size={14} />{t('diag.back')}</Button>
</div>

<section class="flex flex-col gap-2">
  <Button disabled={busy} onclick={run}><Icon name="scan-search" />{t('who.button')}</Button>
  <p class="text-xs text-mut">{t('who.hint')}</p>
  {#if view}
    <div class="well p-3 text-sm" role="status">
      <p>{view.resumed ? t('who.resumed', { name: view.resumed.name }) : t('who.unknown')}</p>
      <p>
        {#if view.overlays === null}{t('who.overlays_unknown')}
        {:else if view.overlays.length}{t('who.overlays', { names: view.overlays.map((o) => o.name).join(', ') })}
        {:else}{t('who.none')}{/if}
      </p>
      {#if serial}
        <div class="mt-2 flex flex-wrap items-center gap-3">
          <Button size="sm" variant="ghost" disabled={s.shotBusy} onclick={() => shoot(serial)}>
            <Icon name="camera" />{s.shotBusy ? t('shot.busy') : t('shot.with_caption')}</Button>
          {#if saved}<ShotStatus {serial} />{/if}
        </div>
      {/if}
    </div>
  {/if}
</section>

<div class="h-px bg-line"></div>

<section class="flex flex-col gap-2">
  {#if s.incident.recording}
    <Button variant="primary" onclick={() => ctl.markIncident()}><Icon name="megaphone" />{t('incident.mark')}</Button>
    <p class="text-xs text-mut" role="status">{t('incident.recording', { marks: s.incident.marks })}</p>
  {:else}
    <Button variant="ghost" disabled={!s.device} onclick={() => ctl.startIncident(120)}><Icon name="eye" />{t('incident.start')}</Button>
    <p class="text-xs text-mut">{t('incident.hint')}</p>
  {/if}
  {#if !s.incident.recording && s.incident.result}
    <div class="well p-3 text-sm" role="status">
      {#if !s.incident.result.marks}<p>{t('incident.none')}</p>
      {:else}
        <ul class="flex flex-col gap-1">
          {#each s.incident.result.hits as h (`${h.mark}-${h.kind}-${h.package}`)}
            <li>{t(`incident.kind.${h.kind}`, { name: h.name, over: h.over_name ?? '?', t: Math.round(h.mark) })}</li>
          {/each}
          {#if !s.incident.result.hits.length}<li>{t('incident.undetermined')}</li>{/if}
        </ul>
        <p class="mt-1 text-xs text-mut">{t('incident.next_scan')}</p>
      {/if}
    </div>
  {/if}
</section>
