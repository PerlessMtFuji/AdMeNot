<script lang="ts">
  import { getContext } from 'svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { levelTag } from '../lib/logic';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const expert = $derived(s.settings.mode === 'expert');
</script>

{#if s.plan}
  <div class="modal-backdrop">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="plan-title">
      <b id="plan-title" class="text-[14px]">{t('plan.title')}</b>
      <div class="mt-3 flex flex-col gap-2">
        {#each s.plan.apps as a (a.package)}
          <div class="card {a.blocked ? 'opacity-80' : ''}">
            <div class="flex items-center gap-2">
              <b>{a.name}</b>
              <span class="mono text-[11px] text-mut">{a.package}</span>
              <span class="tag ml-auto {levelTag(a.level)}">{a.level_label}</span>
            </div>
            {#if a.blocked}
              <p class="bad mt-1">✗ {a.reason_text}</p>
              {#if a.reason === 'protected' && expert}
                <button class="btn-link mt-1" onclick={() => ctl.unlock(a.package)}>{t('plan.unlock')}</button>
              {/if}
            {:else}
              <ul class="mt-1.5 list-disc pl-5 leading-relaxed">
                {#each a.steps as step, i (i)}<li>{step}</li>{/each}
              </ul>
              {#each a.warnings as w (w)}<p class="warn mt-1">⚠ {w}</p>{/each}
            {/if}
          </div>
        {/each}
      </div>
      {#if s.plan.runnable === 0}<p class="bad mt-2">{t('plan.nothing')}</p>{/if}
      <div class="mt-4 flex items-center gap-2">
        <span class="text-[11px] text-mut">{t('plan.undo_hint')}</span>
        <button class="btn ml-auto" onclick={() => ctl.closePlan()}>{t('common.back')}</button>
        <button class="btn btn-pri" disabled={s.plan.runnable === 0 || s.orderRunning}
          onclick={() => ctl.execute()}>{t('plan.run', { count: s.plan.runnable })}</button>
      </div>
    </div>
  </div>
{/if}
