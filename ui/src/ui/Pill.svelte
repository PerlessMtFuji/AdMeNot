<script lang="ts">
  import type { Snippet } from 'svelte';

  let { tone, children }: { tone: 'bad' | 'warn' | 'neutral' | 'ok' | 'accent'; children: Snippet } = $props();
  const TONE = {
    bad: 'bg-bad-soft text-bad', warn: 'bg-warn-soft text-warn', neutral: 'bg-neutral-soft text-neutral',
    ok: 'bg-ok-soft text-ok', accent: 'bg-accent-soft text-accent',
  };
</script>

<span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold whitespace-nowrap ring-1 ring-current/15 ring-inset {TONE[tone]}">
  {@render children()}
</span>
