<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { initial } from '../lib/logic';
  import type { DeviceCheck } from '../lib/types';
  import AppIcon from './AppIcon.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';

  // Kto jest ekranem głównym. Aplikacja spoza systemu to „do sprawdzenia” niezależnie od punktów: adware
  // podmienia ekran główny i chowa ikonę, a werdykt bywa „bezpieczna” (zgłoszenie 2026-11-20).
  let { check }: { check: DeviceCheck } = $props();
  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const expert = $derived(s.settings.mode === 'expert');
  const ok = $derived(check.state === 'ok');
  const home = $derived(check.home ?? []);
  const iconOf = (pkg: string) => s.scan?.apps.find((a) => a.package === pkg)?.icon ?? null;
</script>

<div class="card rounded-2xl p-4">
  <div class="flex items-start gap-3">
    {#if ok}
      <span class="grid h-6 w-6 flex-none place-items-center rounded-full bg-ok-soft text-ok"><Icon name="check" size={14} strokeWidth={3} /></span>
    {:else}
      <span class="grid h-6 w-6 flex-none place-items-center rounded-full bg-warn-soft text-warn"><Icon name="house" size={14} /></span>
    {/if}
    <div class="flex min-w-0 flex-1 flex-col gap-0.5">
      <div class="flex flex-wrap items-center gap-2">
        <h2 class="font-bold">{t('checks.home_screen')}</h2>
        <Pill tone={ok ? 'ok' : 'warn'}>{check.state_label}</Pill>
      </div>
      <span class="text-sm text-mut">{t('checks.home_intro')}</span>
    </div>
  </div>

  <ul class="mt-3 flex flex-col border-t border-line">
    {#each home as h (h.package)}
      <li class="border-b border-line py-2.5 last:border-b-0">
        <div class="flex items-center gap-3">
          <AppIcon icon={iconOf(h.package)} class="h-7 w-7">
            <span class="grid h-7 w-7 flex-none place-items-center rounded-lg bg-accent-soft text-sm font-extrabold text-accent" aria-hidden="true">{initial(h.name)}</span>
          </AppIcon>
          <span class="flex min-w-0 flex-1 flex-col">
            <b class="truncate" title={expert ? h.package : undefined}>{h.name}</b>
            {#if expert}<span class="truncate text-xs text-soft">{h.package}</span>{/if}
          </span>
          {#if h.system}<Pill tone="ok">{t('checks.home_system')}</Pill>{:else}<Pill tone="warn">{t('checks.home_foreign')}</Pill>{/if}
        </div>
        {#if !h.system}<p class="mt-1.5 pl-10 text-sm text-soft">{t('checks.home_hint')}</p>{/if}
      </li>
    {/each}
  </ul>
</div>
