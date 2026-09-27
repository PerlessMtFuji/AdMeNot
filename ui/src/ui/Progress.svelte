<script lang="ts">
  let { value, label }: { value: number; label: string } = $props();
  const pct = $derived(Math.round(Math.min(1, Math.max(0, value)) * 100));
</script>

<div role="progressbar" aria-label={label} aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct}
  class="h-1.5 overflow-hidden rounded-full bg-neutral-soft">
  <i class="progress-fill block h-full rounded-full" style="width: {pct}%"></i>
</div>
