<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import type { Lang, Mode } from '../lib/types';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const modes: Mode[] = ['simple', 'expert'];
</script>

<header class="topbar flex items-center gap-3 px-4 py-2.5">
  <b class="tracking-[.1em]">DEMALWARE</b>
  <span class="opacity-40">|</span>
  {#if s.order}
    <span>{t('app.order')} <b class="mono">{s.order}</b></span>
  {:else}
    <span>{t('app.new_order')}</span>
  {/if}
  {#if s.client.trim()}
    <span class="opacity-70">{t('app.client')}: <b>{s.client.trim()}</b></span>
  {/if}
  <nav class="ml-auto flex items-center gap-2">
    <div class="flex rounded-[7px] bg-[#2c3947] p-0.5" role="group" aria-label={t('settings.mode')}>
      {#each modes as mode (mode)}
        <button
          class="rounded-[5px] px-3 py-1 text-[11px] {s.settings.mode === mode
            ? 'bg-[#e6edf5] font-semibold text-[#1d2733]'
            : 'opacity-70'}"
          aria-pressed={s.settings.mode === mode}
          onclick={() => ctl.setMode(mode)}>{t(`header.${mode}`)}</button>
      {/each}
    </div>
    <select class="mono rounded bg-[#2c3947] px-1.5 py-1 text-[11px]" aria-label={t('header.lang')}
      value={s.settings.lang} onchange={(e) => ctl.setLang(e.currentTarget.value as Lang)}>
      <option value="pl">PL</option>
      <option value="en">EN</option>
    </select>
    <button class="px-2 text-[12px] {s.screen === 'history' ? 'underline' : 'opacity-80'}"
      onclick={() => (s.screen === 'history' ? ctl.back() : ctl.openHistory())}>{t('header.history')}</button>
    <button class="px-2 text-[12px] {s.screen === 'settings' ? 'underline' : 'opacity-80'}"
      onclick={() => (s.screen === 'settings' ? ctl.back() : ctl.openSettings())}>{t('header.settings')}</button>
  </nav>
</header>
