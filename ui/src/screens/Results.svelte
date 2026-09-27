<script lang="ts">
  import { getContext } from 'svelte';
  import AppRow from '../components/AppRow.svelte';
  import ExpertTable from '../components/ExpertTable.svelte';
  import InterruptedBanner from '../components/InterruptedBanner.svelte';
  import PhoneCard from '../components/PhoneCard.svelte';
  import PlanPreview from '../components/PlanPreview.svelte';
  import SummaryBanner from '../components/SummaryBanner.svelte';
  import type { Controller } from '../lib/controller';
  import { t } from '../lib/i18n/index.svelte';
  import { flaggedApps } from '../lib/logic';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const expert = $derived(s.settings.mode === 'expert');
  const flagged = $derived(s.scan ? flaggedApps(s.scan.apps) : []);
  const count = $derived(Object.keys(s.selection).length);
  const apkText = $derived(s.apk.running
    ? t('summary.apk_running', { done: s.apk.done, total: s.apk.total })
    : t('summary.apk_done'));
</script>

<div class="min-w-0 flex-1 overflow-auto p-4">
<section class="flex min-h-0 gap-3.5">
  <PhoneCard />
  <div class="flex min-w-0 flex-1 flex-col gap-2.5">
    {#if s.interrupted.length}<InterruptedBanner orders={s.interrupted} />{/if}
    {#if !s.scan}
      <div class="card hard"><span class="spin"></span> {t(`scan.stage.${s.scanStage ?? 'identify'}`)}</div>
    {:else if expert}
      <ExpertTable />
    {:else}
      <SummaryBanner />
      {#each flagged as app (app.package)}<AppRow {app} />{/each}
    {/if}
  </div>
</section>

{#if s.scan}
  <div class="actionbar sticky bottom-0 -mx-4 -mb-4 mt-auto">
    {#if expert}
      <span class="mono text-[11px] text-mut">› {apkText}</span>
    {:else}
      <span class="text-mut">{t('summary.ok_count', { count: s.scan.counts.safe })}</span>
      {#if s.apk.running}<span class="text-[11px] text-mut"><span class="spin"></span> {apkText}</span>{/if}
    {/if}
    <span class="ml-auto flex gap-2">
      <button class="btn" onclick={() => ctl.newScan()}>{t('actions.rescan')}</button>
      {#if !expert}
        <button class="btn" onclick={() => ctl.setMode('expert')}>{t('actions.details')}</button>
      {/if}
      <button class="btn btn-pri" disabled={count === 0 || s.orderRunning} onclick={() => ctl.openPlan()}>{t('actions.fix', { count })}</button>
    </span>
  </div>
{/if}
</div>

<PlanPreview />
