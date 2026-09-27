<script lang="ts">
  import { untrack } from 'svelte';
  import { t } from '../lib/i18n/index.svelte';
  import { guideHighlight } from '../lib/logic';
  import { guessUsbGroup, USB_GROUPS, USB_STEPS, type UsbGroup } from '../lib/usb';
  import Button from '../ui/Button.svelte';

  let { model, collapsed = false }: { model: string | null; collapsed?: boolean } = $props();
  // `collapsed`/`model` liczą się tylko przy pierwszym renderze (patrz Connect.svelte).
  let open = $state(untrack(() => !collapsed));
  let group = $state<UsbGroup>(untrack(() => guessUsbGroup(model)));
  const steps = $derived(Array.from({ length: USB_STEPS[group] }, (_, i) => t(`usb.${group}.s${i + 1}`)));
</script>

{#if open}
  <section class="rounded-2xl card p-5">
    <div class="mb-2.5 flex items-center justify-between">
      <b class="text-md">{t('connect.guide_title')}</b>
      {#if collapsed}<Button variant="ghost" size="sm" onclick={() => (open = false)}>{t('connect.guide_hide')}</Button>{/if}
    </div>
    <div class="mb-3 flex flex-wrap gap-1" role="group" aria-label={t('connect.guide_maker')}>
      {#each USB_GROUPS as g (g)}
        <button type="button" aria-pressed={g === group} onclick={() => (group = g)}
          class="rounded-full px-3 py-1.5 text-sm font-semibold transition duration-150
            {g === group ? 'bg-ink text-surface shadow-[0_4px_12px_-4px_rgb(17_24_39/.5)]' : 'bg-neutral-soft text-neutral hover:text-ink'}">{t(`usb.group.${g}`)}</button>
      {/each}
    </div>
    <ol class="grid gap-2" style="grid-template-columns: repeat({steps.length}, minmax(0, 1fr))">
      {#each steps as text, i (text)}
        <li class="well p-3 text-sm">
          <div class="mb-2 flex h-[64px] flex-col gap-[3px] rounded-lg border border-line bg-surface p-1.5 text-[8.5px]" aria-hidden="true">
            <i class="block h-[5px] w-3/5 rounded bg-neutral-soft"></i>
            <i class="block truncate rounded bg-accent-soft px-1 font-bold text-accent not-italic">{guideHighlight(text)}</i>
            <i class="block h-[5px] rounded bg-neutral-soft"></i>
            <i class="block h-[5px] w-4/5 rounded bg-neutral-soft"></i>
          </div>
          <b>{i + 1}.</b> {text}
        </li>
      {/each}
    </ol>
  </section>
{:else}
  <button type="button" class="guide-show self-start text-sm font-semibold text-accent"
    onclick={() => (open = true)}>{t('connect.guide_show')}</button>
{/if}

<style>
  /* Strzałka jako ozdobnik CSS: nazwa dostępności przycisku zostaje dokładnie tekstem i18n. */
  .guide-show::after { content: ' \203A'; }
</style>
