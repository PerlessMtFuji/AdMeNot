<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { modelName } from '../lib/logic';
  import type { DeviceEntry } from '../lib/types';
  import Pill from '../ui/Pill.svelte';
  import CopyImei from './CopyImei.svelte';
  import MirrorControls from './MirrorControls.svelte';
  import PhoneThumb from './PhoneThumb.svelte';

  // Kilka podłączonych telefonów: jedna lista wyboru (wiersze z IMEI i Androidem, bo stary i nowy telefon
  // klienta bywają tym samym modelem) i jeden zestaw podglądu/zrzutu dla wybranego.
  let { devices }: { devices: DeviceEntry[] } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const nameOf = (d: DeviceEntry) => d.name ?? modelName(d.model);
  const selected = $derived(devices.find((d) => d.serial === s.serial) ?? null);
  // Telefon jak na karcie urządzenia: IMEI, a numer seryjny adb tylko, gdy telefon nie podał IMEI.
  const idOf = (d: DeviceEntry) => (d.imei ? `IMEI ${d.imei}` : d.serial);
  const idTitle = (d: DeviceEntry) => (d.imei ? `${t('phone.serial')}: ${d.serial}` : t('phone.serial'));
  const mirrorOn = (d: DeviceEntry) => s.mirror.serial === d.serial && (s.mirror.state === 'starting' || s.mirror.state === 'running');
</script>

<div class="flex flex-col gap-3">
  <div role="radiogroup" aria-labelledby="device-list-label" class="overflow-hidden rounded-2xl card">
    <div id="device-list-label" class="lbl px-4 pt-3 pb-2">{tp('connect.devices', devices.length, { count: devices.length })}</div>
    {#each devices as d, i (d.serial)}
      {@const on = s.serial === d.serial}
      <label class="flex cursor-pointer items-center gap-3 px-4 py-2.5 transition-colors duration-150
        {i ? 'border-t border-line' : ''} {on ? 'bg-accent-soft shadow-[inset_3px_0_0_var(--color-accent)]' : 'hover:bg-neutral-soft'}">
        <input type="radio" name="device" class="h-4 w-4 flex-none accent-[var(--color-accent)]" checked={on}
          aria-label="{nameOf(d)} {idOf(d)}" onchange={() => ctl.selectDevice(d.serial)} />
        <PhoneThumb image={d.image ?? null} name={nameOf(d)} compact />
        <span class="min-w-0 flex-1">
          <span class="block truncate font-bold">{nameOf(d)}</span>
          {#if d.android}<span class="block truncate text-sm text-mut">Android {d.android}</span>{/if}
          <span class="flex min-w-0 items-center gap-1">
            <span class="mono truncate text-2xs text-soft" title={idTitle(d)}>{idOf(d)}</span>
            {#if d.imei}<CopyImei imei={d.imei} />{/if}
          </span>
        </span>
        {#if on}<Pill tone="accent">{t('connect.selected')}</Pill>
        {:else if mirrorOn(d)}<Pill tone="warn">{t('connect.mirror_on')}</Pill>{/if}
      </label>
    {/each}
  </div>
  {#if selected}
    <!-- Podgląd i zrzut raz, z nazwą telefonu, którego dotyczą; poza <label>, żeby klik nie zmieniał wyboru. -->
    <!-- IMEI (zapas: numer seryjny) w etykiecie: dwa telefony tego samego modelu inaczej by się nie różniły. -->
    <section aria-label={t('connect.tools_for', { name: nameOf(selected), id: idOf(selected) })}
      class="flex flex-wrap items-start gap-x-3 gap-y-1.5 pl-1">
      <span class="pt-1.5 text-sm font-semibold text-mut">{nameOf(selected)} <span class="mono text-2xs text-soft" title={idTitle(selected)}>{idOf(selected)}</span>:</span>
      {#key selected.serial}<MirrorControls serial={selected.serial} name={nameOf(selected)} />{/key}
    </section>
  {:else}
    <!-- nic nie wybrano (start albo wybrany telefon odłączony): narzędzia i „Skanuj” czekają na wybór -->
    <p class="pl-1 text-sm text-mut">{t('connect.pick_first')}</p>
  {/if}
</div>
