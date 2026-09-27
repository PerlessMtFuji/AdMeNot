<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { guessUsbGroup, USB_GROUPS, USB_STEPS, type UsbGroup } from '../lib/usb';

  const s = getContext<Controller>('ctl').state;
  let group = $state<UsbGroup>(guessUsbGroup(s.devices[0]?.model ?? null));
  const steps = $derived(Array.from({ length: USB_STEPS[group] }, (_, i) => i + 1));
</script>

<div class="card">
  <div class="mb-1.5 flex flex-wrap items-center gap-2">
    <span class="lbl">{t('connect.guide_for')}</span>
    {#each USB_GROUPS as g (g)}
      <button class="tag {g === group ? 'tag-ok' : 'tag-gray'}" aria-pressed={g === group}
        onclick={() => (group = g)}>{t(`usb.group.${g}`)}</button>
    {/each}
  </div>
  <ol class="list-decimal pl-5 leading-relaxed">
    {#each steps as n (n)}
      <li>{t(`usb.${group}.s${n}`)}</li>
    {/each}
  </ol>
</div>
