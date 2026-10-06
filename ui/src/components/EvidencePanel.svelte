<script lang="ts">
  import { getContext } from 'svelte';
  import { CATEGORY_ICON, categoryKey } from '../lib/categories';
  import type { Controller } from '../lib/controller';
  import { t, tp } from '../lib/i18n/index.svelte';
  import { evidenceGroups, initial, planEntries, topReasons, VERDICT_TONE } from '../lib/logic';
  import type { AppView, Level } from '../lib/types';
  import Segmented from '../ui/Segmented.svelte';
  import Button from '../ui/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import Pill from '../ui/Pill.svelte';
  import AppIcon from './AppIcon.svelte';
  import ScoreScale from './ScoreScale.svelte';

  let { app }: { app: AppView | null } = $props();
  const ctl = getContext<Controller | undefined>('ctl');
  const groups = $derived(app ? evidenceGroups(app.findings) : { groups: [], combos: [] });
  const count = $derived(ctl ? planEntries(ctl.state.scan?.apps ?? [], ctl.state.selection).length : 0);
  // Surowe dane: jeden wpis na regułę. Lista SDK tylko wtedy, gdy nie wypisała jej już reguła DM-ADSDK.
  const raw = $derived.by(() => {
    if (!app) return [];
    const rows = app.findings.filter((f) => f.category !== 'combo')
      .map((f) => ({ key: f.rule_id, label: f.label, text: f.text_expert }));
    if (app.ad_sdks?.length && !app.findings.some((f) => f.rule_id.startsWith('DM-ADSDK')))
      rows.push({ key: 'ad_sdks', label: t('evidence.ad_sdks'), text: app.ad_sdks.join(', ') });
    return rows;
  });
  // Powody na górze: jedna etykieta na kategorię, bez punktów (punkty są w szczegółach technicznych).
  const reasons = $derived(app ? topReasons(app, 99, (c) => t(categoryKey(c))).items : []);
  const level = $derived(app && ctl ? ctl.state.selection[app.package] ?? null : null);
  const removed = $derived(!!app && !!ctl && ctl.state.acted[app.package] === 'remove');
  const LEVELS_ACT = $derived([
    { value: 'silence' as Level, label: t('choice.silence'), tone: 'accent' as const },
    { value: 'disable' as Level, label: t('choice.disable'), tone: 'warn' as const },
    { value: 'remove' as Level, label: t('choice.remove'), tone: 'bad' as const },
  ]);
  const BAR = { malicious: 'bg-bad', suspicious: 'bg-warn-strong', review: 'bg-soft', safe: 'bg-ok' };
  const SCORE = { malicious: 'text-bad', suspicious: 'text-warn', review: 'text-neutral', safe: 'text-ok' };
  // Ten sam wybór co w menu wiersza; ponowny klik w zaznaczoną opcję go czyści.
  function pick(v: Level) {
    if (!app || !ctl) return;
    ctl.setLevel(app.package, v === level ? null : v);
  }
  const LEVELS = ['declared', 'code', 'granted', 'observed'] as const;
  const mark = (v: boolean | null) => (v === null ? '?' : v ? '✓' : '—');
  const AVATAR = { malicious: 'bg-bad text-bad', suspicious: 'bg-warn-strong text-warn-strong', review: 'bg-soft text-soft', safe: 'bg-ok text-ok' };
</script>

