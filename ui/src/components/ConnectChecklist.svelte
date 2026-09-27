<script lang="ts">
  import type { CheckStatus } from '../lib/logic';
  import Icon from '../ui/Icon.svelte';

  let { items, label }: { items: { label: string; status: CheckStatus }[]; label: string } = $props();
</script>

<ul aria-label={label} class="flex flex-col gap-0.5 rounded-2xl bg-surface px-3 py-2 shadow-card">
  {#each items as item (item.label)}
    <li data-status={item.status}
      class="flex items-center gap-2.5 py-1.5 {item.status === 'todo' ? 'text-soft' : item.status === 'on' ? 'font-semibold text-ink' : 'text-ink'}">
      {#if item.status === 'done'}
        <span class="grid h-5 w-5 place-items-center rounded-full bg-ok text-white [animation:pop-in_.4s]"><Icon name="check" size={12} strokeWidth={3} /></span>
      {:else if item.status === 'on'}
        <span class="spin !h-5 !w-5"></span>
      {:else}
        <span class="h-5 w-5 rounded-full border-2 border-line"></span>
      {/if}
      {item.label}
    </li>
  {/each}
</ul>
