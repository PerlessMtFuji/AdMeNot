<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../lib/i18n/index.svelte';
  import { BULK_VERDICTS, VERDICT_TONE } from '../lib/logic';
  import type { AppView, Verdict } from '../lib/types';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import GroupBulk from './GroupBulk.svelte';

  // apps: aplikacje widoczne w grupie — z nich korzysta „zaznacz wszystkie” (tylko grupy z BULK_VERDICTS).
  type Props = { verdict: Verdict; count: number; open: boolean; collapsible: boolean; ontoggle?: () => void;
    apps?: AppView[]; children?: Snippet };
  let { verdict, count, open, collapsible, ontoggle, apps = [], children }: Props = $props();
  const label = $derived(t(`groups.${verdict}`));
  const bulk = $derived(open && apps.length > 0 && BULK_VERDICTS.includes(verdict));
</script>

<section id="group-{verdict}" aria-label={label} class="flex flex-col gap-2.5">
  <div class="flex items-center gap-2 text-xs font-bold tracking-wide text-soft uppercase">
    {#if collapsible}
      <button type="button" class="flex flex-1 items-center gap-2 text-left uppercase hover:text-ink" aria-expanded={open} onclick={ontoggle}>
        <Pill tone={VERDICT_TONE[verdict]}>{label}</Pill><span class="mono">{count}</span>
        <span class="ml-auto flex items-center gap-1 normal-case">{open ? t('groups.hide') : t('groups.show')}
          <Icon name="chevron-down" size={14} class="transition-transform duration-150 {open ? 'rotate-180' : ''}" /></span>
      </button>
      {#if bulk}<span class="mx-1 h-4 w-px bg-line" aria-hidden="true"></span><GroupBulk {verdict} {apps} />{/if}
    {:else}
      <Pill tone={VERDICT_TONE[verdict]}>{label}</Pill><span class="mono">{count}</span>
      {#if count === 0}<span class="font-semibold normal-case">— {t('groups.empty')}</span>{/if}
      {#if bulk}<div class="ml-auto"><GroupBulk {verdict} {apps} /></div>{/if}
    {/if}
  </div>
  {#if open && count > 0 && children}{@render children()}{/if}
</section>
