<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { enter } from '../lib/motion';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  let now = $state(Date.now());
  $effect(() => {
    const id = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(id);
  });
  const left = $derived(s.admin ? Math.max(0, Math.round(s.admin.timeout - (now - s.admin.since) / 1000)) : 0);
  const time = $derived(`${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`);
  const name = $derived(s.question?.name ?? s.admin?.name ?? '');
  const RING = 125.6;
</script>

{#if s.admin || s.question}
  <div role="status" in:enter class="flex items-center gap-5 rounded-[20px] bg-surface px-5 py-4 shadow-pop">
    <div class="relative h-[132px] w-[70px] flex-none rounded-[14px] bg-[linear-gradient(145deg,#374151,#111827)] p-1" aria-hidden="true">
      <div class="flex h-full flex-col gap-1 rounded-[11px] bg-white px-1.5 py-1.5 text-[6.5px] text-[#374151]">
        <b class="text-[7px]">{t('admin.phone_title')}</b>
        <i class="block h-1 w-4/5 rounded bg-[#e5e7eb]"></i>
        <div class="flex items-center justify-between rounded-[3px] bg-[#fef2f2] px-1 py-0.5"><span class="truncate">{name}</span><span class="h-1.5 w-3 rounded-full bg-[#dc2626]"></span></div>
        <i class="block h-1 rounded bg-[#e5e7eb]"></i>
        <div class="mt-auto rounded-[5px] bg-[#dc2626] py-0.5 text-center font-bold text-white [animation:tap-red_1.4s_infinite]">{t('admin.deactivate')}</div>
      </div>
    </div>
    <div class="min-w-0 flex-1">
      {#if s.question}
        <b class="text-lg">{t('question.admin.title')}</b>
        <p class="mt-1 text-mut">{t('question.admin.text', { name: s.question.name })}</p>
        <div class="mt-2.5 flex gap-2">
          <Button size="sm" onclick={() => ctl.answer('skip')}>{t('question.admin.skip')}</Button>
          <Button size="sm" variant="primary" onclick={() => ctl.answer('retry')}>{t('question.admin.retry')}</Button>
        </div>
      {:else if s.admin}
        <b class="text-lg">{t('admin.title')}</b>
        <p class="mt-1 text-mut">{t('admin.text', { name: s.admin.name })}</p>
        <p class="mono mt-1 text-xs text-soft">{t('admin.left', { time })}</p>
        {#if s.device && s.mirror.available && !ctl.mirrorActive(s.device.serial)}
          {@const device = s.device}
          <div class="mt-2"><Button size="sm" onclick={() => ctl.mirrorStart(device.serial, device.name)}>
            <Icon name="screen-share" />{t('mirror.show_phone')}</Button></div>
        {/if}
      {/if}
    </div>
    {#if s.admin && !s.question}
      <div class="relative h-12 w-12 flex-none" aria-hidden="true">
        <svg width="48" height="48" class="-rotate-90">
          <circle cx="24" cy="24" r="20" fill="none" stroke="var(--color-accent-soft)" stroke-width="4" />
          <circle cx="24" cy="24" r="20" fill="none" stroke="var(--color-accent)" stroke-width="4" stroke-linecap="round"
            stroke-dasharray={RING} stroke-dashoffset={RING * (1 - left / Math.max(1, s.admin.timeout))}
            style="transition: stroke-dashoffset 1s linear" />
        </svg>
        <span class="absolute inset-0 grid place-items-center text-sm font-extrabold tabular-nums">{left}</span>
      </div>
    {/if}
  </div>
{/if}
