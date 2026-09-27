<script lang="ts">
  import type { StepEvent, StepStatus } from '../lib/types';

  let props: { steps: StepEvent[] } = $props();
  const ICON: Record<StepStatus, string> = { running: '', done: '✓', failed: '✗', skipped: '–', undone: '↺' };
  const CLS: Record<StepStatus, string> = {
    running: 'warn', done: 'ok', failed: 'bad', skipped: 'text-mut', undone: 'ok',
  };
</script>

<ul class="mt-1.5 leading-[1.75]">
  {#each props.steps as st (st.action_id)}
    <li class={CLS[st.status]}>
      {#if st.status === 'running'}<span class="spin"></span>{:else}{ICON[st.status]}{/if}
      {st.label}{#if st.error}<span> — {st.error}</span>{/if}
    </li>
  {/each}
</ul>
