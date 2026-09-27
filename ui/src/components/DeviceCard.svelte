<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../lib/i18n/index.svelte';

  type Props = { name: string; details: string; serial: string; image?: string | null; compact?: boolean;
    scanning?: boolean; connected?: boolean; children?: Snippet };
  let { name, details, serial, image = null, compact = false, scanning = false, connected = false, children }: Props = $props();
</script>

<div class="flex items-center gap-3.5 {compact ? '' : 'rounded-2xl bg-surface p-4 shadow-card'}">
  <div class="relative grid flex-none place-items-center overflow-hidden rounded-xl bg-[linear-gradient(160deg,var(--color-accent-soft),var(--color-surface-2))]
    {compact ? 'h-[60px] w-[36px]' : 'h-[96px] w-[58px]'}">
    {#if image}
      <img src={image} alt={name} class="max-h-full max-w-full object-contain" />
    {:else}
      <span class="rounded-[5px] bg-[#1f2937] {compact ? 'h-[40px] w-[20px]' : 'h-[64px] w-[32px]'}" aria-hidden="true"></span>
    {/if}
    {#if scanning}<div class="scanline"></div>{/if}
  </div>
  <div class="min-w-0 flex-1">
    <div class="truncate font-extrabold {compact ? 'text-[13px]' : 'text-[15px]'}">{name}</div>
    <div class="truncate text-mut {compact ? 'text-[11px]' : ''}">
      {details}{#if connected} · <span class="text-ok">● USB</span>{/if}
    </div>
    <div class="mono truncate text-[10.5px] text-soft" title={t('phone.serial')}>{serial}</div>
    {#if children}<div class="mt-2.5">{@render children()}</div>{/if}
  </div>
</div>
