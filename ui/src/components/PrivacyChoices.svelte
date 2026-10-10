<script lang="ts">
  import { getContext, onMount, tick } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import type { TelemetrySample } from '../lib/types';

  let { telemetry, packages, onchange }: {
    telemetry: boolean; packages: boolean; onchange: (telemetry: boolean, packages: boolean) => void | Promise<void>;
  } = $props();
  const ctl = getContext<Controller>('ctl');
  let sample = $state<TelemetrySample | null>(null);
  const WHAT = ['common', 'start', 'scan', 'repair', 'undo', 'packages', 'never'];
  onMount(async () => { sample = await ctl.telemetrySample(); });

  // `checked` jest jednokierunkowe: gdy zapis się nie uda, właściwość się nie zmienia i pole
  // zostałoby kliknięte — po zapisie ustawiamy je na to, co naprawdę obowiązuje.
  async function change(input: HTMLInputElement, tel: boolean, pkg: boolean, shown: () => boolean): Promise<void> {
    await onchange(tel, pkg);
    await tick();
    input.checked = shown();
  }
</script>

<div class="flex flex-col gap-3">
  <label class="flex items-start gap-3">
    <input type="checkbox" checked={telemetry} onchange={(e) => change(e.currentTarget, e.currentTarget.checked, packages && e.currentTarget.checked, () => telemetry)} />
    <span><span class="font-semibold">{t('privacy.telemetry')}</span><br /><span class="text-xs text-mut">{t('privacy.telemetry_hint')}</span></span>
  </label>
  <label class="ml-7 flex items-start gap-3" class:opacity-50={!telemetry}>
    <input type="checkbox" checked={packages && telemetry} disabled={!telemetry}
      onchange={(e) => change(e.currentTarget, telemetry, e.currentTarget.checked, () => packages && telemetry)} />
    <span><span class="font-semibold">{t('privacy.packages')}</span><br /><span class="text-xs text-mut">{t('privacy.packages_hint')}</span></span>
  </label>
  <details class="text-sm">
    <summary class="cursor-pointer text-accent">{t('privacy.what_toggle')}</summary>
    <ul class="ml-4 mt-2 list-disc space-y-1">
      {#each WHAT as key (key)}<li>{t(`privacy.what.${key}`)}</li>{/each}
    </ul>
    {#if sample}
      <details class="mt-2">
        <summary class="cursor-pointer text-mut">{t('privacy.raw')}</summary>
        <pre class="mono mt-2 max-h-64 overflow-auto rounded-xl p-3 text-xs card">{JSON.stringify(packages && telemetry ? sample.packages : sample.basic, null, 2)}</pre>
      </details>
    {/if}
  </details>
  <button type="button" class="self-start text-sm text-accent underline" onclick={() => ctl.openPrivacy()}>{t('privacy.policy')}</button>
</div>
