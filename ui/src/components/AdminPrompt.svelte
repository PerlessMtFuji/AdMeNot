<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';

  const s = getContext<Controller>('ctl').state;
  let now = $state(Date.now());
  $effect(() => {
    const id = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(id);
  });
  const left = $derived(s.admin
    ? Math.max(0, Math.round(s.admin.timeout - (now - s.admin.since) / 1000)) : 0);
  const time = $derived(`${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`);
</script>

{#if s.admin}
  <div class="card hard border-[#1d4ed8] bg-[#eff6ff] shadow-[4px_4px_0_#1d4ed8]" role="status">
    <div class="flex items-start gap-2.5">
      <span class="text-[22px]" aria-hidden="true">👆</span>
      <div>
        <b class="text-[13px]">{t('admin.title')}</b>
        <p class="mt-0.5">{t('admin.text', { name: s.admin.name })}</p>
        <p class="mono mt-1 text-[11px] text-mut">{t('admin.left', { time })}</p>
      </div>
    </div>
  </div>
{/if}
