<script lang="ts">
  import { getContext } from 'svelte';
  import { flip } from 'svelte/animate';
  import { fade } from 'svelte/transition';
  import ApkModeChoice from '../components/ApkModeChoice.svelte';
  import ApkProgress from '../components/ApkProgress.svelte';
  import ApkSpace from '../components/ApkSpace.svelte';
  import AppCard from '../components/AppCard.svelte';
  import EvidencePanel from '../components/EvidencePanel.svelte';
  import ExpertTable from '../components/ExpertTable.svelte';
  import EmptyVerdicts from '../components/EmptyVerdicts.svelte';
  import DeviceChecks from '../components/DeviceChecks.svelte';
  import DiagnosticsPanel from '../components/DiagnosticsPanel.svelte';
  import InterruptedBanner from '../components/InterruptedBanner.svelte';
  import ManualList from '../components/ManualList.svelte';
  import NoticeLine from '../components/NoticeLine.svelte';
  import PhoneThumb from '../components/PhoneThumb.svelte';
  import PlanConfirm from '../components/PlanConfirm.svelte';
  import PlanPanel from '../components/PlanPanel.svelte';
  import RepairTabs from '../components/RepairTabs.svelte';
  import VerdictSection from '../components/VerdictSection.svelte';
  import StepTimeline from '../components/StepTimeline.svelte';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { emptyDangerVerdicts, facetCounts, flaggedApps, focusedApp, groupOpen, isManual, modeUndecided, notices, phoneBadge, shownChecks, splitNotices,
    verdictGroups, visibleApps } from '../lib/logic';
  import { DUR, enter, ms, stagger } from '../lib/motion';
  import type { Mode, Verdict } from '../lib/types';
  import Banner from '../ui/Banner.svelte';
  import Button from '../ui/Button.svelte';
  import CountUp from '../ui/CountUp.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import Segmented from '../ui/Segmented.svelte';
  import SidePanel from '../ui/SidePanel.svelte';
  import Tooltip from '../ui/Tooltip.svelte';

  const ctl = getContext<Controller>('ctl');
  const s = ctl.state;
  // Tryb ręczny (spec trybu ręcznego §3): werdykty heurystyk ukryte — bez grup, tabeli eksperta i przełącznika widoku.
  const manual = $derived(isManual(s.scan));
  const choosing = $derived(s.apkQuestion?.kind === 'mode');
  // Tryb jeszcze nie wybrany (szacunek, pytanie, „zawsze ręcznie” do `apk:manual`): stan „w toku” zamiast grup.
  const undecided = $derived(modeUndecided({ scan: s.scan, setting: s.settings.apk_mode_default, running: s.apk.running,
    fullChosen: s.apkFullChosen }));
  const verdictsHidden = $derived(manual || choosing || undecided);
  const expert = $derived(s.settings.mode === 'expert' && !verdictsHidden);
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
  // Zakładki kroku (spec układu Naprawy §4): uwagi o stanie telefonu idą do „Telefon”, reszta zostaje przy aplikacjach.
  const notes = $derived(splitNotices(noteItems));
  const phone = $derived(phoneBadge(s.scan?.device_checks));
  const checks = $derived(shownChecks(s.scan));
  // Błędy kolektorów (dawny tooltip kafelka) — tylko dla eksperta, pod pełnym komunikatem o niepełnej ocenie.
  const noteDetails = $derived(expert ? { incomplete: (s.scan?.collectors.failed ?? [])
    .map((c) => t('expert.collector_failed', { name: c.name, error: c.error ?? '' })) } : {});
  const undoName = $derived(s.undoTarget ? (apps.find((a) => a.package === s.undoTarget)?.name ?? s.undoTarget) : null);
  // Sekcje według werdyktu w trybie Prostym: groźne zawsze otwarte, „do sprawdzenia” i „bez uwag” zwinięte.
  const DANGER: Verdict[] = ['malicious', 'suspicious'];
  const simpleGroups = $derived(verdictGroups(apps));
  const isOpen = (v: Verdict, searching = false) => groupOpen(v, s.settings.mode, s.openGroups, searching);
  // Liczniki filtrów rodzaju i źródła liczone po wyszukiwarce, przed samymi filtrami.
  const searched = $derived(visibleApps(apps, { showAll: true, verdict: 'all', query: s.query }));
  const facets = $derived(facetCounts(searched));
  const rows = $derived(visibleApps(searched, { showAll: true, verdict: 'all', query: '',
    categories: s.categoryFilter, source: s.sourceFilter }));
  const searching = $derived(s.query.trim() !== '' || s.categoryFilter.length > 0 || s.sourceFilter !== null);
  const expertGroups = $derived(verdictGroups(rows));
  const navRows = $derived(expertGroups.filter((g) => isOpen(g.verdict, searching)).flatMap((g) => g.apps));
  const focused = $derived(focusedApp(navRows.map((r) => r.package), s.focused));
  const focusedRow = $derived(navRows.find((r) => r.package === focused) ?? null);
  const safeGroup = $derived(simpleGroups.find((g) => g.verdict === 'safe')!);
  const titleParts = $derived(tp('results.title', flagged.length, { count: '\u0000' }).split('\u0000'));
  const modes = $derived([{ value: 'simple' as Mode, label: t('header.simple') },
    { value: 'expert' as Mode, label: t('header.expert') }]);
  // Podgląd ekranu: stan dotyczy tylko bieżącego telefonu; „starting” blokuje przycisk, brak scrcpy też.
  const mirrorState = $derived(s.device && s.mirror.serial === s.device.serial ? s.mirror.state : 'stopped');
  const mirrorOn = $derived(mirrorState === 'running');
  const mirrorDisabled = $derived(!s.device || !s.mirror.available || mirrorState === 'starting');
  const mirrorLabel = $derived(!s.mirror.available ? t('mirror.missing') : mirrorState === 'starting' ? t('mirror.header_starting')
    : mirrorOn ? t('mirror.header_off') : t('mirror.header_on'));
  const findLabel = $derived(t(s.incident.recording ? 'header.find_source_recording' : 'header.find_source'));

  // Odczyt Firefoxa przez zdalne debugowanie pojawia się, gdy serwisant je włączy na telefonie: bez przycisku
  // ponowienia program sam sprawdza co kilka sekund, dopóki ekran Naprawa jest otwarty i podpowiedź jest prawdziwa
  // — na każdej zakładce, żeby licznik „Telefon” rósł też, gdy serwisant stoi na „Aplikacje” (spec §8a.5).
  // Tanio: telefon czyta tylko gniazdo debugowania, pełny odczyt witryn dopiero po jego pojawieniu się.
  const RECHECK_MS = 5000;
  const waitingForRdp = $derived(checks.some((c) => c.browsers.some((b) => b.rdp_hint)));

  $effect(() => {
    if (!waitingForRdp) return;
    const id = setInterval(() => void ctl.recheckSiteNotifications(true), RECHECK_MS);
    return () => clearInterval(id);
  });
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
        {#if !verdictsHidden}
          <Segmented label={t('results.mode')} value={s.settings.mode} options={modes} onchange={(m) => ctl.setMode(m)} />
        {/if}
        <div class="flex items-center gap-1.5">
          <Tooltip text={findLabel}>
            <Button size="icon" pressed={s.diagnostics} label={findLabel}
              onclick={() => (s.diagnostics ? ctl.closeDiagnostics() : ctl.openDiagnostics())}>
              <span class="relative grid"><Icon name="scan-search" />
                {#if s.incident.recording}<span data-recording class="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full bg-bad ring-2 ring-[var(--color-surface)]"></span>{/if}
              </span>
            </Button>
          </Tooltip>
          <Tooltip text={mirrorLabel}>
            <Button size="icon" pressed={mirrorOn} label={mirrorLabel} disabled={mirrorDisabled}
              onclick={() => (mirrorOn ? ctl.mirrorStop() : ctl.mirrorStart(s.device!.serial, s.device!.name))}>
              <Icon name={mirrorOn ? 'screen-share-off' : 'screen-share'} />
            </Button>
          </Tooltip>
        </div>
        <Button onclick={() => ctl.newScan()}><Icon name="rotate-ccw" />{t('actions.rescan')}</Button>
      </div>
      {#if manual}
        <h1 class="col-span-2 text-2xl font-extrabold">{t('manual.title')}</h1>
      {:else if choosing || undecided}
        <h1 class="col-span-2 text-2xl font-extrabold">{t('results.apk_title')}</h1>
      {:else if flagged.length > 0}
        <h1 class="col-span-2 text-2xl font-extrabold" aria-label={tp('results.title', flagged.length)}>
          {titleParts[0]}<CountUp value={flagged.length} />{titleParts[1]}
        </h1>
      {:else}
        <h1 class="col-span-2 text-2xl font-extrabold">{t(s.apk.running ? 'results.apk_title'
          : anyIncomplete ? 'results.clean_title_incomplete' : 'results.clean_title')}</h1>
      {/if}
    </header>

    {#if !manual && !choosing && (undecided || s.apk.running)}<ApkProgress calm={flagged.length === 0 || verdictsHidden} />{/if}
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
    {#if s.scan}
      <RepairTabs value={s.repairTab} onchange={(tab) => ctl.setRepairTab(tab)}
        appsCount={verdictsHidden || flagged.length === 0 ? null : flagged.length} {phone} />
    {/if}

    {#if s.repairTab === 'phone'}
      <div role="tabpanel" id="repair-panel-phone" aria-labelledby="repair-tab-phone" class="flex flex-col gap-4">
        <NoticeLine items={notes.phone} />
        <DeviceChecks />
        {#if !checks.length && !notes.phone.length}
          <p class="py-6 text-center text-mut">{t('repair_tabs.phone_empty')}</p>
        {/if}
      </div>
    {:else}
      <div role="tabpanel" id="repair-panel-apps" aria-labelledby="repair-tab-apps" class="flex flex-col gap-4">
        <NoticeLine items={notes.apps} details={noteDetails} />

        {#if choosing}
          <ApkModeChoice />
        {:else if manual}
          <ManualList />
        {:else if undecided || (flagged.length === 0 && s.apk.running)}
          <!-- W toku i nic jeszcze nie oznaczono: zamiast przedwczesnego „czysto” sama linia postępu u góry. -->
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
            <!-- Aplikacje czyste, a w „Telefon” jest coś do zrobienia (spec §8a.8): tytuł zostaje, odnośnik prowadzi dalej. -->
            {#if phone.kind !== 'ok'}
              <button type="button" class="mt-1 inline-flex items-center gap-1 rounded-md text-sm font-semibold text-accent outline-none hover:underline focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
                onclick={() => ctl.setRepairTab('phone')}>
                {phone.kind === 'count' ? tp('repair_tabs.phone_todo', phone.count) : t('repair_tabs.phone_unknown_link')}
                <Icon name="chevron-right" size={16} />
              </button>
            {/if}
          </div>
        {/if}
        {#if expert}
          <ExpertTable groups={expertGroups} {focused} {facets} {searching} {navRows} emptyDanger={emptyDangerVerdicts(apps)} />
        {:else if flagged.length > 0 && !verdictsHidden}
          <EmptyVerdicts verdicts={emptyDangerVerdicts(apps)} />
          {#each simpleGroups.filter((g) => g.verdict !== 'safe') as g (g.verdict)}
            {#if g.apps.length}
              <VerdictSection verdict={g.verdict} count={g.apps.length} open={isOpen(g.verdict)} apps={g.apps}
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
        {#if !expert && !verdictsHidden && safeGroup.apps.length}
          <VerdictSection verdict="safe" count={safeGroup.apps.length} open={isOpen('safe')} collapsible
            ontoggle={() => ctl.setGroupOpen('safe', !isOpen('safe'))}>
            {#each safeGroup.apps as app (app.package)}
              <AppCard {app} level={s.selection[app.package] ?? null} done={s.acted[app.package] ?? null} busy={s.orderRunning}
                onundo={() => ctl.undoApp(app.package)} onlevel={(level) => ctl.setLevel(app.package, level)} ontoggle={() => ctl.toggle(app)} />
            {/each}
          </VerdictSection>
        {/if}
      </div>
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
