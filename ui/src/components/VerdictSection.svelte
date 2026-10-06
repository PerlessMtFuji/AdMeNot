<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../lib/i18n/index.svelte';
  import { VERDICT_TONE } from '../lib/logic';
  import type { Verdict } from '../lib/types';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';

  type Props = { verdict: Verdict; count: number; open: boolean; collapsible: boolean; ontoggle?: () => void;
    children?: Snippet };
  let { verdict, count, open, collapsible, ontoggle, children }: Props = $props();
  const label = $derived(t(`groups.${verdict}`));
</script>

<section id="group-{verdict}" aria-label={label} class="flex flex-col gap-2.5">
  <div class="flex items-center gap-2 text-xs font-bold tracking-wide text-soft uppercase">
    {#if collapsible}
      <button type="button" class="flex flex-1 items-center gap-2 text-left uppercase hover:text-ink" aria-expanded={open} onclick={ontoggle}>
        <Pill tone={VERDICT_TONE[verdict]}>{label}</Pill><span class="mono">{count}</span>
        <span class="ml-auto flex items-center gap-1 normal-case">{open ? t('groups.hide') : t('groups.show')}
          <Icon name="chevron-down" size={14} class="transition-transform duration-150 {open ? 'rotate-180' : ''}" /></span>
      </button>
    {:else}
      <Pill tone={VERDICT_TONE[verdict]}>{label}</Pill><span class="mono">{count}</span>
      {#if count === 0}<span class="font-semibold normal-case">— {t('groups.empty')}</span>{/if}
    {/if}
  </div>
  {#if open && count > 0 && children}{@render children()}{/if}
</section>
