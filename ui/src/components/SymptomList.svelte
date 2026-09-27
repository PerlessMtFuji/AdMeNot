<script lang="ts">
  import { CATEGORY_ICON, categoryKey } from '../lib/categories';
  import { t } from '../lib/i18n/index.svelte';
  import type { Symptom } from '../lib/types';
  import Icon from '../ui/Icon.svelte';

  let { symptoms }: { symptoms: Symptom[] } = $props();
  const COLOR = { bad: 'text-bad', warn: 'text-warn', neutral: 'text-neutral' };
</script>

<ul class="flex flex-col gap-1.5 pr-4 pb-3.5 pl-[76px]">
  {#each symptoms as sy (sy.category)}
    <li class="grid grid-cols-[16px_150px_1fr] items-start gap-2">
      <span class="mt-px {COLOR[sy.severity]}"><Icon name={CATEGORY_ICON[sy.category]} size={15} /></span>
      <b class={COLOR[sy.severity]}>{t(categoryKey(sy.category))}</b>
      <span class="text-mut">{sy.text}</span>
    </li>
  {/each}
</ul>
