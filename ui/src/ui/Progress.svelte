<script lang="ts">
  // `value` null: postęp nieznany (np. eksport trwający minuty bez liczników) — pasek „w ruchu”, bez procentów.
  let { value, label }: { value: number | null; label: string } = $props();
  const pct = $derived(value === null ? null : Math.round(Math.min(1, Math.max(0, value)) * 100));
</script>

<div role="progressbar" aria-label={label} aria-valuemin="0" aria-valuemax="100" aria-valuenow={pct ?? undefined}
  aria-busy={pct === null ? 'true' : undefined} data-indeterminate={pct === null ? '' : undefined}
  class="h-2 overflow-hidden rounded-full bg-neutral-soft shadow-[var(--shadow-well)]">
  {#if pct === null}
    <i class="progress-fill progress-indeterminate block h-full w-1/3 rounded-full"></i>
  {:else}
    <i class="progress-fill block h-full rounded-full" style="width: {pct}%"></i>
  {/if}
</div>

<style>
  .progress-indeterminate {
    animation: progress-slide 1.4s ease-in-out infinite;
  }
  @keyframes progress-slide {
    from { transform: translateX(-100%); }
    to { transform: translateX(300%); }
  }
  @media (prefers-reduced-motion: reduce) {
    .progress-indeterminate { animation: none; width: 100%; opacity: 0.5; }
  }
</style>
