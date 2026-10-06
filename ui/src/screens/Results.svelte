<script lang="ts">
  import { getContext } from 'svelte';
  import { flip } from 'svelte/animate';
  import { fade } from 'svelte/transition';
  import ApkSpace from '../components/ApkSpace.svelte';
  import AppCard from '../components/AppCard.svelte';
  import EvidencePanel from '../components/EvidencePanel.svelte';
  import ExpertTable from '../components/ExpertTable.svelte';
  import DiagnosticsPanel from '../components/DiagnosticsPanel.svelte';
  import InterruptedBanner from '../components/InterruptedBanner.svelte';
  import NoticeLine from '../components/NoticeLine.svelte';
  import PhoneThumb from '../components/PhoneThumb.svelte';
  import PlanConfirm from '../components/PlanConfirm.svelte';
  import PlanPanel from '../components/PlanPanel.svelte';
  import VerdictSection from '../components/VerdictSection.svelte';
  import StepTimeline from '../components/StepTimeline.svelte';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { facetCounts, flaggedApps, focusedApp, groupOpen, notices, verdictGroups, visibleApps } from '../lib/logic';
  import { DUR, enter, ms, stagger } from '../lib/motion';
  import type { Mode, Verdict } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import CountUp from '../ui/CountUp.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import Progress from '../ui/Progress.svelte';
  import Segmented from '../ui/Segmented.svelte';
  import SidePanel from '../ui/SidePanel.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  const expert = $derived(s.settings.mode === 'expert');
  const apps = $derived(s.scan?.apps ?? []);
  const flagged = $derived(flaggedApps(apps));
  const anyIncomplete = $derived(apps.some((a) => a.incomplete));
  // Brakujące dane (Plan 6: nigdy samo „bez uwag”): etykiety luk z aplikacji, a gdy żadna
  // aplikacja ich nie ma — nazwy kolektorów, które zawiodły albo zadziałały częściowo.
  const missing = $derived.by(() => {
    const labels = [...new Set(apps.flatMap((a) => a.gaps.map((g) => g.label)))];
    if (labels.length) return labels;
    const c = s.scan?.collectors;
    return [...new Set([...(c?.failed ?? []), ...(c?.partial ?? [])].map((x) => x.name))];
  });
  const withGaps = $derived(apps.filter((a) => a.gaps.length > 0).length);
  const noteItems = $derived(notices({ scan: s.scan, sdk: s.device?.sdk, selectLevel: s.settings.select_level,
    missing, withGaps }));
  // Błędy kolektorów (dawny tooltip kafelka) — tylko dla eksperta, pod pełnym komunikatem o niepełnej ocenie.
  const noteDetails = $derived(expert ? { incomplete: (s.scan?.collectors.failed ?? [])
    .map((c) => t('expert.collector_failed', { name: c.name, error: c.error ?? '' })) } : {});
  const undoName = $derived(s.undoTarget ? (apps.find((a) => a.package === s.undoTarget)?.name ?? s.undoTarget) : null);
  // Sekcje według werdyktu w trybie Prostym: groźne zawsze otwarte, „do sprawdzenia” i „bez uwag” zwinięte.
  const DANGER: Verdict[] = ['malicious', 'suspicious'];
  const simpleGroups = $derived(verdictGroups(apps));
  const isOpen = (v: Verdict, searching = false) => groupOpen(v, s.settings.mode, s.openGroups, searching);
  // Liczniki filtrów rodzaju i źródła liczone po przełączniku i wyszukiwarce, przed samymi filtrami.
  const base = $derived(visibleApps(apps, { showAll: s.showAll, verdict: 'all', query: s.query }));
  const facets = $derived(facetCounts(base));
  const rows = $derived(visibleApps(base, { showAll: true, verdict: 'all', query: '',
    categories: s.categoryFilter, source: s.sourceFilter }));
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
        <Button pressed={s.diagnostics} onclick={() => (s.diagnostics ? ctl.closeDiagnostics() : ctl.openDiagnostics())}>
          <Icon name="scan-search" />{t('header.find_source')}
          {#if s.incident.recording}<span data-recording class="h-2 w-2 rounded-full bg-bad" title={t('header.find_source_recording')}></span>{/if}
        </Button>
        <Segmented label={t('results.mode')} value={s.settings.mode} options={modes} onchange={(m) => ctl.setMode(m)} />
        <Button onclick={() => ctl.newScan()}><Icon name="rotate-ccw" />{t('actions.rescan')}</Button>
      </div>
      {#if flagged.length > 0}
        <h1 class="col-span-2 text-2xl font-extrabold" aria-label={tp('results.title', flagged.length)}>
          {titleParts[0]}<CountUp value={flagged.length} />{titleParts[1]}
        </h1>
      {:else}
        <h1 class="col-span-2 text-2xl font-extrabold">{t(anyIncomplete ? 'results.clean_title_incomplete' : 'results.clean_title')}</h1>
      {/if}
    </header>

    {#if s.apk.running}
      <div class="flex items-center gap-3 text-sm text-mut">
        <span class="whitespace-nowrap">{t('summary.apk_running', { done: s.apk.done, total: s.apk.total })}</span>
        <div class="w-40"><Progress value={s.apk.total ? s.apk.done / s.apk.total : 0} label={t('scan.stage.apk')} /></div>
      </div>
    {/if}
    <ApkSpace />
    {#if s.interrupted.length}<InterruptedBanner orders={s.interrupted} />{/if}
    {#if undoName && s.job?.kind === 'undo'}
      <Banner tone="info" icon="undo-2" title={t('summary.undoing_app', { name: undoName })}>
        {#if s.undoSteps.length}<StepTimeline steps={s.undoSteps} />{/if}
      </Banner>
    {:else if undoName && s.undoResult?.errors.length}
      <Banner tone="bad" icon="triangle-alert" title={t('summary.undo_app_failed', { name: undoName })}>
        <ul class="list-disc pl-5 text-sm">{#each s.undoResult.errors as e (e)}<li>{e}</li>{/each}</ul>
      </Banner>
    {/if}
    <NoticeLine items={noteItems} details={noteDetails} />

    {#if expert}
      <ExpertTable {rows} {focused} {facets} />
    {:else if flagged.length === 0}
      <div class="grid place-items-center gap-2 py-10 text-center" in:enter>
        {#if anyIncomplete}
          <span class="grid h-20 w-20 place-items-center rounded-full bg-warn-strong text-white shadow-[0_0_0_12px_var(--color-warn-soft),0_0_40px_-4px_var(--color-warn-strong)] [animation:pop-in_.6s]">
            <Icon name="info" size={38} strokeWidth={3} />
          </span>
        {:else}
          <span class="grid h-20 w-20 place-items-center rounded-full bg-ok text-white shadow-[0_0_0_12px_var(--color-ok-soft),0_0_40px_-4px_var(--color-ok)] [animation:pop-in_.6s]">
            <Icon name="check" size={38} strokeWidth={3} />
          </span>
        {/if}
        <p class="mt-3 text-mut">{t('results.clean_sub', { count: s.scan?.counts.total ?? 0 })}</p>
      </div>
    {:else}
      {#each simpleGroups.filter((g) => g.verdict !== 'safe') as g (g.verdict)}
        {#if g.apps.length || DANGER.includes(g.verdict)}
          <VerdictSection verdict={g.verdict} count={g.apps.length} open={isOpen(g.verdict)}
            collapsible={g.apps.length > 0 && !DANGER.includes(g.verdict)}
            ontoggle={() => ctl.setGroupOpen(g.verdict, !isOpen(g.verdict))}>
            {#each g.apps as app, i (app.package)}
              <div animate:flip={{ duration: ms(DUR.flip) }} in:enter={{ delay: stagger(i) }}>
                <AppCard {app} level={s.selection[app.package] ?? null} done={s.acted[app.package] ?? null} busy={s.orderRunning}
                  onundo={() => ctl.undoApp(app.package)} flash={s.apk.changed.includes(app.package)}
                  onlevel={(level) => ctl.setLevel(app.package, level)} ontoggle={() => ctl.toggle(app)} />
              </div>
            {/each}
          </VerdictSection>
        {/if}
      {/each}
    {/if}
    {#if !expert && simpleGroups[3].apps.length}
      <VerdictSection verdict="safe" count={simpleGroups[3].apps.length} open={isOpen('safe')} collapsible
        ontoggle={() => ctl.setGroupOpen('safe', !isOpen('safe'))}>
        {#each simpleGroups[3].apps as app (app.package)}
          <AppCard {app} level={s.selection[app.package] ?? null} done={s.acted[app.package] ?? null} busy={s.orderRunning}
            onundo={() => ctl.undoApp(app.package)} onlevel={(level) => ctl.setLevel(app.package, level)} ontoggle={() => ctl.toggle(app)} />
        {/each}
      </VerdictSection>
    {/if}
  </main>
  <SidePanel width={expert ? 344 : undefined} label={s.plan ? t('panel.plan') : s.diagnostics ? t('diag.title') : expert ? t('evidence.title') : t('panel.plan')}>
    <div class="grid flex-1 grid-cols-1 grid-rows-1">
      {#if s.plan}
        <div class="col-start-1 row-start-1 flex min-h-0 flex-col gap-3"
          in:fade={{ duration: ms(DUR.panel) }} out:fade={{ duration: ms(DUR.panel) }}>
          <PlanConfirm />
        </div>
      {:else if s.diagnostics}
        <div class="col-start-1 row-start-1 flex min-h-0 flex-col gap-3"
          in:fade={{ duration: ms(DUR.panel) }} out:fade={{ duration: ms(DUR.panel) }}>
          <DiagnosticsPanel ask={() => ctl.whoIsShowing()} />
        </div>
      {:else if expert}
        <div class="col-start-1 row-start-1 flex min-h-0 flex-col gap-3"
          in:fade={{ duration: ms(DUR.panel) }} out:fade={{ duration: ms(DUR.panel) }}>
          <EvidencePanel app={focusedRow} />
        </div>
      {:else}
        <div class="col-start-1 row-start-1 flex flex-col gap-3"
          in:fade={{ duration: ms(DUR.panel) }} out:fade={{ duration: ms(DUR.panel) }}>
          <PlanPanel />
        </div>
      {/if}
    </div>
  </SidePanel>
</div>
