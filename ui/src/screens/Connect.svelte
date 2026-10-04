<script lang="ts">
  import { getContext } from 'svelte';
  import ConnectChecklist from '../components/ConnectChecklist.svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import InterruptedBanner from '../components/InterruptedBanner.svelte';
  import MirrorControls from '../components/MirrorControls.svelte';
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

<main class="flex min-w-0 flex-1 gap-7 scroll-fade overflow-auto px-7 py-7">
  <div class="flex w-[260px] flex-none flex-col gap-3">
    <div>
      <h1 class="text-2xl font-extrabold">{t(`connect.title.${link}`)}</h1>
      <p class="mt-1 min-h-[44px] text-mut">{t(`connect.sub.${link}`)}</p>
    </div>
    <PhoneStage state={stage} />
    <ConnectChecklist label={t('connect.check.label')} items={[
      { label: t('connect.check.cable'), status: checks[0] },
      { label: t('connect.check.auth'), status: checks[1] },
      { label: t('connect.check.model'), status: checks[2] },
    ]} />
  </div>

  <div class="flex min-w-0 flex-1 flex-col gap-4">
    {#if s.interrupted.length}<InterruptedBanner orders={s.interrupted} />{/if}
    {#if link === 'adb_missing'}
      <Banner tone="bad" icon="triangle-alert" title={t('connect.adb_missing')}>
        {#snippet actions()}<Button onclick={() => ctl.openSettings()}>{t('connect.open_settings')}</Button>{/snippet}
      </Banner>
    {:else if link === 'ready' || link === 'many'}
      <div class="flex flex-col gap-2.5" in:enter>
        {#each ready as d (d.serial)}
          {#if ready.length > 1}
            <!-- Wiele telefonów: przyciski podglądu/zrzutu NIE mogą być potomkami <label>, bo klik
                 byłby przekazany do radia (zmieniałby wybrane urządzenie) — renderujemy je jako
                 rodzeństwo pod etykietą, wciąż wizualnie pod kartą tego telefonu. -->
            <div class="flex flex-col gap-2">
              <label class="block cursor-pointer rounded-2xl {s.serial === d.serial ? 'ring-2 ring-accent' : ''}">
                <input class="sr-only" type="radio" name="device" checked={s.serial === d.serial}
                  aria-label="{d.name ?? modelName(d.model)} {d.serial}" onchange={() => ctl.selectDevice(d.serial)} />
                <DeviceCard name={d.name ?? modelName(d.model)} details={t('connect.title.ready')} serial={d.serial} imei={d.imei} connected />
              </label>
              <div class="pl-[80px]"><MirrorControls serial={d.serial} name={d.name ?? modelName(d.model)} /></div>
            </div>
          {:else}
            <label class="block cursor-pointer rounded-2xl">
              <DeviceCard name={d.name ?? modelName(d.model)} details={t('connect.title.ready')} serial={d.serial} imei={d.imei} connected>
                <MirrorControls serial={d.serial} name={d.name ?? modelName(d.model)} />
              </DeviceCard>
            </label>
          {/if}
        {/each}
        <form class="flex gap-2" onsubmit={(e) => { e.preventDefault(); void ctl.startScan(); }}>
          <input class="field flex-1 rounded-xl px-3.5 py-2.5" bind:value={s.client}
            placeholder={t('connect.client_placeholder')} aria-label={t('connect.client_label')} maxlength="80" />
          <Button type="submit" variant="primary" size="lg" disabled={!s.serial}>{t('connect.scan')}</Button>
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
