<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../lib/i18n/index.svelte';
  import PhoneThumb from './PhoneThumb.svelte';

  type Props = { name: string; details: string; serial: string; image?: string | null; compact?: boolean;
    scanning?: boolean; connected?: boolean; children?: Snippet };
  let { name, details, serial, image = null, compact = false, scanning = false, connected = false, children }: Props = $props();
</script>

<div class="flex items-center gap-3.5 {compact ? '' : 'rounded-2xl card p-5'}">
  <PhoneThumb {image} {name} {compact} {scanning} />
  <div class="min-w-0 flex-1">
    <div class="truncate font-extrabold {compact ? 'text-md' : 'text-xl'}">{name}</div>
    <div class="truncate text-mut {compact ? 'text-sm' : ''}">
      {details}{#if connected}{' · '}<span class="text-ok">● USB</span>{/if}
    </div>
    <div class="mono truncate text-2xs text-soft" title={t('phone.serial')}>{serial}</div>
    {#if children}<div class="mt-2.5">{@render children()}</div>{/if}
  </div>
</div>
