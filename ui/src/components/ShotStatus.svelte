<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';

  // Potwierdzenie ostatniego zrzutu tego telefonu: miniatura i liczba zrzutów do protokołu.
  let { serial }: { serial: string } = $props();
  const s = getContext<Controller>('ctl').state;
</script>

{#if s.lastShot && s.lastShotSerial === serial}
  <div class="flex items-center gap-2 text-xs text-mut" role="status">
    {#if s.lastShot.image}<img src={s.lastShot.image} alt="" class="h-10 w-auto rounded-md border border-line" />{/if}
    <span>{tp('shot.count', s.shotCount)}{s.lastShot.black ? ` · ${t('shot.black')}` : ''}</span>
  </div>
{/if}
