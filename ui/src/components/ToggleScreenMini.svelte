<script lang="ts">
  import { t } from '../lib/i18n/index.svelte';

  // Miniatura ekranu powiadomień witryny na telefonie: `off` — naprawa wyłącza (czerwony),
  // `on` — cofanie włącza (zielony). Pulsujący przełącznik pokazuje, co stuknąć.
  type Props = { tone: 'off' | 'on'; label: string; compact?: boolean };
  let { tone, label, compact = false }: Props = $props();
  const row = $derived(tone === 'on' ? 'bg-[#f0fdf4]' : 'bg-[#fef2f2]');
  const knob = $derived(tone === 'on' ? 'bg-[#16a34a] [animation:tap-green_1.4s_infinite]' : 'bg-[#dc2626] [animation:tap-red_1.4s_infinite]');
</script>

<div class="relative flex-none rounded-[14px] bg-[linear-gradient(145deg,#374151,#111827)] p-1 {compact ? 'h-[106px] w-[56px]' : 'h-[132px] w-[70px]'}"
  aria-hidden="true">
  <div class="flex h-full flex-col gap-1 rounded-[11px] bg-white px-1.5 py-1.5 text-[6.5px] text-[#374151]">
    <b class="truncate text-[7px]">{t('user.phone_title')}</b>
    <i class="block h-1 w-4/5 rounded bg-[#e5e7eb]"></i>
    <div class="flex items-center justify-between gap-0.5 rounded-[3px] px-1 py-0.5 {row}">
      <span class="truncate">{label}</span><span class="h-1.5 w-3 flex-none rounded-full {knob}"></span>
    </div>
    <i class="block h-1 rounded bg-[#e5e7eb]"></i>
  </div>
</div>
