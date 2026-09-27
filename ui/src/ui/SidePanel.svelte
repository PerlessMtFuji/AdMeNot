<script lang="ts">
  import type { Snippet } from 'svelte';

  let { width = 290, label, children }: { width?: number; label: string; children: Snippet } = $props();
</script>

<aside aria-label={label} style="width: {width}px"
  class="flex flex-none flex-col gap-3 overflow-auto border-l border-line bg-surface p-4">
  {@render children()}
</aside>
