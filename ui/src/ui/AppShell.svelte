<script lang="ts">
  import { getContext, type Snippet } from 'svelte';
  import Console from '../components/Console.svelte';
  import ErrorCard from '../components/ErrorCard.svelte';
  import type { Controller } from '../lib/controller';
  import StepRail from './StepRail.svelte';

  let { children }: { children: Snippet } = $props();
  const s = getContext<Controller>('ctl').state;
</script>

<div class="flex h-full">
  <StepRail />
  <div class="flex min-w-0 flex-1 flex-col">
    {#if s.error}<div class="px-6 pt-4"><ErrorCard /></div>{/if}
    <div class="flex min-h-0 min-w-0 flex-1">{@render children()}</div>
    {#if s.settings.mode === 'expert' && s.consoleOpen && s.screen === 'main'}<Console />{/if}
  </div>
</div>
