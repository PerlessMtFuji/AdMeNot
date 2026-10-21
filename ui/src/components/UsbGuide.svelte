<script lang="ts">
  import { untrack } from 'svelte';
  import { t } from '../lib/i18n/index.svelte';
  import { guidePath, guideTerms } from '../lib/logic';
  import { guessUsbGroup, USB_GROUPS, USB_STEPS, type UsbGroup } from '../lib/usb';
  import Button from '../ui/Button.svelte';

  let { model, collapsed = false }: { model: string | null; collapsed?: boolean } = $props();
  // `collapsed`/`model` liczą się tylko przy pierwszym renderze (patrz Connect.svelte).
  let open = $state(untrack(() => !collapsed));
  let group = $state<UsbGroup>(untrack(() => guessUsbGroup(model)));
  const steps = $derived(USB_STEPS[group].map((parts, i) => {
    const key = `usb.${group}.s${i + 1}`;
    return {
      act: guideTerms(t(`${key}.act`)),
      path: parts.includes('path') ? guidePath(t(`${key}.path`)) : [],
      note: parts.includes('note') ? t(`${key}.note`) : null,
      cond: parts.includes('cond') ? t(`${key}.cond`) : null,
      optional: parts.includes('optional'),
    };
  }));
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
    <ol>
      {#each steps as step, i (`${group}-${i}`)}
        <li class="grid grid-cols-[28px_1fr] items-start gap-3.5 border-t border-line px-1.5 py-3 first:border-t-0">
          <span class="grid size-7 place-items-center rounded-full bg-neutral-soft text-sm font-extrabold text-neutral" aria-hidden="true">{i + 1}</span>
          <div class="grid gap-1.5">
            <p class="text-md font-bold">
              {#each step.act as part, j (j)}{#if part.term}<span class="term term-end">{part.text}</span>{:else}{part.text}{/if}{/each}
              {#if step.cond}<span class="ml-2 inline-block rounded-full border border-warn-strong/40 bg-warn-soft px-2 align-[2px] text-xs font-bold text-warn">{step.cond}</span>{/if}
              {#if step.optional}<span class="ml-2 inline-block rounded-full border border-dashed border-soft px-2 align-[2px] text-xs font-semibold text-mut">{t('connect.guide_optional')}</span>{/if}
            </p>
            {#if step.path.length}
              <p class="flex flex-wrap items-center gap-1.5 text-sm text-neutral">
                {#each step.path as seg, j (j)}
                  {#if j}<span class="text-soft">›</span>{/if}
                  <span class="term {j === step.path.length - 1 ? 'term-end' : ''}">{seg}</span>
                {/each}
              </p>
            {/if}
            {#if step.note}<p class="text-sm text-mut">{step.note}</p>{/if}
          </div>
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
  /* Nazwa z ekranu telefonu: poziom menu albo przycisk do stuknięcia. */
  .term { border-radius: 7px; padding: 1px 8px; background: var(--color-neutral-soft); }
  .term-end { background: var(--color-accent-soft); color: var(--color-accent); font-weight: 700; }
</style>
