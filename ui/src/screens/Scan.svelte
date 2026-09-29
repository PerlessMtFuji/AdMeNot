<script lang="ts">
  import { getContext } from 'svelte';
  import ConnectChecklist from '../components/ConnectChecklist.svelte';
  import DeviceCard from '../components/DeviceCard.svelte';
  import MirrorControls from '../components/MirrorControls.svelte';
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

<div class="flex min-h-0 min-w-0 flex-1">
  <main class="flex min-w-0 flex-1 flex-col gap-4 scroll-fade overflow-auto px-7 py-7">
    <div>
      <div class="text-sm font-semibold text-soft">{s.client.trim()}</div>
      <h1 class="text-2xl font-extrabold">{t('scan.title')}</h1>
      <p class="text-mut">{t('scan.sub')}</p>
    </div>
    <div class="flex items-start gap-7">
      <div class="relative grid h-[300px] w-[230px] flex-none place-items-center overflow-hidden rounded-[20px] bg-[linear-gradient(160deg,var(--color-accent-soft),var(--color-surface))] shadow-[var(--shadow-card),0_0_40px_-12px_var(--glow-accent)]">
        {#if s.device}
          <img class="max-h-[250px] drop-shadow-[0_8px_10px_rgba(17,24,39,.25)]" src={s.device.image} alt={s.device.name} />
        {:else}
          <span class="h-[160px] w-[80px] rounded-[14px] bg-[#1f2937]" aria-hidden="true"></span>
        {/if}
        <div class="scanline"></div>
      </div>
      <div class="w-[360px]">
        <ConnectChecklist label={t('scan.steps')}
          items={SCAN_STEPS.map((k, i) => ({ label: t(`scan.stage.${k}`), status: checks[i] }))} />
      </div>
    </div>
  </main>
  <SidePanel label={t('phone.subject')}>
    <DeviceCard compact name={name} serial={s.serial ?? ''} image={s.device?.image ?? null}
      {details} connected>
      {#if s.serial}<MirrorControls serial={s.serial} {name} />{/if}
    </DeviceCard>
  </SidePanel>
</div>
