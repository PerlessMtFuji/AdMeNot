<script lang="ts">
  import type { Snippet } from 'svelte';

  let { width = 304, label, children }: { width?: number; label: string; children: Snippet } = $props();
</script>

<aside aria-label={label} style="width: {width}px"
  class="scroll-fade flex flex-none flex-col gap-3.5 overflow-auto border-l border-line bg-surface/90 p-5 backdrop-blur-xl">
  {@render children()}
</aside>
