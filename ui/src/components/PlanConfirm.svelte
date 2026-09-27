<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { LEVEL_TONE } from '../lib/logic';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const expert = $derived(s.settings.mode === 'expert');
</script>

{#if s.plan}
  {@const plan = s.plan}
  <section aria-label={t('plan.title')} class="flex min-h-0 flex-1 flex-col gap-3">
    <h2 class="text-lg font-bold">{t('plan.confirm_title')}</h2>
    <div class="scroll-fade -mr-2 flex min-h-0 flex-col gap-2.5 overflow-auto pr-2">
      {#each plan.apps as a (a.package)}
        <div class="well flex-none p-3.5 {a.blocked ? 'opacity-60' : ''}">
          <div class="flex items-center gap-2">
            <b class="min-w-0 flex-1 truncate">{a.name}</b>
            <Pill tone={a.blocked ? 'neutral' : LEVEL_TONE[a.level]}>{a.blocked ? t('plan.blocked') : t(`choice.${a.level}`)}</Pill>
          </div>
          {#if a.blocked}
            <p class="mt-1 text-sm text-bad">{a.reason_text}</p>
            {#if a.reason === 'protected' && expert}
              <Button variant="ghost" size="sm" class="mt-1" onclick={() => ctl.unlock(a.package)}>
                <Icon name="lock-open" />{t('plan.unlock')}
              </Button>
            {/if}
          {:else}
            <ul class="mt-1.5 flex flex-col gap-0.5 text-sm text-mut">
              {#each a.steps as step, i (i)}
                <li class="flex gap-2"><span class="mt-[7px] h-1 w-1 flex-none rounded-full bg-soft"></span>{step}</li>
              {/each}
            </ul>
            {#each a.warnings as w (w)}
              <p class="mt-1.5 rounded-lg bg-warn-soft px-2 py-1 text-sm text-warn">{w}</p>
            {/each}
          {/if}
        </div>
      {/each}
    </div>
    {#if plan.runnable === 0}<p class="text-bad">{t('plan.nothing')}</p>{/if}
    <div class="mt-auto text-xs text-mut">{t('plan.undo_hint')}</div>
    <div class="flex gap-2">
      <Button variant="ghost" onclick={() => ctl.closePlan()}>{t('common.back')}</Button>
      <Button variant="primary" size="lg" class="flex-1" disabled={plan.runnable === 0 || s.orderRunning}
        onclick={() => ctl.execute()}>{t('plan.run', { count: plan.runnable })}</Button>
    </div>
  </section>
{/if}
