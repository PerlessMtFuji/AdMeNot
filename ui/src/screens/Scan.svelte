<script lang="ts">
  import { getContext } from 'svelte';
  import ConnectChecklist from '../components/ConnectChecklist.svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { modelName, SCAN_STEPS, scanChecklist } from '../lib/logic';
  import SidePanel from '../ui/SidePanel.svelte';

  const s = getContext<Controller>('ctl').state;
  const entry = $derived(s.devices.find((d) => d.serial === s.serial) ?? null);
  const name = $derived(s.device?.name ?? modelName(entry?.model ?? null));
  const checks = $derived(scanChecklist(s.scanStage));
  const details = $derived(s.device
    ? `${s.device.model} · Android ${s.device.android}${s.device.patch ? ` · ${t('phone.patch')} ${s.device.patch}` : ''}`
    : modelName(entry?.model ?? null));
</script>

<div class="flex min-h-0 flex-1">
  <main class="flex min-w-0 flex-1 flex-col gap-4 overflow-auto px-6 py-5">
    <div>
      <div class="text-[11.5px] font-semibold text-soft">{s.client.trim()}</div>
      <h1 class="text-[19px] font-extrabold">{t('scan.title')}</h1>
      <p class="text-mut">{t('scan.sub')}</p>
    </div>
    <div class="flex items-start gap-5">
      <div class="relative grid h-[260px] w-[200px] flex-none place-items-center overflow-hidden rounded-2xl bg-[linear-gradient(160deg,var(--color-accent-soft),var(--color-surface))] shadow-card">
        {#if s.device}
          <img class="max-h-[220px] drop-shadow-[0_8px_10px_rgba(17,24,39,.25)]" src={s.device.image} alt={s.device.name} />
        {:else}
          <span class="h-[160px] w-[80px] rounded-[14px] bg-[#1f2937]" aria-hidden="true"></span>
        {/if}
        <div class="scanline"></div>
      </div>
      <div class="w-[320px]">
        <ConnectChecklist label={t('scan.steps')}
          items={SCAN_STEPS.map((k, i) => ({ label: t(`scan.stage.${k}`), status: checks[i] }))} />
      </div>
    </div>
  </main>
  <SidePanel label={t('phone.subject')}>
    <DeviceCard compact name={name} serial={s.serial ?? ''} image={s.device?.image ?? null}
      {details} connected />
  </SidePanel>
</div>
