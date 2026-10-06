<script lang="ts">
  import { CATEGORY_ICON, categoryKey } from '../lib/categories';
  import { t } from '../lib/i18n/index.svelte';
  import type { AppView } from '../lib/types';
  import Icon from '../ui/Icon.svelte';
  import Tooltip from '../ui/Tooltip.svelte';

  let { app, side = 'top', focusable = true }: { app: AppView; side?: 'top' | 'bottom'; focusable?: boolean } = $props();
  const CHIP = { bad: 'bg-bad-soft text-bad', warn: 'bg-warn-soft text-warn', neutral: 'bg-neutral-soft text-neutral' };
</script>

{#if app.symptoms.length}
  <span class="inline-flex flex-wrap gap-1">
    {#each app.symptoms as sy (sy.category)}
      <Tooltip text={t(categoryKey(sy.category))} {side}>
        <!-- Kafelek jest fokusowalny, żeby podpowiedź pokazywała się też z klawiatury; w tabeli
             eksperta (własna nawigacja po wierszach) focusable={false}, a podpowiedź działa na hover. -->
        <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
        <span role="img" tabindex={focusable ? 0 : undefined} aria-label={t(categoryKey(sy.category))}
          class="grid h-6 w-6 place-items-center rounded-[7px] ring-1 ring-current/15 ring-inset outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)] {CHIP[sy.severity]}">
          <Icon name={CATEGORY_ICON[sy.category]} size={14} />
        </span>
      </Tooltip>
    {/each}
  </span>
{/if}