{#if app}
  <div class="flex items-center gap-2.5">
    <AppIcon icon={app.icon} class="h-11 w-11">
      <span class="grid h-11 w-11 flex-none place-items-center rounded-[13px] shadow-[inset_0_1px_0_rgb(255_255_255/.3),0_6px_14px_-6px_currentColor] {AVATAR[app.verdict]}" aria-hidden="true"><span class="text-lg font-extrabold text-white">{initial(app.name)}</span></span>
    </AppIcon>
    <div class="min-w-0 flex-1"><b class="block truncate text-lg">{app.name}</b>{#if app.name !== app.package}<span class="mono block truncate text-2xs text-soft">{app.package}</span>{/if}</div>
    <Pill tone={VERDICT_TONE[app.verdict]}>{app.verdict_label}</Pill>
  </div>
  <div data-testid="score-line" class="flex items-center gap-2.5 text-sm">
    <span class="h-1.5 flex-1 overflow-hidden rounded-full bg-neutral-soft shadow-[var(--shadow-well)]"><i class="block h-full rounded-full {BAR[app.verdict]}" style="width: {app.score}%"></i></span>
    <b class="mono {SCORE[app.verdict]}">{app.score}</b><span class="text-mut">· {t(`evidence.conf.${app.confidence}`)}</span>
  </div>

  {#if reasons.length}
    <span class="lbl">{t('evidence.why')}</span>
    <ul aria-label={t('evidence.why')} class="well well-list flex flex-col p-3 [&>*+*]:mt-2 [&>*+*]:pt-2">
      {#each reasons as r (r.category)}
        <li class="flex items-center gap-2"><span class="text-mut"><Icon name={CATEGORY_ICON[r.category]} /></span>{r.label}</li>
      {/each}
    </ul>
  {/if}

  {#if ctl}
    <span class="lbl">{t('evidence.what_to_do')}</span>
    {#if removed}
      <div class="flex items-center gap-2 text-sm"><Pill tone="ok">{t('history.level_done.remove')}</Pill>
        <Button size="sm" variant="ghost" disabled={ctl.state.orderRunning} label={t('summary.undo_app', { name: app.name })}
          onclick={() => ctl.undoApp(app.package)}><Icon name="undo-2" size={14} />{t('history.undo_changes')}</Button></div>
    {:else}
      <Segmented stretch size="sm" label={t('evidence.what_to_do')} value={level} options={LEVELS_ACT} onchange={pick} />
    {/if}
  {/if}

  <details class="group text-xs" open={ctl?.state.detailsOpen ?? false}
    ontoggle={(e) => ctl?.setDetailsOpen(e.currentTarget.open)}>
    <summary class="flex cursor-pointer list-none items-center gap-1.5 text-sm font-semibold text-accent">
      <Icon name="chevron-right" size={14} class="transition-transform duration-150 group-open:rotate-90" />{t('evidence.technical')}
    </summary>
    <div class="mt-3 flex flex-col gap-3">
      <div><span class="lbl">{t('evidence.score')}</span><ScoreScale score={app.score} verdict={app.verdict} /></div>
      <div class="text-mut"><span class="lbl">{t('evidence.confidence')}</span> {app.confidence_label}</div>
      {#if app.gaps.length || app.scope?.length || app.incomplete}
        <div class="well p-3 text-xs">
          <span class="lbl block">{t('evidence.limits')}</span>
          <ul class="mt-1 list-disc pl-4">
            {#each app.gaps as g (g.key)}<li>{g.label}</li>{/each}
            {#if app.incomplete && !app.gaps.length}<li>{t('evidence.incomplete_data')}</li>{/if}
            {#each app.scope ?? [] as s (s.key)}<li>{s.label}</li>{/each}
          </ul>
        </div>
      {/if}
      <span class="lbl">{t('evidence.points')}</span>
      <div class="well well-list flex flex-col p-3.5 [&>*+*]:mt-2.5 [&>*+*]:pt-2.5">
        {#each groups.groups as g (g.category)}
          <div>
            <div class="flex items-center gap-2 font-bold"><span class="text-mut"><Icon name={CATEGORY_ICON[g.category]} /></span>{t(categoryKey(g.category))}</div>
            {#each g.items as f (f.rule_id)}
              <div class="flex gap-2 py-0.5 pl-[26px] text-ink"><span class="min-w-0 flex-1">{f.label}</span><span class="text-xs text-soft tabular-nums">+{f.weight}</span></div>
            {/each}
          </div>
        {/each}
        {#each groups.combos as c (c.rule_id)}
          <div class="flex gap-2 border-t border-dashed border-line pt-1.5 text-xs text-mut"><span class="flex-1">{c.label}</span><span class="text-soft tabular-nums">+{c.weight}</span></div>
        {/each}
        {#if app.apk_error}
          <div class="flex items-center gap-2 text-xs text-mut"><Icon name="triangle-alert" />{t('expert.apk_error')}: {app.apk_error}</div>
        {/if}
      </div>
      {#if app.capabilities?.length}
        <span class="lbl">{t('evidence.capabilities')}</span>
        <table class="well w-full text-xs">
          <thead>
            <tr class="text-left text-soft">
              <th scope="col" class="p-1.5 font-semibold"><span class="sr-only">{t('evidence.capabilities')}</span></th>
              {#each LEVELS as l (l)}<th scope="col" aria-label={t(`evidence.levels.${l}`)} title={t(`evidence.levels.${l}`)} class="p-1.5 text-center font-semibold">{t(`evidence.levels_short.${l}`)}</th>{/each}
            </tr>
          </thead>
          <tbody>
            {#each app.capabilities as c (c.key)}
              <tr class="border-t border-line">
                <th scope="row" class="p-1.5 text-left font-semibold">{c.label}</th>
                {#each LEVELS as l (l)}<td class="p-1.5 text-center tabular-nums">{mark(c.levels[l])}</td>{/each}
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
      {#if ctl}
        <div class="flex items-center gap-2.5 text-xs text-mut">
          <span class="min-w-0 flex-1">{t('evidence.deep_hint')}</span>
          <Button disabled={!ctl.state.device || ctl.state.job !== null || ctl.state.orderRunning} onclick={() => ctl.deepAnalyze(app.package)}>{t('evidence.deep')}</Button>
        </div>
      {/if}
      <details class="group text-xs">
        <summary class="flex cursor-pointer list-none items-center gap-1.5 font-semibold text-accent">
          <Icon name="chevron-right" size={14} class="transition-transform duration-150 group-open:rotate-90" />{t('evidence.raw')}
        </summary>
        <ul aria-label={t('evidence.raw')} class="well well-list mt-2 flex flex-col">
          {#each raw as r (r.key)}
            <li class="px-3 py-2">
              <span class="block text-xs font-bold text-ink">{r.label}</span>
              <span class="mono mt-0.5 block text-2xs break-words whitespace-pre-wrap text-mut">{r.text}</span>
            </li>
          {/each}
        </ul>
      </details>
    </div>
  </details>
{:else}
  <p class="text-mut">{t('evidence.none')}</p>
{/if}
{#if ctl}
  <div class="mt-auto flex items-center gap-2.5 border-t border-line pt-3">
    <div class="min-w-0 flex-1"><span class="lbl block">{t('evidence.plan')}</span><b>{tp('panel.apps', count)}</b></div>
    <Button variant="primary" disabled={count === 0 || ctl.state.orderRunning} onclick={() => ctl.openPlan()}>{t('evidence.fix', { count })}</Button>
  </div>
{/if}
