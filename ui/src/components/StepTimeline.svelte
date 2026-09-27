<script lang="ts">
  import type { StepEvent } from '../lib/types';
  import Icon from '../ui/Icon.svelte';

  let { steps }: { steps: StepEvent[] } = $props();
  const TEXT = { running: 'font-semibold text-ink', done: 'text-ink', undone: 'text-ink', failed: 'text-ink', skipped: 'text-soft' };
</script>

<ul class="flex flex-col gap-1 pr-5 pb-4 pl-[68px]">
  {#each steps as st (st.action_id)}
    <li data-status={st.status} class="flex items-start gap-2 py-0.5 {TEXT[st.status]}">
      {#if st.status === 'running'}
        <span class="spin mt-0.5 !h-[18px] !w-[18px] flex-none"></span>
      {:else if st.status === 'done' || st.status === 'undone'}
        <span class="mt-0.5 grid h-[18px] w-[18px] flex-none place-items-center rounded-full bg-ok text-white [animation:pop-in_.35s]">
          <Icon name={st.status === 'done' ? 'check' : 'rotate-ccw'} size={11} strokeWidth={3} />
        </span>
      {:else if st.status === 'failed'}
        <span class="mt-0.5 grid h-[18px] w-[18px] flex-none place-items-center rounded-full bg-bad text-white"><Icon name="x" size={11} strokeWidth={3} /></span>
      {:else}
        <span class="mt-0.5 grid h-[18px] w-[18px] flex-none place-items-center">—</span>
      {/if}
      <span class="min-w-0">{st.label}{#if st.error}<span class="block text-xs font-normal text-bad">{st.error}</span>{/if}</span>
    </li>
  {/each}
</ul>
