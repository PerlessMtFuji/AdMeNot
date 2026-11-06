<script lang="ts">
  import { cubicOut } from 'svelte/easing';
  import { fly } from 'svelte/transition';
  import { t } from '../../lib/i18n/index.svelte';
  import { DUR, ms } from '../../lib/motion';
  import type { CrumbView } from '../../lib/types';
  import Icon from '../../ui/Icon.svelte';

  type Props = { crumbs: CrumbView[]; ongo: (path: string) => void };
  let { crumbs, ongo }: Props = $props();
</script>

<!-- Okruszki ścieżki: każdy człon klikalny; pierwszy to pamięć telefonu (jego nazwa). -->
<nav aria-label={t('explorer.crumbs_label')} class="min-w-0 flex-1 overflow-x-auto">
  <ol class="flex min-w-0 items-center gap-0.5 text-md font-semibold">
    {#each crumbs as c, i (c.path)}
      {@const last = i === crumbs.length - 1}
      {#if i > 0}<li aria-hidden="true" class="flex-none text-soft"><Icon name="chevron-right" size={15} /></li>{/if}
      <li in:fly={{ x: 14, duration: ms(DUR.zoom), easing: cubicOut }} class="min-w-0 flex-none">
        <button type="button" title={c.label} aria-current={last ? 'location' : undefined} onclick={() => ongo(c.path)}
          class="flex max-w-full min-w-0 items-center gap-1.5 rounded-lg px-1.5 py-0.5 transition duration-150
            hover:bg-neutral-soft {last ? 'text-ink' : 'text-mut hover:text-ink'}">
          {#if i === 0}<Icon name="smartphone" size={15} class="text-accent" />{/if}
          <span class="truncate">{c.label}</span>
        </button>
      </li>
    {/each}
  </ol>
</nav>
