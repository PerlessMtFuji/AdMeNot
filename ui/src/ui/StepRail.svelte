<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { type StageState, stageStates } from '../lib/logic';
  import Icon from './Icon.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const STAGES = ['connect', 'read', 'analyze', 'fix', 'report'] as const;
  const states = $derived(stageStates(s.phase, s.scanStage));
  const expert = $derived(s.settings.mode === 'expert');
  const ITEM: Record<StageState, string> = {
    now: 'bg-accent-soft font-bold text-accent', done: 'text-ink', todo: 'text-soft', off: 'text-soft',
  };
  const DOT: Record<StageState, string> = {
    now: 'bg-accent text-white', done: 'bg-ok-soft text-ok', todo: 'bg-neutral-soft text-soft',
    off: 'bg-neutral-soft text-soft',
  };
  const NAV = 'flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11.5px] text-ink transition duration-150 hover:bg-surface-2';
  const CURRENT = 'bg-accent-soft font-bold text-accent hover:bg-accent-soft';
</script>

<nav aria-label={t('rail.label')} class="flex w-[168px] flex-none flex-col gap-1 border-r border-line bg-surface px-3 py-4">
  <div class="mb-3 flex items-center gap-2 px-1 text-[13px] font-extrabold">
    <span class="h-[22px] w-[22px] rounded-[7px] bg-[linear-gradient(135deg,#6366f1,#3b82f6)]" aria-hidden="true"></span>
    DeMalware
  </div>
  {#if s.screen === 'main'}
    <ol aria-label={t('stage.label')} class="flex flex-col gap-0.5">
      {#each STAGES as stage, i (stage)}
        <li aria-current={states[i] === 'now' ? 'step' : undefined}
          title={stage === 'report' ? t('stage.soon') : undefined}
          class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-[11.5px] transition-colors duration-300 {ITEM[states[i]]}">
          <span class="grid h-[18px] w-[18px] place-items-center rounded-full text-[10px] transition-colors duration-300 {DOT[states[i]]}">
            {#if states[i] === 'done'}<Icon name="check" size={11} strokeWidth={3} />{:else}{i + 1}{/if}
          </span>
          {t(`stage.${stage}`)}
        </li>
      {/each}
    </ol>
  {:else}
    <button class={NAV} onclick={() => ctl.back()}>
      <Icon name="plus" />{s.phase === 'connect' ? t('rail.new_order') : t('rail.back_to_order')}
    </button>
  {/if}
  <div class="mt-auto flex flex-col gap-0.5">
    {#if expert && s.screen === 'main' && s.scan}
      <button class="{NAV} {s.consoleOpen ? CURRENT : ''}" aria-pressed={s.consoleOpen}
        onclick={() => (s.consoleOpen = !s.consoleOpen)}><Icon name="terminal" />{t('actions.console')}</button>
    {/if}
    <button class="{NAV} {s.screen === 'history' ? CURRENT : ''}"
      aria-current={s.screen === 'history' ? 'page' : undefined}
      onclick={() => (s.screen === 'history' ? ctl.back() : ctl.openHistory())}>
      <Icon name="history" />{t('header.history')}
    </button>
    <button class="{NAV} {s.screen === 'settings' ? CURRENT : ''}"
      aria-current={s.screen === 'settings' ? 'page' : undefined}
      onclick={() => (s.screen === 'settings' ? ctl.back() : ctl.openSettings())}>
      <Icon name="settings" />{t('header.settings')}
    </button>
  </div>
</nav>
