<script lang="ts">
  let { image = null, name, compact = false, scanning = false }:
    { image?: string | null; name: string; compact?: boolean; scanning?: boolean } = $props();
</script>

<div class="relative grid flex-none place-items-center overflow-hidden rounded-xl bg-[linear-gradient(160deg,var(--color-accent-soft),var(--color-surface-2))]
  {compact ? 'h-[60px] w-[36px]' : 'h-[96px] w-[58px]'}">
  {#if image}
    <img src={image} alt={name} class="max-h-full max-w-full object-contain" />
  {:else}
    <span class="rounded-[5px] bg-[#1f2937] {compact ? 'h-[40px] w-[20px]' : 'h-[64px] w-[32px]'}" aria-hidden="true"></span>
  {/if}
  {#if scanning}<div class="scanline"></div>{/if}
</div>
