<script lang="ts">
  import { getContext } from 'svelte';
  import AdminPrompt from '../components/AdminPrompt.svelte';
  import QuestionDialog from '../components/QuestionDialog.svelte';
  import StepList from '../components/StepList.svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { groupSteps, levelTag } from '../lib/logic';
  import type { OrderResult } from '../lib/types';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const groups = $derived(groupSteps(s.steps));
  const planned = $derived((s.execPlan?.apps ?? []).filter((a) => !a.blocked));
  const waiting = $derived(planned.filter((a) => !groups.some((g) => g.package === a.package)));
  const running = $derived(s.phase === 'executing');

  function outcome(app: OrderResult['apps'][number]): { text: string; cls: string } {
    switch (app.outcome) {
      case 'ok':
        return { text: `✓ ${t('result.ok')}`, cls: 'ok' };
      case 'still_active':
        return { text: `⚠ ${t('result.still_active', { kinds: app.kinds.join(', ') })}`, cls: 'warn' };
      case 'stopped':
        return { text: `⏸ ${t('result.stopped')}`, cls: 'warn' };
      default:
        return { text: `✗ ${t('result.failed')}: ${app.errors.join('; ')}`, cls: 'bad' };
    }
  }

  async function undoAll(order: string) {
    await ctl.openHistory(s.device?.serial ?? null);
    await ctl.undo(order);
  }
</script>

<div class="min-w-0 flex-1 overflow-auto p-4">
<section class="flex flex-col gap-2">
  <b class="text-[14px]">{t('exec.title', { order: s.order ?? '' })}</b>
  <AdminPrompt />
  {#each groups as g (g.package)}
    {@const plan = planned.find((a) => a.package === g.package)}
    {@const res = s.result?.apps.find((a) => a.package === g.package)}
    <div class="card">
      <div class="flex items-center gap-2">
        <b>{g.name}</b>
        {#if plan}<span class="tag ml-auto {levelTag(plan.level)}">{plan.level_label}</span>{/if}
      </div>
      <StepList steps={g.steps} />
      {#if res}
        {@const o = outcome(res)}
        <p class="mt-1.5 font-semibold {o.cls}">{o.text}</p>
      {/if}
    </div>
  {/each}
  <!-- aplikacje bez kroków: np. po „Wstrzymaj” te, do których wykonanie nie doszło -->
  {#each s.result?.apps.filter((a) => !groups.some((g) => g.package === a.package)) ?? [] as res (res.package)}
    {@const o = outcome(res)}
    {@const plan = planned.find((a) => a.package === res.package)}
    <div class="card">
      <div class="flex items-center gap-2">
        <b>{res.name}</b>
        {#if plan}<span class="tag ml-auto {levelTag(plan.level)}">{plan.level_label}</span>{/if}
      </div>
      <p class="mt-1.5 font-semibold {o.cls}">{o.text}</p>
    </div>
  {/each}
  {#if running}
    {#each waiting as a (a.package)}
      <div class="card opacity-80">
        <div class="flex items-center gap-2"><b>{a.name}</b><span class="tag ml-auto {levelTag(a.level)}">{a.level_label}</span></div>
        <p class="mt-1 text-mut">○ {t('exec.waiting')}</p>
      </div>
    {/each}
  {/if}
  {#if s.verifying}<div class="card"><span class="spin"></span> {t('exec.verifying')}</div>{/if}
  {#if s.result}
    <div class="card hard">
      <b>{t('exec.done', { order: s.result.order, status: s.result.status_label })}</b>
      {#if s.result.stopped}<p class="warn mt-1">{t('exec.stopped')}</p>{/if}
    </div>
  {/if}
</section>

<div class="actionbar sticky bottom-0 -mx-4 -mb-4 mt-auto">
  <span class="text-[11px] text-mut">{t('plan.undo_hint')}</span>
  <span class="ml-auto flex gap-2">
    {#if running}
      <button class="btn" disabled={s.stopping || !s.job} onclick={() => ctl.stop()}>
        {s.stopping ? t('exec.stopping') : t('exec.stop')}
      </button>
    {:else if s.result}
      {@const order = s.result.order}
      {#if s.result.stopped}
        <button class="btn" disabled={s.orderRunning} onclick={() => ctl.resume(order)}>{t('exec.resume')}</button>
      {/if}
      <button class="btn" disabled={s.orderRunning} onclick={() => undoAll(order)}>{t('exec.undo_all')}</button>
      <button class="btn btn-pri" onclick={() => ctl.newScan()}>{t('exec.new_scan')}</button>
    {/if}
  </span>
</div>
</div>

<QuestionDialog />
