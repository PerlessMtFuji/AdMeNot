<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { type StageState, stageStates } from '../lib/logic';
  import Icon from './Icon.svelte';
  import logo from '../assets/admenot.svg';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const STAGES = ['connect', 'read', 'analyze', 'fix', 'report'] as const;
  const states = $derived(stageStates(s.phase, s.scanStage, !!(s.result && s.reports[s.result.order])));
  const expert = $derived(s.settings.mode === 'expert');
  const ITEM: Record<StageState, string> = {
    now: 'rail-now font-bold text-accent', done: 'text-ink', todo: 'text-soft',
  };
  const DOT: Record<StageState, string> = {
    now: 'bg-accent text-white shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-accent)_18%,transparent),0_0_14px_var(--glow-accent)]', done: 'bg-ok-soft text-ok', todo: 'bg-neutral-soft text-soft',
  };
  const NAV = 'flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm font-semibold text-mut transition duration-150 hover:bg-neutral-soft hover:text-ink max-[1200px]:justify-center max-[1200px]:px-0';
  const CURRENT = 'rail-now !text-accent';
</script>

<nav aria-label={t('rail.label')} class="flex w-[200px] max-[1200px]:w-[68px] flex-none flex-col gap-1 border-r border-line bg-surface/90 px-3.5 max-[1200px]:px-2 py-5 backdrop-blur-xl">
  <div class="mb-5 flex items-center gap-2.5 px-1.5 text-lg font-extrabold tracking-[-.01em] max-[1200px]:justify-center max-[1200px]:px-0">
    <img src={logo} alt="" aria-hidden="true" width="28" height="28"
      class="h-7 w-7 drop-shadow-[0_4px_10px_var(--glow-accent)]" />
    <span class="max-[1200px]:sr-only">AdMeNot</span>
  </div>
  {#if s.screen === 'main'}
    <ol aria-label={t('stage.label')} class="flex flex-col gap-0.5">
      {#each STAGES as stage, i (stage)}
        <li aria-current={states[i] === 'now' ? 'step' : undefined} title={t(`stage.${stage}`)}
          class="flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm transition-colors duration-300 max-[1200px]:justify-center max-[1200px]:px-0 {ITEM[states[i]]}">
          <span class="grid h-[22px] w-[22px] place-items-center rounded-full text-2xs font-bold transition duration-300 {DOT[states[i]]}">
            {#if states[i] === 'done'}<Icon name="check" size={13} strokeWidth={3} />{:else}{i + 1}{/if}
          </span>
          <span class="max-[1200px]:sr-only">{t(`stage.${stage}`)}</span>
        </li>
      {/each}
    </ol>
  {:else}
    {@const backLabel = s.phase === 'connect' ? t('rail.new_order') : t('rail.back_to_order')}
    <button class={NAV} title={backLabel} onclick={() => ctl.back()}>
      <Icon name="plus" /><span class="max-[1200px]:sr-only">{backLabel}</span>
    </button>
  {/if}
  <div class="mt-auto flex flex-col gap-0.5">
    <button class="{NAV} mb-1.5 bg-accent-soft/60 !text-accent hover:!bg-accent-soft" title={t('donate.support')} onclick={() => ctl.openDonate()}>
      <Icon name="heart" /><span class="max-[1200px]:sr-only">{t('donate.support')}</span>
    </button>
    {#if expert && s.screen === 'main' && s.scan}
      <button class="{NAV} {s.consoleOpen ? CURRENT : ''}" aria-pressed={s.consoleOpen} title={t('actions.console')}
        onclick={() => (s.consoleOpen = !s.consoleOpen)}><Icon name="terminal" /><span class="max-[1200px]:sr-only">{t('actions.console')}</span></button>
    {/if}
    <button class="{NAV} {s.screen === 'history' ? CURRENT : ''}"
      aria-current={s.screen === 'history' ? 'page' : undefined} title={t('header.history')}
      onclick={() => (s.screen === 'history' ? ctl.back() : ctl.openHistory())}>
      <Icon name="history" /><span class="max-[1200px]:sr-only">{t('header.history')}</span>
    </button>
    <button class="{NAV} {s.screen === 'settings' ? CURRENT : ''}"
      aria-current={s.screen === 'settings' ? 'page' : undefined} title={t('header.settings')}
      onclick={() => (s.screen === 'settings' ? ctl.back() : ctl.openSettings())}>
      <Icon name="settings" /><span class="max-[1200px]:sr-only">{t('header.settings')}</span>
    </button>
  </div>
</nav>
