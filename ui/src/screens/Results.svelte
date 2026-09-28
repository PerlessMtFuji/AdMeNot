<script lang="ts">
  import { getContext } from 'svelte';
  import { flip } from 'svelte/animate';
  import { fade } from 'svelte/transition';
  import AppCard from '../components/AppCard.svelte';
  import EvidencePanel from '../components/EvidencePanel.svelte';
  import ExpertTable from '../components/ExpertTable.svelte';
  import WhoIsShowing from '../components/WhoIsShowing.svelte';
  import InterruptedBanner from '../components/InterruptedBanner.svelte';
  import PhoneThumb from '../components/PhoneThumb.svelte';
  import PlanConfirm from '../components/PlanConfirm.svelte';
  import PlanPanel from '../components/PlanPanel.svelte';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { flaggedApps, focusedApp, visibleApps } from '../lib/logic';
  import { DUR, enter, ms, stagger } from '../lib/motion';
  import type { Mode } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import CountUp from '../ui/CountUp.svelte';
  import Icon from '../ui/Icon.svelte';
  import Progress from '../ui/Progress.svelte';
  import Segmented from '../ui/Segmented.svelte';
  import SidePanel from '../ui/SidePanel.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const expert = $derived(s.settings.mode === 'expert');
  const apps = $derived(s.scan?.apps ?? []);
  const flagged = $derived(flaggedApps(apps));
  const safeApps = $derived(apps.filter((a) => a.verdict === 'safe'));
  let showSafe = $state(false);
  const rows = $derived(visibleApps(apps, { showAll: s.showAll, verdict: 'all', query: s.query }));
  const focused = $derived(focusedApp(rows.map((r) => r.package), s.focused));
  const focusedRow = $derived(rows.find((r) => r.package === focused) ?? null);
  const titleParts = $derived(tp('results.title', flagged.length, { count: '\u0000' }).split('\u0000'));
  const modes = $derived([{ value: 'simple' as Mode, label: t('header.simple') },
    { value: 'expert' as Mode, label: t('header.expert') }]);
</script>

<div class="flex min-h-0 min-w-0 flex-1">
  <main inert={s.plan !== null}
    class="flex min-w-0 flex-1 flex-col gap-4 scroll-fade overflow-auto px-7 py-7 transition-opacity duration-300 {s.plan ? 'opacity-50' : ''}">
    <header class="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-4 pb-1">
      {#if s.device}<div class="row-span-2"><PhoneThumb compact image={s.device.image} name={s.device.name} /></div>{/if}
      <div class="truncate text-sm font-semibold text-soft {s.device ? '' : 'col-span-2'}">
        {[s.client.trim(), s.device?.name].filter(Boolean).join(' · ')}
      </div>
      <div class="flex items-center gap-2">
        <Segmented label={t('results.mode')} value={s.settings.mode} options={modes} onchange={(m) => ctl.setMode(m)} />
        <Button onclick={() => ctl.newScan()}><Icon name="rotate-ccw" />{t('actions.rescan')}</Button>
      </div>
      {#if flagged.length > 0}
        <h1 class="col-span-2 text-2xl font-extrabold" aria-label={tp('results.title', flagged.length)}>
          {titleParts[0]}<CountUp value={flagged.length} />{titleParts[1]}
        </h1>
      {:else}
        <h1 class="col-span-2 text-2xl font-extrabold">{t('results.clean_title')}</h1>
      {/if}
    </header>

    {#if s.apk.running}
      <div class="flex items-center gap-3 text-sm text-mut">
        <span class="whitespace-nowrap">{t('summary.apk_running', { done: s.apk.done, total: s.apk.total })}</span>
        <div class="w-40"><Progress value={s.apk.total ? s.apk.done / s.apk.total : 0} label={t('scan.stage.apk')} /></div>
      </div>
    {/if}
    {#if s.interrupted.length}<InterruptedBanner orders={s.interrupted} />{/if}
    {#if s.scan?.low_behavior_data}<Banner tone="warn" icon="info" title={t('summary.low_data', { hours: s.scan.usage_window_h?.toFixed(1) ?? '?' })} />{/if}
    {#if s.scan?.profiles.others.length}<Banner tone="warn" icon="info" title={t('summary.profiles', { ids: s.scan.profiles.others.join(', ') })} />{/if}
    <WhoIsShowing ask={() => ctl.whoIsShowing()} />

    {#if expert}
      <ExpertTable {rows} {focused} />
    {:else if flagged.length === 0}
      <div class="grid place-items-center gap-2 py-10 text-center" in:enter>
        <span class="grid h-20 w-20 place-items-center rounded-full bg-ok text-white shadow-[0_0_0_12px_var(--color-ok-soft),0_0_40px_-4px_var(--color-ok)] [animation:pop-in_.6s]">
          <Icon name="check" size={38} strokeWidth={3} />
        </span>
        <p class="mt-3 text-mut">{t('results.clean_sub', { count: s.scan?.counts.total ?? 0 })}</p>
      </div>
    {:else}
      <div class="flex flex-col gap-3.5">
        {#each flagged as app, i (app.package)}
          <div animate:flip={{ duration: ms(DUR.flip) }} in:enter={{ delay: stagger(i) }}>
            <AppCard {app} level={s.selection[app.package] ?? null} flash={s.apk.changed.includes(app.package)}
              onlevel={(level) => ctl.setLevel(app.package, level)} ontoggle={() => ctl.toggle(app)} />
          </div>
        {/each}
      </div>
    {/if}
    {#if showSafe && !expert}
      <section class="rounded-2xl card p-4" in:enter>
        <span class="lbl">{t('results.safe_list')}</span>
        <ul aria-label={t('results.safe_list')} class="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5">
          {#each safeApps as a (a.package)}
            <li class="flex min-w-0 gap-2"><span class="truncate">{a.name}</span><span class="mono truncate text-2xs text-soft">{a.package}</span></li>
          {/each}
        </ul>
      </section>
    {/if}
  </main>
  <SidePanel width={expert ? 344 : undefined} label={expert && !s.plan ? t('evidence.title') : t('panel.plan')}>
    <div class="grid flex-1 grid-cols-1 grid-rows-1">
      {#if s.plan}
        <div class="col-start-1 row-start-1 flex min-h-0 flex-col gap-3"
          in:fade={{ duration: ms(DUR.panel) }} out:fade={{ duration: ms(DUR.panel) }}>
          <PlanConfirm />
        </div>
      {:else if expert}
        <div class="col-start-1 row-start-1 flex min-h-0 flex-col gap-3"
          in:fade={{ duration: ms(DUR.panel) }} out:fade={{ duration: ms(DUR.panel) }}>
          <EvidencePanel app={focusedRow} />
        </div>
      {:else}
        <div class="col-start-1 row-start-1 flex flex-col gap-3"
          in:fade={{ duration: ms(DUR.panel) }} out:fade={{ duration: ms(DUR.panel) }}>
          <PlanPanel {showSafe} ontoggleSafe={() => (showSafe = !showSafe)} />
        </div>
      {/if}
    </div>
  </SidePanel>
</div>
