<script lang="ts">
  import { getContext } from 'svelte';
  import ConnectChecklist from '../components/ConnectChecklist.svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import InterruptedBanner from '../components/InterruptedBanner.svelte';
  import PhoneStage from '../components/PhoneStage.svelte';
  import UsbGuide from '../components/UsbGuide.svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { connectChecklist, linkState, modelName } from '../lib/logic';
  import { enter } from '../lib/motion';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const link = $derived(linkState(s.devices, s.devicesError));
  const ready = $derived(s.devices.filter((d) => d.state === 'device'));
  const pending = $derived(s.devices.find((d) => d.state !== 'device') ?? null);
  const stage = $derived(link === 'ready' || link === 'many' ? 'ok'
    : link === 'unauthorized' ? 'auth' : link === 'offline' ? 'offline' : 'wait');
  const checks = $derived(connectChecklist(link));
  const known = $derived(pending !== null && s.knownSerials.includes(pending.serial));
</script>

<main class="flex min-w-0 flex-1 gap-5 overflow-auto px-6 py-5">
  <div class="flex w-[260px] flex-none flex-col gap-3">
    <div>
      <h1 class="text-[17px] font-extrabold">{t(`connect.title.${link}`)}</h1>
      <p class="mt-0.5 min-h-[34px] text-mut">{t(`connect.sub.${link}`)}</p>
    </div>
    <PhoneStage state={stage} />
    <ConnectChecklist label={t('connect.check.label')} items={[
      { label: t('connect.check.cable'), status: checks[0] },
      { label: t('connect.check.auth'), status: checks[1] },
      { label: t('connect.check.model'), status: checks[2] },
    ]} />
  </div>

  <div class="flex min-w-0 flex-1 flex-col gap-3">
    {#if s.interrupted.length}<InterruptedBanner orders={s.interrupted} />{/if}
    {#if link === 'adb_missing'}
      <Banner tone="bad" icon="triangle-alert" title={t('connect.adb_missing')}>
        {#snippet actions()}<Button onclick={() => ctl.openSettings()}>{t('connect.open_settings')}</Button>{/snippet}
      </Banner>
    {:else if link === 'ready' || link === 'many'}
      <div class="flex flex-col gap-2.5" in:enter>
        {#each ready as d (d.serial)}
          <label class="block cursor-pointer rounded-2xl {s.serial === d.serial && ready.length > 1 ? 'ring-2 ring-accent' : ''}">
            {#if ready.length > 1}
              <input class="sr-only" type="radio" name="device" checked={s.serial === d.serial}
                aria-label="{modelName(d.model)} {d.serial}" onchange={() => ctl.selectDevice(d.serial)} />
            {/if}
            <DeviceCard name={modelName(d.model)} details={t('connect.title.ready')} serial={d.serial} connected />
          </label>
        {/each}
        <form class="flex gap-2" onsubmit={(e) => { e.preventDefault(); void ctl.startScan(); }}>
          <input class="flex-1 rounded-[10px] border border-line bg-surface px-3 py-2" bind:value={s.client}
            placeholder={t('connect.client_placeholder')} aria-label={t('connect.client_label')} maxlength="80" />
          <Button type="submit" variant="primary" disabled={!s.serial}>{t('connect.scan')}</Button>
        </form>
      </div>
    {:else}
      <!-- nowy telefon albo historia wczytana po pierwszym renderze: przewodnik liczy stan od nowa -->
      {#key `${pending?.serial ?? ''}|${known}`}
        <UsbGuide model={pending?.model ?? null} collapsed={known} />
      {/key}
    {/if}
  </div>
</main>
