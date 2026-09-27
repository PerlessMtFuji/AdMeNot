<script lang="ts">
  import { getContext } from 'svelte';
  import InterruptedBanner from '../components/InterruptedBanner.svelte';
  import UsbGuide from '../components/UsbGuide.svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const ready = $derived(s.devices.filter((d) => d.state === 'device'));
  const unauthorized = $derived(s.devices.some((d) => d.state === 'unauthorized'));
  const offline = $derived(s.devices.some((d) => d.state === 'offline'));
  const scanning = $derived(s.phase === 'scanning');
</script>

<section class="flex gap-4">
  <div class="relative grid h-[210px] w-[150px] flex-none place-items-center" aria-hidden="true">
    <svg width="150" height="210" viewBox="0 0 150 210">
      <rect x="45" y="20" width="60" height="110" rx="10" fill="var(--color-card)" stroke="var(--color-ink)" stroke-width="2.5" />
      <rect x="52" y="30" width="46" height="86" rx="4" fill="var(--color-paper)" />
      <path d="M75 130 C75 160, 75 160, 75 195" stroke="#2563eb" stroke-width="3" fill="none"
        stroke-dasharray="6 4" style="animation: dash 1s linear infinite" />
      <rect x="55" y="188" width="40" height="16" rx="3" fill="var(--color-ink)" />
    </svg>
    <span class="absolute top-[60px] left-[45px] h-[60px] w-[60px] rounded-full border-2 border-accent"
      style="animation: pulse-ring 1.8s infinite"></span>
  </div>

  <div class="flex flex-1 flex-col gap-2">
    {#if s.interrupted.length}
      <InterruptedBanner orders={s.interrupted} />
    {/if}
    {#if s.devicesError === 'adb_missing'}
      <div class="card hard" role="alert">
        <b>{t('connect.adb_missing')}</b>
        <button class="btn ml-2" onclick={() => ctl.openSettings()}>{t('connect.open_settings')}</button>
      </div>
    {:else if ready.length > 1}
      <div class="card hard">
        <b>{t('connect.many')}</b>
        {#each ready as d (d.serial)}
          <label class="mt-1.5 flex items-center gap-2">
            <input type="radio" name="device" checked={s.serial === d.serial}
              onchange={() => ctl.selectDevice(d.serial)} />
            <span>{d.model ?? '?'}</span>
            <span class="mono text-mut">{d.serial}</span>
          </label>
        {/each}
      </div>
    {:else if ready.length === 1}
      <div class="card hard">
        <b class="ok">✓ {t('connect.ready')}</b>
        <span>{ready[0].model ?? ''}</span>
        <span class="mono text-mut">{ready[0].serial}</span>
      </div>
    {:else}
      <div class="card hard">
        <b class="text-[14px]">{t('connect.waiting')}</b> <span class="spin"></span>
        <p class="mt-1">{t('connect.plug')}</p>
      </div>
      {#if unauthorized}
        <div class="card border-[var(--warn-line)] bg-[var(--warn-bg)]"><span class="warn">⚠</span> {t('connect.unauthorized')}</div>
      {/if}
      {#if offline}
        <div class="card border-[var(--warn-line)] bg-[var(--warn-bg)]"><span class="warn">⚠</span> {t('connect.offline')}</div>
      {/if}
      <UsbGuide />
    {/if}

    <div class="card flex flex-wrap items-end gap-3">
      <label class="flex flex-1 flex-col gap-1">
        <span class="lbl">{t('connect.client_label')}</span>
        <input class="rounded border border-line bg-card px-2 py-1.5" bind:value={s.client}
          placeholder={t('connect.client_placeholder')} maxlength="80" />
      </label>
      <button class="btn btn-pri" disabled={!s.serial || scanning} onclick={() => ctl.startScan()}>
        {#if scanning}<span class="spin"></span> {t('connect.scanning')}{:else}{t('connect.scan')}{/if}
      </button>
    </div>
  </div>
</section>
