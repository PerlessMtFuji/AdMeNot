<script lang="ts">
  import type { Snippet } from 'svelte';

  type Props = { stripe?: 'bad' | 'warn' | 'neutral' | null; dim?: boolean; class?: string; role?: string;
    label?: string; children: Snippet };
  let { stripe = null, dim = false, class: cls = '', role, label, children }: Props = $props();
  const STRIPE = { bad: 'bg-bad text-bad glow-dot', warn: 'bg-warn-strong text-warn-strong glow-dot', neutral: 'bg-soft' };
</script>

<div {role} aria-label={label}
  class="relative flex-none overflow-hidden rounded-2xl card transition-opacity duration-300 {dim ? 'opacity-50' : ''} {cls}">
  {#if stripe}<span class="absolute inset-y-3 left-0 w-1 rounded-r-full {STRIPE[stripe]}" aria-hidden="true"></span>{/if}
  {@render children()}
</div>
