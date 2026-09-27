<script lang="ts">
  import { CATEGORY_ICON, categoryKey } from '../lib/categories';
  import { t } from '../lib/i18n/index.svelte';
  import type { Symptom } from '../lib/types';
  import Icon from '../ui/Icon.svelte';

  let { symptoms }: { symptoms: Symptom[] } = $props();
  const COLOR = { bad: 'text-bad', warn: 'text-warn', neutral: 'text-neutral' };
</script>

<ul class="mr-5 mb-4 ml-[92px] flex flex-col gap-2 rounded-xl bg-surface-2/70 px-4 py-3 shadow-[var(--shadow-well)]">
  {#each symptoms as sy (sy.category)}
    <li class="grid grid-cols-[18px_170px_1fr] items-start gap-2.5">
      <span class="mt-px {COLOR[sy.severity]}"><Icon name={CATEGORY_ICON[sy.category]} size={17} /></span>
      <b class={COLOR[sy.severity]}>{t(categoryKey(sy.category))}</b>
      <span class="text-mut">{sy.text}</span>
    </li>
  {/each}
</ul>
